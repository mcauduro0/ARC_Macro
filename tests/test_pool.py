"""Pooled forward holdout — CI-native invariant tests (pure pandas/numpy; no engine, no network).

The pool is a fourth booked candidate: an equal-weight panel of the three single sleeves, pre-committed
to a SHORTER forward sample (eval_at_n derived from the sleeves' correlation breadth). These tests prove
its scorer inherits the single verdict's discipline (one-shot, fail-closed, pre-committed sample size,
NaN-fatal, deterministic-on-read) and that the pooled stream uses common support only with no fitting.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from arc.autonomy.ledger import (
    HoldoutNotReadyError,
    MissingDeflationBasisError,
    PaperLedger,
)
from arc.autonomy.pool import (
    book_pool,
    issue_pool_token,
    pooled_forward_returns,
    pooled_verdict,
)
from arc.autonomy.spec import (
    FROZEN_SPEC,
    HARD_PB_SPEC,
    NOWCAST_SPEC,
    POOL_HASH,
    POOL_SPEC,
    strategy_hash,
)
from arc.eval.gate import sharpe_stats
from arc.eval.governance import HoldoutToken


def _frozen_frame(vals, start="2026-07-31"):
    idx = pd.date_range(start, periods=len(vals), freq="ME")
    return pd.DataFrame({"sleeve_return": list(vals), "held_position": [0.5] * len(vals)}, index=idx)


def _three(vals):
    return {"momentum_front": _frozen_frame(vals), "nowcast_long": _frozen_frame(vals),
            "fiscal_hard": _frozen_frame(vals)}


# ============================================================ registry / binding
def test_pool_spec_binds_to_member_hashes_and_forks_on_change():
    members = sorted(strategy_hash(s) for s in (FROZEN_SPEC, NOWCAST_SPEC, HARD_PB_SPEC))
    assert POOL_SPEC["members"] == members
    assert POOL_SPEC["kind"] == "pool" and POOL_SPEC["weights"] == "equal"
    assert strategy_hash(POOL_SPEC) == POOL_HASH
    tampered = dict(POOL_SPEC, members=members[:-1] + ["deadbeef00000000"])
    assert strategy_hash(tampered) != POOL_HASH  # editing membership forks the pool hash


# ============================================================ pooled stream construction
def test_pooled_returns_equal_weight_common_months_only():
    a = _frozen_frame([0.01, 0.02, 0.03], start="2026-07-31")  # Jul Aug Sep
    b = _frozen_frame([0.04, 0.05, 0.06], start="2026-08-31")  # Aug Sep Oct
    c = _frozen_frame([0.07, 0.08, 0.09], start="2026-08-31")  # Aug Sep Oct
    pooled = pooled_forward_returns({"a": a, "b": b, "c": c})
    assert len(pooled) == 2  # only Aug, Sep are common to all three
    assert abs(pooled.iloc[0] - (0.02 + 0.04 + 0.07) / 3) < 1e-12
    assert abs(pooled.iloc[1] - (0.03 + 0.05 + 0.08) / 3) < 1e-12


def test_pooled_returns_empty_if_any_member_empty():
    assert len(pooled_forward_returns({"a": _frozen_frame([0.01]), "b": pd.DataFrame()})) == 0


# ============================================================ verdict discipline
def test_pooled_verdict_requires_a_basis(tmp_path):
    led = PaperLedger(tmp_path)  # not booked
    with pytest.raises(MissingDeflationBasisError):
        pooled_verdict(led, _three([0.01] * 12), issue_pool_token(issued_by="t"), asof="2027-07-31")


def test_pooled_verdict_token_must_bind_to_pool_hash(tmp_path):
    led = PaperLedger(tmp_path)
    book_pool(led, n_trials=10, eval_at_n=12, dsr_min=0.05, forward_start="2026-06-30", issued_by="t")
    wrong = HoldoutToken(strategy_hash="deadbeefdeadbeef", issued_by="t")
    with pytest.raises(ValueError):
        pooled_verdict(led, _three([0.01] * 12), wrong, asof="2027-07-31")


def test_pooled_verdict_refuses_before_and_after_eval_at_n(tmp_path):
    led = PaperLedger(tmp_path)
    book_pool(led, n_trials=72, eval_at_n=12, dsr_min=0.50, forward_start="2026-06-30", issued_by="t")
    with pytest.raises(HoldoutNotReadyError):  # too few
        pooled_verdict(led, _three([0.01] * 8), issue_pool_token(issued_by="t"), asof="2027-03-31")
    with pytest.raises(HoldoutNotReadyError):  # overshoot
        pooled_verdict(led, _three([0.01] * 14), issue_pool_token(issued_by="t"), asof="2027-09-30")


def test_pooled_verdict_reproduces_gate_deflation_and_is_one_shot(tmp_path):
    led = PaperLedger(tmp_path)
    book_pool(led, n_trials=10, eval_at_n=12, dsr_min=0.05, forward_start="2026-06-30", issued_by="t",
              sr_std=0.07)
    rng = np.random.default_rng(5)
    vals = list(0.005 + rng.normal(scale=0.01, size=12))
    frames = _three(vals)  # identical members -> pooled == vals exactly
    v1 = pooled_verdict(led, frames, issue_pool_token(issued_by="t"), asof="2027-07-31")
    exp = sharpe_stats(np.array(vals), n_trials=10, sr_std=0.07)
    assert abs(v1["dsr"] - exp["dsr"]) < 1e-9
    assert v1["n"] == 12
    # one-shot deterministic-on-read: a second call returns the recorded verdict, no re-consume
    n_consumed = len(led.consumed_hashes())
    v2 = pooled_verdict(led, frames, issue_pool_token(issued_by="t"), asof="2027-08-31")
    assert v1 == v2 and len(led.consumed_hashes()) == n_consumed


def test_pooled_verdict_nan_fatal(tmp_path):
    led = PaperLedger(tmp_path)
    book_pool(led, n_trials=10, eval_at_n=12, dsr_min=0.05, forward_start="2026-06-30", issued_by="t",
              sr_std=0.07)
    v = pooled_verdict(led, _three([0.01] * 12), issue_pool_token(issued_by="t"), asof="2027-07-31")
    assert v["passed"] is False
    assert "NaN" in v["reason"] or "degenerate" in v["reason"]
