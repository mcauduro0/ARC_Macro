"""Co-pilot (human-in-the-loop) invariant tests — pure pandas/numpy; no engine, no network.

The co-pilot adds a THIRD stream (``operator``) for the human's decisions, on top of the deterministic
``frozen`` (scored holdout) and ``live`` (auto baseline) streams. The non-negotiable invariant: NOTHING
the human does can change the frozen holdout the verdict scores. These tests prove that, plus the
operator stream's idempotency/immutability/guards and its realized-return arithmetic.
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from arc.autonomy.copilot import copilot_status, decide, propose
from arc.autonomy.governance import book_trial
from arc.autonomy.ledger import PaperLedger, RepaintError
from arc.autonomy.loop import run_loop
from arc.autonomy.paper import reconcile, reconcile_operator, turnover_cost
from arc.autonomy.source import monthly_return_provider
from arc.autonomy.spec import FROZEN_SPEC, strategy_hash


# ----------------------------------------------------------------- fixtures
def _ar1(n=80, phi=0.55, scale=0.02, seed=7):
    rng = np.random.default_rng(seed)
    x = np.zeros(n)
    for t in range(1, n):
        x[t] = phi * x[t - 1] + rng.normal(scale=scale)
    return pd.Series(x, index=pd.date_range("2008-01-31", periods=n, freq="ME"))


def _copilot_ledger(tmp_path):
    led = PaperLedger(tmp_path)
    book_trial(led, n_trials=45, sr_std=0.07, eval_at_n=24, dsr_min=0.50, issued_by="test-human")
    return led


def _run_copilot(led, r, action, *, position=None, start=20):
    """Drive the co-pilot month-by-month with a fixed action; return the list of decided months."""
    prov = monthly_return_provider(r, pub_lag_days=1)
    months = []
    for m in r.index[start:]:
        p = propose(m + pd.Timedelta(days=2), prov, led)
        if p.month:
            decide(led, month=p.month, action=action, position=position, rationale="t", decided_by="t")
            months.append(p.month)
    asof = r.index[-1] + pd.Timedelta(days=5)
    reconcile(asof, r, led)
    reconcile_operator(asof, r, led)
    return months


# ============================================================ THE invariant: frozen is untouchable
def test_human_skip_never_touches_the_frozen_holdout(tmp_path):
    """INV (co-pilot prime directive): whatever the human does (here: SKIP everything), the frozen stream
    the verdict scores is byte-IDENTICAL to a no-co-pilot run. The human can never corrupt the holdout."""
    r = _ar1(60)
    led = _copilot_ledger(tmp_path)
    _run_copilot(led, r, "SKIP")
    fz, op = led.frozen_frame(), led.operator_frame()

    # operator skipped everything -> all operator positions flat; but frozen is the real signal, nonzero
    assert (op["held_position"].abs() < 1e-12).all()
    assert (fz["held_position"].abs() > 1e-9).any()

    # control: the SAME ledger machinery with NO co-pilot calls at all
    ctrl = _copilot_ledger(tmp_path / "ctrl")
    prov = monthly_return_provider(r, pub_lag_days=1)
    for m in r.index[20:]:
        run_loop(m + pd.Timedelta(days=2), prov, ctrl)
    reconcile(r.index[-1] + pd.Timedelta(days=5), r, ctrl)
    fz2 = ctrl.frozen_frame()

    common = fz.index.intersection(fz2.index)
    assert len(common) == len(fz2) == len(fz)
    assert (fz.loc[common, "sleeve_return"] - fz2.loc[common, "sleeve_return"]).abs().max() < 1e-12
    assert (fz.loc[common, "held_position"] - fz2.loc[common, "held_position"]).abs().max() < 1e-12


def test_propose_accrues_frozen_without_any_human_decision(tmp_path):
    """The holdout is independent of the human: proposing (advancing the loop) accrues frozen even if the
    human NEVER decides — and the operator stream stays empty until the human acts."""
    r = _ar1(60)
    led = _copilot_ledger(tmp_path)
    prov = monthly_return_provider(r, pub_lag_days=1)
    for m in r.index[20:]:
        propose(m + pd.Timedelta(days=2), prov, led)  # never decide
    reconcile(r.index[-1] + pd.Timedelta(days=5), r, led)
    assert led.frozen_frame().shape[0] > 0          # holdout accrued anyway
    assert len(led.operator_decisions()) == 0       # human never acted
    assert led.operator_frame().shape[0] == 0       # operator stream empty


# ============================================================ propose -> decide flow
def test_approve_reproduces_the_live_baseline(tmp_path):
    """APPROVE takes the loop's (breaker-adjusted) live position, so on every shared month the operator
    stream equals the deterministic live baseline to 1e-12 (the human added no deviation)."""
    r = _ar1(60)
    led = _copilot_ledger(tmp_path)
    _run_copilot(led, r, "APPROVE")
    op, lv = led.operator_frame(), led.live_frame()
    common = op.index.intersection(lv.index)
    assert len(common) == len(lv) > 0          # live drops only its boundary first month
    assert (op.loc[common, "sleeve_return"] - lv.loc[common, "sleeve_return"]).abs().max() < 1e-12


def test_operator_reconcile_arithmetic(tmp_path):
    """Each operator realization is exactly held*realized - turnover(held, prev, cost_bps)."""
    r = _ar1(40)
    led = _copilot_ledger(tmp_path)
    _run_copilot(led, r, "OVERRIDE", position=1.0, start=20)
    reals = led.realizations("operator")
    assert len(reals) > 0
    for rec in reals.values():
        expected = rec.held_position * rec.realized_return - turnover_cost(
            rec.held_position, rec.prev_held, float(FROZEN_SPEC["cost_bps"]))
        assert abs(rec.sleeve_return - expected) < 1e-12


def test_proposal_digest_binds_the_decision(tmp_path):
    r = _ar1(40)
    led = _copilot_ledger(tmp_path)
    prov = monthly_return_provider(r, pub_lag_days=1)
    p = propose(r.index[25] + pd.Timedelta(days=2), prov, led)
    od = decide(led, month=p.month, action="APPROVE", rationale="ok", decided_by="t")
    assert od.proposal_digest == p.proposal_digest and len(od.proposal_digest) == 16
    assert od.strategy_hash == strategy_hash(FROZEN_SPEC)


# ============================================================ guards & immutability
def test_override_records_custom_size(tmp_path):
    r = _ar1(40)
    led = _copilot_ledger(tmp_path)
    prov = monthly_return_provider(r, pub_lag_days=1)
    p = propose(r.index[25] + pd.Timedelta(days=2), prov, led)
    od = decide(led, month=p.month, action="OVERRIDE", position=0.33, rationale="half", decided_by="t")
    assert od.action == "OVERRIDE" and abs(od.operator_position - 0.33) < 1e-12


def test_override_fat_finger_and_missing_position_raise(tmp_path):
    r = _ar1(40)
    led = _copilot_ledger(tmp_path)
    prov = monthly_return_provider(r, pub_lag_days=1)
    p = propose(r.index[25] + pd.Timedelta(days=2), prov, led)
    with pytest.raises(ValueError):
        decide(led, month=p.month, action="OVERRIDE", position=99.0, rationale="oops", decided_by="t")
    with pytest.raises(ValueError):
        decide(led, month=p.month, action="OVERRIDE", position=None, rationale="x", decided_by="t")


def test_invalid_action_raises(tmp_path):
    r = _ar1(40)
    led = _copilot_ledger(tmp_path)
    prov = monthly_return_provider(r, pub_lag_days=1)
    p = propose(r.index[25] + pd.Timedelta(days=2), prov, led)
    with pytest.raises(ValueError):
        decide(led, month=p.month, action="YOLO", rationale="x", decided_by="t")


def test_decide_requires_an_existing_decision(tmp_path):
    led = _copilot_ledger(tmp_path)
    with pytest.raises(ValueError):
        decide(led, month="2030-01-31", action="APPROVE", rationale="x", decided_by="t")


def test_operator_decision_is_immutable(tmp_path):
    """Idempotent on identical re-commit; a DIFFERENT later choice for the same month raises (no repaint
    of one's own forward track record)."""
    r = _ar1(40)
    led = _copilot_ledger(tmp_path)
    prov = monthly_return_provider(r, pub_lag_days=1)
    p = propose(r.index[25] + pd.Timedelta(days=2), prov, led)
    decide(led, month=p.month, action="APPROVE", rationale="ok", decided_by="t")
    decide(led, month=p.month, action="APPROVE", rationale="different note", decided_by="t")  # no-op
    assert len(led.operator_decisions()) == 1
    with pytest.raises(RepaintError):
        decide(led, month=p.month, action="SKIP", rationale="changed mind", decided_by="t")


def test_duplicate_operator_decision_is_fatal_on_read(tmp_path):
    """Two operator decisions for one (month,hash) raise on read — no silent last-wins."""
    r = _ar1(40)
    led = _copilot_ledger(tmp_path)
    prov = monthly_return_provider(r, pub_lag_days=1)
    p = propose(r.index[25] + pd.Timedelta(days=2), prov, led)
    od = decide(led, month=p.month, action="APPROVE", rationale="ok", decided_by="t")
    from dataclasses import asdict
    led._append(PaperLedger.OPERATOR, {"kind": "operator_decision", **asdict(od)})  # forced duplicate
    from arc.autonomy.ledger import LedgerIntegrityError
    with pytest.raises(LedgerIntegrityError):
        led.operator_decisions()


# ============================================================ status discipline
def test_copilot_status_exposes_no_scores(tmp_path):
    """Like forward_telemetry, the co-pilot status is operational only — never a Sharpe/DSR/IC back door."""
    r = _ar1(60)
    led = _copilot_ledger(tmp_path)
    _run_copilot(led, r, "APPROVE")
    st = copilot_status(led, strategy="momentum")
    keys = set()
    for sub in ("frozen", "live", "operator"):
        keys |= set(st[sub].keys())
    for forbidden in ("sharpe", "dsr", "psr", "ic", "sr_annual", "psr"):
        assert not any(forbidden in k for k in keys)
    assert st["operator"]["n"] > 0 and st["n_operator_decisions"] > 0
    json.dumps(st)  # serializable
