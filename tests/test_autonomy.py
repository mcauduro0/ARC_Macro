"""Phase 7 autonomy spine — CI-native invariant tests (pure pandas/numpy; no engine, no network).

Each test maps to a non-negotiable invariant from the adversarial governance + look-ahead audit. These
are the structural proofs that the paper loop cannot quietly turn the single-use forward holdout back
into a re-peekable, under-deflated, left-tail-truncated backtest.
"""

from __future__ import annotations

import json
from dataclasses import asdict

import numpy as np
import pandas as pd
import pytest

from arc.autonomy.governance import book_trial, issue_token
from arc.autonomy.ledger import (
    DataRevisionError,
    Decision,
    DeflationBasis,
    HoldoutConsumedError,
    HoldoutConsumedRecord,
    HoldoutNotReadyError,
    LedgerIntegrityError,
    MissingDeflationBasisError,
    PaperLedger,
    Realization,
    TrialBooking,
    UnbookedTrialError,
    VerdictRecord,
)
from arc.autonomy.loop import run_loop
from arc.autonomy.monitor import MonitorConfig, circuit_breaker, promotion_verdict
from arc.autonomy.paper import forward_telemetry, reconcile, tick
from arc.autonomy.source import knowledge_time, monthly_return_provider
from arc.autonomy.spec import (
    FROZEN_HASH,
    FROZEN_SPEC,
    HARD_PB_SPEC,
    NOWCAST_SPEC,
    SPECS,
    strategy_hash,
)
from arc.eval.gate import sharpe_stats
from arc.eval.governance import HoldoutToken
from arc.research.sleeve import momentum_sleeve_returns, signal_sleeve_returns


# ----------------------------------------------------------------- fixtures
def _ar1(n=80, phi=0.55, scale=0.02, seed=7):
    rng = np.random.default_rng(seed)
    x = np.zeros(n)
    for t in range(1, n):
        x[t] = phi * x[t - 1] + rng.normal(scale=scale)
    return pd.Series(x, index=pd.date_range("2008-01-31", periods=n, freq="ME"))


def _booked_ledger(tmp_path, **kw):
    led = PaperLedger(tmp_path)
    book_trial(led, n_trials=45, sr_std=0.07, eval_at_n=kw.get("eval_at_n", 24),
               dsr_min=kw.get("dsr_min", 0.50), issued_by="test-human", min_forward_n=kw.get("min_n", 24))
    return led


def _seed_frozen(led, vals, start="2024-01-31", pos=0.5):
    """Append N decisions + N frozen realizations with given sleeve returns (bypasses tick; for verdict
    tests). Decisions are required because frozen_frame inner-joins decisions with realizations."""
    idx = pd.date_range(start, periods=len(vals), freq="ME")
    for k, (m, v) in enumerate(zip(idx, vals)):
        miso = m.strftime("%Y-%m-%d")
        led.append_decision(Decision(
            month=miso, strategy_hash=FROZEN_HASH, frozen_position=pos, live_position=pos,
            signal=0.0, signal_z=0.0, data_max_knowledge_time=miso, input_digest=f"seed{k}",
            run_id="seed", created_at=miso))
        led.append_realization(Realization(
            month=miso, strategy_hash=FROZEN_HASH, stream="frozen", held_position=pos, prev_held=pos,
            realized_return=float(v), sleeve_return=float(v), realized_knowledge_time=miso,
            return_vintage_seq=0, reconciled_at=miso, run_id="seed"))


# ============================================================ A. look-ahead / equivalence
def test_golden_forward_equivalence(tmp_path):
    """INV1: ticking each month + reconciling rebuilds a stream byte-equal to momentum_sleeve_returns."""
    r = _ar1(80)
    led = _booked_ledger(tmp_path)
    for i in range(len(r)):
        tick(r.index[i], r.iloc[: i + 1], led, run_id="g")
    reconcile(r.index[-1] + pd.Timedelta(days=5), r, led, settlement_lag=pd.Timedelta(0))
    fz = led.frozen_frame()
    expected = momentum_sleeve_returns(r, lookback=3, z_window=12, clip_z=2.0, cost_bps=2.0)
    common = fz.index.intersection(expected.index)
    assert len(common) == len(expected)  # every sleeve month reconstructed (no off-by-one)
    assert (fz.loc[common, "sleeve_return"] - expected.loc[common]).abs().max() < 1e-9


def test_forward_start_excludes_in_sample_months(tmp_path):
    """INV (honesty): months at/before the research cutoff are used to COMPUTE the position but are
    NEVER recorded as holdout — in-sample history cannot leak into the forward stream."""
    r = _ar1(60)
    led = _booked_ledger(tmp_path)
    cutoff = r.index[40]
    for i in range(len(r)):
        tick(r.index[i], r.iloc[: i + 1], led, run_id="fs", forward_start=cutoff)
    months = [pd.Timestamp(m) for m in led.decisions()]
    assert months, "expected some forward decisions"
    assert all(m > cutoff for m in months)  # nothing at/before the cutoff was recorded


def test_external_signal_tick_equivalence(tmp_path):
    """The generic (external-signal) tick + reconcile rebuilds signal_sleeve_returns to 1e-9 — proving
    the multi-strategy path (e.g. the nowcast) is as honest as the momentum path."""
    r = _ar1(80, seed=11)
    sig = _ar1(80, seed=12)  # an independent point-in-time signal (not derived from returns)
    led = PaperLedger(tmp_path)
    book_trial(led, spec=NOWCAST_SPEC, n_trials=55, sr_std=None, eval_at_n=24, dsr_min=0.5, issued_by="t")
    for i in range(len(r)):
        tick(r.index[i], r.iloc[: i + 1], led, spec=NOWCAST_SPEC, signal_through_K=sig.iloc[: i + 1], run_id="g")
    reconcile(r.index[-1] + pd.Timedelta(days=5), r, led, spec=NOWCAST_SPEC)
    fz = led.frozen_frame()
    expected = signal_sleeve_returns(sig, r, z_window=12, clip_z=2.0, cost_bps=2.0)
    common = fz.index.intersection(expected.index)
    assert len(common) == len(expected)
    assert (fz.loc[common, "sleeve_return"] - expected.loc[common]).abs().max() < 1e-9


def test_run_loop_hosts_second_strategy(tmp_path):
    """run_loop with a signal_provider hosts a non-momentum strategy (the nowcast) end to end."""
    r = _ar1(60, seed=13)
    sig = _ar1(60, seed=14)
    led = PaperLedger(tmp_path)
    book_trial(led, spec=NOWCAST_SPEC, n_trials=55, sr_std=None, eval_at_n=24, dsr_min=0.5, issued_by="t")
    prov = monthly_return_provider(r, pub_lag_days=1)
    sigprov = lambda asof: sig[sig.index <= pd.Timestamp(asof)]  # noqa: E731
    out = None
    for mo in r.index[20:]:
        out = run_loop(mo + pd.Timedelta(days=2), prov, led, spec=NOWCAST_SPEC, signal_provider=sigprov)
    assert out["proposal"]["strategy_hash"] == strategy_hash(NOWCAST_SPEC)
    assert led.frozen_frame().shape[0] > 0


def test_decision_keyed_to_next_month(tmp_path):
    """INV2: a decision is keyed to the month AFTER the latest known return; never uses its own month."""
    r = _ar1(40)
    led = _booked_ledger(tmp_path)
    d = tick(r.index[20], r.iloc[:21], led, run_id="k")
    assert d is not None
    assert pd.Timestamp(d.month) > r.index[20]
    assert pd.Timestamp(d.data_max_knowledge_time) == r.index[20]


def test_no_recompute_on_reconcile(tmp_path, monkeypatch):
    """INV3: reconcile multiplies the STORED position — it never recomputes the (expanding-z) signal."""
    r = _ar1(60)
    led = _booked_ledger(tmp_path)
    for i in range(len(r)):
        tick(r.index[i], r.iloc[: i + 1], led, run_id="nr")
    import arc.autonomy.paper as paper_mod

    def _boom(*a, **k):
        raise AssertionError("causal_position must NOT be called during reconcile")

    monkeypatch.setattr(paper_mod, "causal_position", _boom)
    recs = reconcile(r.index[-1] + pd.Timedelta(days=5), r, led)
    assert len(recs) > 0  # reconciled without recomputing


def test_publication_lag_boundary():
    """INV12: a month-M return is invisible until its knowledge time (the one look-ahead boundary)."""
    r = _ar1(12)
    prov = monthly_return_provider(r, pub_lag_days=1)
    may = r.index[4]
    assert may not in prov(may).index                      # not knowable within its own month
    assert may in prov(knowledge_time(may, 1)).index       # knowable the next day
    assert len(prov(may - pd.Timedelta(days=1)).index) == 4


# ============================================================ D. ledger integrity
def test_idempotent_retick(tmp_path):
    """INV3/idempotency: re-ticking a month is a no-op (one record, no overwrite)."""
    r = _ar1(40)
    led = _booked_ledger(tmp_path)
    tick(r.index[20], r.iloc[:21], led, run_id="a")
    tick(r.index[20], r.iloc[:21], led, run_id="b")  # identical re-tick
    assert len(led.decisions()) == 1


def test_data_revision_detected(tmp_path):
    """INV3: same (month,hash) with a different input slice raises rather than silently repainting."""
    r = _ar1(40)
    led = _booked_ledger(tmp_path)
    tick(r.index[20], r.iloc[:21], led, run_id="a")
    r2 = r.iloc[:21].copy()
    r2.iloc[-1] += 0.05  # revised final return -> different input_digest, same earned month
    with pytest.raises(DataRevisionError):
        tick(r.index[20], r2, led, run_id="b")


def test_duplicate_decision_is_fatal_on_read(tmp_path):
    """INV4: two decisions for the same (month,hash) raise on read — no silent last-wins repaint."""
    led = PaperLedger(tmp_path)
    d = Decision(month="2024-03-31", strategy_hash=FROZEN_HASH, frozen_position=0.3, live_position=0.3,
                 signal=0.0, signal_z=0.0, data_max_knowledge_time="2024-02-29", input_digest="x",
                 run_id="r", created_at="2024-03-31")
    led._append(PaperLedger.DECISIONS, {"kind": "decision", **asdict(d)})
    led._append(PaperLedger.DECISIONS, {"kind": "decision", **asdict(d)})  # forced duplicate
    with pytest.raises(LedgerIntegrityError):
        led.decisions()


def test_corrupt_line_is_quarantined(tmp_path):
    """INV4: a corrupt line (anywhere) is quarantined to .corrupt; valid records still read."""
    r = _ar1(40)
    led = _booked_ledger(tmp_path)
    tick(r.index[20], r.iloc[:21], led, run_id="a")
    path = led._path(PaperLedger.DECISIONS)
    with open(path, "a", encoding="ascii") as f:
        f.write("this is not valid json or checksum\n")
    decs = led.decisions()  # quarantines the bad line, returns the good one
    assert len(decs) == 1
    assert path.with_suffix(path.suffix + ".corrupt").exists()


def test_checksum_detects_tamper(tmp_path):
    """INV4: editing a field without fixing record_sha invalidates the line (quarantined)."""
    r = _ar1(40)
    led = _booked_ledger(tmp_path)
    tick(r.index[20], r.iloc[:21], led, run_id="a")
    path = led._path(PaperLedger.DECISIONS)
    lines = path.read_text(encoding="ascii").splitlines()
    obj = json.loads(lines[0])
    obj["frozen_position"] = 99.0  # tamper, leave record_sha stale
    path.write_text(json.dumps(obj, separators=(",", ":")) + "\n", encoding="ascii")
    assert len(led.decisions()) == 0  # tampered line rejected
    assert path.with_suffix(path.suffix + ".corrupt").exists()


# ============================================================ B/F. holdout & verdict
def test_unbooked_trial_refused(tmp_path):
    """INV7: ticking a hash with no booked trial raises (forward data can't accrue un-booked)."""
    r = _ar1(40)
    led = PaperLedger(tmp_path)  # NOT booked
    with pytest.raises(UnbookedTrialError):
        tick(r.index[20], r.iloc[:21], led, run_id="a")


def test_forward_telemetry_exposes_no_scores(tmp_path):
    """INV5: token-free telemetry exposes operational state only — no Sharpe/DSR/IC."""
    led = _booked_ledger(tmp_path)
    _seed_frozen(led, [0.01] * 10)
    tel = forward_telemetry(led)
    fields = set(asdict(tel).keys())
    for forbidden in ("sharpe", "dsr", "psr", "ic", "sr_annual", "sharpe_ann"):
        assert not any(forbidden in f for f in fields)


def test_promotion_requires_deflation_basis(tmp_path):
    """INV6: a verdict with no persisted deflation basis raises — never defaults to a weak bar."""
    led = PaperLedger(tmp_path)
    led.append_booking(TrialBooking(FROZEN_HASH, "front/mom3", "human", ""))  # booked but NO basis
    _seed_frozen(led, list(np.full(24, 0.01)))
    tok = issue_token(issued_by="human")
    with pytest.raises(MissingDeflationBasisError):
        promotion_verdict(led, tok, asof="2026-01-31")


def test_verdict_reproduces_gate_deflation(tmp_path):
    """INV6: forward DSR == gate.sharpe_stats(returns, n_trials, sr_std) with the persisted basis."""
    led = _booked_ledger(tmp_path, eval_at_n=24, dsr_min=0.10)
    rng = np.random.default_rng(3)
    vals = list(0.004 + rng.normal(scale=0.01, size=24))
    _seed_frozen(led, vals)
    tok = issue_token(issued_by="human")
    v = promotion_verdict(led, tok, asof="2026-01-31")
    basis = led.basis_for(FROZEN_HASH)
    expected = sharpe_stats(np.array(vals), n_trials=basis.n_trials, sr_std=basis.sr_std)
    assert abs(v["dsr"] - expected["dsr"]) < 1e-9
    assert "ic" not in v  # INV9: no raw-IC-vs-carry-neutral-bar criterion


def test_verdict_is_one_shot_and_deterministic_on_read(tmp_path):
    """INV5/INV11: a second verdict call returns the RECORDED verdict; it never re-scores or re-consumes."""
    led = _booked_ledger(tmp_path, eval_at_n=24, dsr_min=0.10)
    rng = np.random.default_rng(4)
    _seed_frozen(led, list(0.004 + rng.normal(scale=0.01, size=24)))
    v1 = promotion_verdict(led, issue_token(issued_by="h"), asof="2026-01-31")
    n_consumed_after_first = len(led.consumed_hashes())
    v2 = promotion_verdict(led, issue_token(issued_by="h"), asof="2026-02-28")  # fresh token, same hash
    assert v1 == v2
    assert len(led.consumed_hashes()) == n_consumed_after_first  # no second consumption


def test_duplicate_verdict_is_fatal_on_read(tmp_path):
    """INV4/INV11: two verdict records for one hash raise on read — no last-wins on the holdout verdict."""
    led = PaperLedger(tmp_path)
    v = VerdictRecord(FROZEN_HASH, True, "PASS", 0.6, 1.0, 24, 0.5, 45, 0.07, "2026-01-31", "r")
    led.append_verdict(v)
    led.append_verdict(v)  # forced duplicate (idempotency is not enforced on verdicts; read must catch it)
    with pytest.raises(LedgerIntegrityError):
        led.verdict_for(FROZEN_HASH)


def test_consumed_without_verdict_is_fail_closed(tmp_path):
    """INV5: a durable consumption with no rendered verdict (prior crash) leaves the holdout SPENT."""
    led = _booked_ledger(tmp_path, eval_at_n=24, dsr_min=0.10)
    _seed_frozen(led, list(np.full(24, 0.01)))
    led.append_consumed(HoldoutConsumedRecord(FROZEN_HASH, "h", 24, "2026-01-31", "crash"))  # no verdict
    with pytest.raises(HoldoutConsumedError):
        promotion_verdict(led, issue_token(issued_by="h"), asof="2026-02-28")


def test_pre_committed_eval_at_n(tmp_path):
    """INV11: a verdict before/after the pre-committed sample size refuses to consume (no optional stop)."""
    led = _booked_ledger(tmp_path, eval_at_n=24, dsr_min=0.10)
    _seed_frozen(led, list(np.full(20, 0.01)))  # too few
    with pytest.raises(HoldoutNotReadyError):
        promotion_verdict(led, issue_token(issued_by="h"), asof="2026-01-31")
    _seed_frozen(led, list(np.full(8, 0.01)), start="2025-09-30")  # now overshoots 24
    with pytest.raises(HoldoutNotReadyError):
        promotion_verdict(led, issue_token(issued_by="h"), asof="2026-06-30")


def test_verdict_nan_fatal(tmp_path):
    """INV11: a degenerate forward sample (zero variance -> NaN DSR) FAILS, never passes."""
    led = PaperLedger(tmp_path)
    led.append_booking(TrialBooking(FROZEN_HASH, "front/mom3", "human", ""))
    led.append_basis(DeflationBasis(FROZEN_HASH, 45, 0.07, 24, 0.10, None, "human", ""))
    _seed_frozen(led, list(np.full(24, 0.01)))  # constant -> sd 0 -> NaN DSR
    v = promotion_verdict(led, issue_token(issued_by="h"), asof="2026-01-31")
    assert v["passed"] is False
    assert "NaN" in v["reason"] or "degenerate" in v["reason"]


def test_token_must_bind_to_frozen_hash(tmp_path):
    """A token bound to a different spec cannot score the frozen holdout."""
    led = _booked_ledger(tmp_path, eval_at_n=24, dsr_min=0.10)
    _seed_frozen(led, list(np.full(24, 0.01)))
    wrong = HoldoutToken(strategy_hash="deadbeefdeadbeef", issued_by="h")
    with pytest.raises(ValueError):
        promotion_verdict(led, wrong, asof="2026-01-31")


# ============================================================ E. frozen vs live separation
def test_halt_zeroes_live_not_frozen(tmp_path):
    """INV8: a halt zeroes the LIVE position but never the FROZEN (scored) position."""
    r = _ar1(40)
    led = _booked_ledger(tmp_path)
    tick(r.index[18], r.iloc[:19], led, run_id="a", halted=False)
    d = tick(r.index[19], r.iloc[:20], led, run_id="b", halted=True)
    assert d.live_position == 0.0
    assert d.frozen_position != 0.0  # frozen = the real signal, untouched by the halt
    reconcile(r.index[-1] + pd.Timedelta(days=5), r, led)
    fz, lv = led.frozen_frame(), led.live_frame()
    m = d.month
    assert pd.Timestamp(m) in fz.index and pd.Timestamp(m) in lv.index
    assert fz.loc[pd.Timestamp(m), "held_position"] == d.frozen_position
    assert lv.loc[pd.Timestamp(m), "held_position"] == 0.0


def test_circuit_breaker_does_not_mutate(tmp_path):
    """INV8: the breaker reads the live frame and returns state; it mutates no record."""
    led = _booked_ledger(tmp_path)
    _seed_frozen(led, list(np.full(10, -0.02)))  # also creates frozen frame
    before = led.frozen_frame().copy()
    circuit_breaker(led.live_frame(), MonitorConfig())
    after = led.frozen_frame()
    pd.testing.assert_frame_equal(before, after)


def test_circuit_breaker_halts_on_drawdown(tmp_path):
    """The breaker trips on a live drawdown beyond the threshold (operational, live-only)."""
    led = PaperLedger(tmp_path)
    # seed a live stream with a clear drawdown
    idx = pd.date_range("2024-01-31", periods=8, freq="ME")
    for k, m in enumerate(idx):
        miso = m.strftime("%Y-%m-%d")
        led.append_decision(Decision(miso, FROZEN_HASH, 0.5, 0.5, 0.0, 0.0, miso, f"x{k}", "s", miso))
        led.append_realization(Realization(miso, FROZEN_HASH, "live", 0.5, 0.5, -0.05, -0.05,
                                            miso, 0, miso, "s"))
    st = circuit_breaker(led.live_frame(), MonitorConfig(dd_halt=-0.03))
    assert st.halted is True and st.live_drawdown <= -0.03


# ============================================================ loop orchestration
def test_run_loop_accumulates_and_proposes(tmp_path):
    """The deterministic loop, driven over months by the as-of provider, accumulates the frozen stream
    and emits a human-approval Proposal (it never scores the holdout)."""
    r = _ar1(60)
    led = _booked_ledger(tmp_path)
    prov = monthly_return_provider(r, pub_lag_days=1)
    out = None
    for m in r.index[20:]:
        out = run_loop(m + pd.Timedelta(days=2), prov, led, cfg=MonitorConfig(), vol_target=0.10)
    assert out["proposal"]["human_approval_required"] is True
    assert out["proposal"]["strategy_hash"] == strategy_hash(FROZEN_SPEC)
    assert out["proposal"]["action"] in ("OPERATE", "HALT", "HOLD(warmup)")
    assert "dsr" not in out["proposal"] and "sharpe_ann" not in out["proposal"]  # no scoring in the loop
    assert led.frozen_frame().shape[0] > 0


def test_run_loop_is_deterministic(tmp_path):
    """Same ledger state + same asof + same returns => identical Proposal (idempotent re-run)."""
    r = _ar1(50)
    led = _booked_ledger(tmp_path)
    prov = monthly_return_provider(r, pub_lag_days=1)
    for m in r.index[20:40]:
        run_loop(m + pd.Timedelta(days=2), prov, led)
    asof = r.index[40] + pd.Timedelta(days=2)
    a = run_loop(asof, prov, led)["proposal"]
    b = run_loop(asof, prov, led)["proposal"]  # re-run, idempotent
    # JSON-compare so identical NaN fields (e.g. the gate-off VaR forecast) count as equal (NaN != NaN)
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


# ----------------------------------------------------------------- registry: the three booked edges
def test_specs_registry_holds_three_distinct_booked_edges():
    """The multi-strategy paper loop hosts exactly three booked candidate sleeves, each with a DISTINCT
    binding hash (changing any spec field forks a new trial). Locks the registry so an accidental spec
    edit can never silently re-point a forward holdout."""
    assert set(SPECS) == {"momentum_front", "nowcast_long", "fiscal_hard"}
    assert SPECS["momentum_front"] is FROZEN_SPEC
    assert SPECS["fiscal_hard"] is HARD_PB_SPEC
    hashes = {name: strategy_hash(spec) for name, spec in SPECS.items()}
    assert len(set(hashes.values())) == 3, f"hash collision across edges: {hashes}"
    # the fiscal candidate's contract (Phase 4.5 re-test): primary-balance momentum on the sovereign spread
    assert HARD_PB_SPEC["instrument"] == "hard"
    assert HARD_PB_SPEC["kind"] == "fiscal_momentum"
    assert HARD_PB_SPEC["lookback"] == 6
    # every spec carries the fields tick() reads to form a position
    for spec in SPECS.values():
        for field in ("instrument", "kind", "z_window", "clip_z", "cost_bps"):
            assert field in spec


def test_fiscal_sleeve_runs_through_the_loop_with_an_external_signal(tmp_path):
    """The fiscal candidate drives positions via an EXTERNAL oriented signal (primary_balance.diff(6)),
    exactly like the nowcast — the loop/tick path is signal-kind-agnostic. Booking HARD_PB_SPEC and
    feeding a signal_provider must accrue frozen decisions (no momentum fallback, no crash)."""
    r = _ar1(60)
    sig = r.rolling(6).sum()  # any oriented monthly signal aligned to the return index
    led = PaperLedger(tmp_path)
    book_trial(led, spec=HARD_PB_SPEC, n_trials=69, sr_std=0.07, eval_at_n=24, dsr_min=0.50,
               issued_by="test")
    prov = monthly_return_provider(r, pub_lag_days=1)
    sigprov = lambda asof: sig[sig.index <= pd.Timestamp(asof)]  # noqa: E731
    for m in r.index[20:]:
        run_loop(m + pd.Timedelta(days=2), prov, led, spec=HARD_PB_SPEC,
                 signal_provider=sigprov, vol_target=0.10)
    fz = led.frozen_frame()
    assert fz.shape[0] > 0
    assert all(d.strategy_hash == strategy_hash(HARD_PB_SPEC) for d in led.decisions().values())


def test_build_signal_is_the_single_source_of_truth_per_kind():
    """Every front-end (CLI, readiness harness, monthly accrual, Dagster) builds each edge's signal via
    the ONE shared `build_signal`. Momentum -> None (loop uses returns); fiscal -> primary_balance.diff(L);
    unknown kind/input -> raises (fail loud, never silently fall back to a different strategy — the bug
    that the per-file duplicate copies caused)."""
    from arc.autonomy import build_signal
    idx = pd.date_range("2010-01-31", periods=40, freq="ME")
    pb = pd.Series(np.arange(40, dtype="float64"), index=idx)
    monthly = {"primary_balance": pb}

    assert build_signal(FROZEN_SPEC, monthly) is None              # momentum: derived from returns
    fiscal = build_signal(HARD_PB_SPEC, monthly)                   # fiscal: pb.diff(lookback=6)
    pd.testing.assert_series_equal(fiscal, pb.diff(6))

    with pytest.raises(KeyError):                                  # missing required input -> loud
        build_signal(HARD_PB_SPEC, {})
    with pytest.raises(ValueError):                                # unknown kind -> loud
        build_signal({"kind": "totally_unknown"}, monthly)
