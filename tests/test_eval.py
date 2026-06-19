"""Honest-measurement library tests (arc.eval)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from arc.eval import (
    GovernanceLedger,
    HoldoutConsumedError,
    HoldoutToken,
    PurgedKFold,
    combinatorial_purged_splits,
    deflated_sharpe_ratio,
    expected_max_sharpe,
    forward_returns,
    information_coefficient,
    newey_west_tstat,
    probabilistic_sharpe_ratio,
    probability_of_backtest_overfitting,
    triple_barrier_labels,
)
from arc.eval.cv import t1_from_horizon


# ---------------- labels ----------------
def test_forward_returns_alignment_and_tail_nan():
    r = pd.Series([0.0, 0.1, 0.2, 0.3, 0.0])
    f1 = forward_returns(r, 1)
    assert f1.iloc[0] == pytest.approx(0.1)  # = r[t+1]
    assert f1.iloc[3] == pytest.approx(0.0)
    assert np.isnan(f1.iloc[-1])  # last horizon points unknown
    f2 = forward_returns(r, 2)
    assert f2.iloc[0] == pytest.approx(1.1 * 1.2 - 1)  # (1+r1)(1+r2)-1
    assert np.isnan(f2.iloc[-1]) and np.isnan(f2.iloc[-2])


def test_triple_barrier_hits_upper_lower_vertical():
    idx = pd.date_range("2020-01-01", periods=15, freq="D")
    target = pd.Series(0.05, index=idx)
    up = pd.Series(100 * (1.02) ** np.arange(15), index=idx)     # rises ~2%/day -> upper
    dn = pd.Series(100 * (0.98) ** np.arange(15), index=idx)     # falls ~2%/day -> lower
    flat = pd.Series(100 + 0.0 * np.arange(15), index=idx)       # flat -> vertical
    assert triple_barrier_labels(up, [idx[0]], pt=1, sl=1, max_holding=10, target=target)["label"].iloc[0] == 1
    assert triple_barrier_labels(dn, [idx[0]], pt=1, sl=1, max_holding=10, target=target)["label"].iloc[0] == -1
    assert triple_barrier_labels(flat, [idx[0]], pt=1, sl=1, max_holding=5, target=target)["label"].iloc[0] == 0


# ---------------- cv ----------------
def test_purged_kfold_no_leakage_with_horizon():
    n = 24
    X = pd.DataFrame({"x": np.arange(n)}, index=pd.RangeIndex(n))
    t1 = t1_from_horizon(X.index, horizon=3)
    cv = PurgedKFold(n_splits=4, t1=t1, embargo=0.0)
    start = np.asarray(X.index)
    end = np.asarray(t1.values)
    for train, test in cv.split(X):
        assert set(train).isdisjoint(set(test))
        ts0, ts1 = start[test].min(), end[test].max()
        # no train sample's label interval overlaps the test envelope
        for j in train:
            assert not (start[j] <= ts1 and end[j] >= ts0)


def test_purged_kfold_embargo_drops_following_samples():
    n = 20
    X = pd.DataFrame({"x": np.arange(n)}, index=pd.RangeIndex(n))
    folds = list(PurgedKFold(n_splits=4, embargo=0.1).split(X))  # embargo_n = 2
    # the non-last fold must purge the 2 samples immediately after its test block
    train, test = folds[0]
    after = set(range(test.max() + 1, test.max() + 3))
    assert after.isdisjoint(set(train))


def test_combinatorial_purged_splits_path_count():
    splits = combinatorial_purged_splits(n_samples=60, n_groups=6, n_test_groups=2)
    assert len(splits) == 15  # C(6,2)
    for train, test in splits:
        assert set(train).isdisjoint(set(test))
        assert len(test) > 0


# ---------------- metrics ----------------
def test_psr_monotonic_and_centered():
    assert probabilistic_sharpe_ratio(0.0, 120) == pytest.approx(0.5, abs=1e-6)
    assert probabilistic_sharpe_ratio(0.2, 120) > probabilistic_sharpe_ratio(0.1, 120)


def test_expected_max_sharpe_grows_with_trials():
    assert expected_max_sharpe(1, 1.0) == 0.0
    assert expected_max_sharpe(50, 1.0) > expected_max_sharpe(5, 1.0) > 0


def test_deflated_sharpe_penalizes_more_trials():
    one = deflated_sharpe_ratio(0.15, 120, n_trials=1, sr_std=0.5)
    many = deflated_sharpe_ratio(0.15, 120, n_trials=50, sr_std=0.5)
    assert many < one  # more trials => harder benchmark => lower DSR


def test_newey_west_tstat_detects_mean_and_ignores_noise():
    rng = np.random.default_rng(0)
    signal = 0.02 + 0.01 * rng.standard_normal(200)
    noise = rng.standard_normal(200)
    assert newey_west_tstat(signal) > 3
    assert abs(newey_west_tstat(noise)) < 2.5


def test_information_coefficient_signs():
    real = pd.Series(np.arange(50, dtype=float))
    assert information_coefficient(real, real) == pytest.approx(1.0)
    assert information_coefficient(-real, real) == pytest.approx(-1.0)


def test_pbo_low_for_dominant_high_for_noise():
    rng = np.random.default_rng(1)
    T, N = 120, 10
    noise = rng.standard_normal((T, N))
    pbo_noise = probability_of_backtest_overfitting(noise, n_splits=10)
    assert 0.2 < pbo_noise < 0.8  # random configs -> ~coin flip
    dominant = rng.standard_normal((T, N)) * 0.1
    dominant[:, 0] += 1.0  # config 0 consistently best IS and OOS
    assert probability_of_backtest_overfitting(dominant, n_splits=10) < 0.1


# ---------------- governance ----------------
def test_governance_ledger_counts_and_stats():
    led = GovernanceLedger()
    led.record_trial("h1", sharpe=1.0, label="a")
    led.record_trial("h2", sharpe=2.0, label="b")
    led.record_trial("h1", sharpe=0.5, label="a2")  # same config retried
    assert led.n_trials() == 3
    assert led.n_unique_configs() == 2
    assert led.sharpe_std() > 0
    assert led.best().config_hash == "h2"


def test_holdout_token_single_use_and_bound():
    tok = HoldoutToken(strategy_hash="abc", issued_by="human")
    assert tok.consume("abc") is True
    with pytest.raises(HoldoutConsumedError):
        tok.consume("abc")  # second use forbidden
    fresh = HoldoutToken(strategy_hash="abc", issued_by="human")
    with pytest.raises(ValueError):
        fresh.consume("different")  # bound to the frozen spec hash
