"""Momentum sleeve (Phase 4.3) — CI-native. Causal construction; profitable on genuine momentum,
flat on noise; positions are point-in-time (no look-ahead)."""

from __future__ import annotations

import numpy as np
import pandas as pd

from arc.research.sleeve import (
    causal_position,
    momentum_sleeve_returns,
    sleeve_stats,
)


def _idx(n):
    return pd.date_range("2008-01-31", periods=n, freq="ME")


def test_position_is_point_in_time():
    """Appending future returns must not change any earlier position (expanding z-score is causal)."""
    rng = np.random.default_rng(0)
    r = pd.Series(rng.normal(size=120), index=_idx(120))
    from arc.research.sleeve import momentum_signal
    p_full = causal_position(momentum_signal(r))
    r_short = r.iloc[:90]
    p_short = causal_position(momentum_signal(r_short))
    common = p_short.dropna().index.intersection(p_full.dropna().index)
    assert len(common) > 30
    assert (p_short.reindex(common) - p_full.reindex(common)).abs().max() < 1e-12


def test_sleeve_profits_on_genuine_momentum():
    """An AR(1)-trending return series (positive autocorrelation) should give a profitable momentum
    sleeve; the position clips to [-1, 1]."""
    rng = np.random.default_rng(1)
    n = 240
    r = np.zeros(n)
    for t in range(1, n):
        r[t] = 0.5 * r[t - 1] + rng.normal(scale=0.02)  # persistent trend
    rs = pd.Series(r, index=_idx(n))
    sleeve = momentum_sleeve_returns(rs, lookback=3, cost_bps=2.0)
    st = sleeve_stats(sleeve, n_trials=1)
    assert st["sharpe_ann"] > 0.5
    pos = causal_position(rs.rolling(3).sum())
    assert pos.dropna().abs().max() <= 1.0 + 1e-9


def test_sleeve_flat_on_noise():
    rng = np.random.default_rng(2)
    rs = pd.Series(rng.normal(scale=0.02, size=240), index=_idx(240))
    sleeve = momentum_sleeve_returns(rs, lookback=3, cost_bps=2.0)
    st = sleeve_stats(sleeve, n_trials=10)
    assert abs(st["sharpe_ann"]) < 0.6  # no durable edge from white noise


def test_costs_reduce_sharpe():
    rng = np.random.default_rng(3)
    n = 240
    r = np.zeros(n)
    for t in range(1, n):
        r[t] = 0.4 * r[t - 1] + rng.normal(scale=0.02)
    rs = pd.Series(r, index=_idx(n))
    gross = sleeve_stats(momentum_sleeve_returns(rs, cost_bps=0.0), n_trials=1)["sharpe_ann"]
    net = sleeve_stats(momentum_sleeve_returns(rs, cost_bps=20.0), n_trials=1)["sharpe_ann"]
    assert gross > net


def test_vol_target_leverage_reported():
    rng = np.random.default_rng(4)
    rs = pd.Series(rng.normal(scale=0.01, size=120), index=_idx(120))
    st = sleeve_stats(momentum_sleeve_returns(rs), n_trials=1, vol_target_ann=0.10)
    assert "leverage_for_vol_target" in st and st["leverage_for_vol_target"] > 0
