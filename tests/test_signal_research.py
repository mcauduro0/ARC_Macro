"""Honest signal evaluation (Phase 4) — CI-native (numpy/pandas + arc.eval only).

A genuine, stationary, orthogonal-to-carry signal passes; pure noise fails; carry-in-disguise fails
the carry-neutral bar; a first-half-only signal fails the half-sample decay bar.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from arc.research.signals import SignalThresholds, evaluate_signal, rank_signals


def _idx(n):
    return pd.date_range("2008-01-31", periods=n, freq="ME")


def test_genuine_stationary_signal_passes():
    rng = np.random.default_rng(0)
    n = 180
    idx = _idx(n)
    sig = pd.Series(rng.normal(size=n), index=idx)
    carry = pd.Series(rng.normal(size=n), index=idx)
    fwd = pd.Series(0.6 * sig.values + 0.3 * carry.values + rng.normal(scale=0.7, size=n), index=idx)
    res = evaluate_signal(sig, fwd, carry)
    assert res["passed"], res["reasons"]
    assert res["carry_neutral_ic"] > 0.05
    assert res["refit_oos_mean"] > 0.03


def test_pure_noise_fails():
    rng = np.random.default_rng(1)
    n = 180
    idx = _idx(n)
    sig = pd.Series(rng.normal(size=n), index=idx)
    carry = pd.Series(rng.normal(size=n), index=idx)
    fwd = pd.Series(rng.normal(size=n), index=idx)
    res = evaluate_signal(sig, fwd, carry)
    assert not res["passed"]


def test_carry_in_disguise_fails_carry_neutral():
    rng = np.random.default_rng(2)
    n = 180
    idx = _idx(n)
    carry = pd.Series(rng.normal(size=n), index=idx)
    fwd = pd.Series(carry.values + rng.normal(scale=0.05, size=n), index=idx)
    sig = carry.copy()  # the "signal" is just carry
    res = evaluate_signal(sig, fwd, carry)
    assert not res["passed"]
    assert any("carry-neutral" in r for r in res["reasons"])


def test_first_half_only_signal_fails_decay():
    rng = np.random.default_rng(3)
    n = 180
    idx = _idx(n)
    sig = pd.Series(rng.normal(size=n), index=idx)
    carry = pd.Series(rng.normal(size=n), index=idx)
    fwd = pd.Series(rng.normal(scale=0.6, size=n), index=idx)
    fwd.iloc[: n // 2] += 1.5 * sig.iloc[: n // 2]  # predictive only early
    res = evaluate_signal(sig, fwd, carry)
    assert not res["passed"]
    assert any("decay" in r or "2nd-half" in r for r in res["reasons"])


def test_rank_signals_counts_and_survivors():
    rng = np.random.default_rng(4)
    n = 160
    idx = _idx(n)
    good = pd.Series(rng.normal(size=n), index=idx)
    noise = pd.Series(rng.normal(size=n), index=idx)
    carry = pd.Series(rng.normal(size=n), index=idx)
    fwd = pd.Series(0.7 * good.values + rng.normal(scale=0.6, size=n), index=idx)
    feat_df = pd.DataFrame({"good": good, "noise": noise}, index=idx)
    out = rank_signals(
        {"inst": ["good", "noise", "absent"]},
        feat_df,
        {"inst": fwd},
        {"inst": carry},
    )
    assert out["n_hypotheses"] == 2  # good + noise (absent has 0 obs)
    feats = {r["feature"] for r in out["survivors"]}
    assert "good" in feats and "noise" not in feats
