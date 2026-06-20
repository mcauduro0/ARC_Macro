"""Operationalize a verified signal as a standalone, causal, costed trading sleeve (Phase 4.3).

A single verified edge is best run as its own rules-based sleeve and combined into the book at the
portfolio level — NOT fed into the overfit ensemble (feature selection would dilute/contaminate the
very thing we verified). This builds the sleeve fully causally and reports its gated, deflated,
net-of-cost performance.

position[t] = clip(z, -clip_z, clip_z)/clip_z in [-1, 1], where z is the EXPANDING (point-in-time)
z-score of the trailing-``lookback`` return momentum known at t. The sleeve earns r[t+1] on that
position, minus turnover * cost. No look-ahead: every input at t uses only data up to t.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from arc.eval.gate import sharpe_stats


def momentum_signal(returns: pd.Series, lookback: int = 3) -> pd.Series:
    """Trailing ``lookback``-month return momentum, known at t (sum of r[t-lookback+1..t])."""
    return returns.rolling(lookback).sum()


def causal_position(signal: pd.Series, z_window: int = 12, clip_z: float = 2.0) -> pd.Series:
    """Point-in-time position in [-1, 1]: expanding z-score of the signal, clipped and normalized.
    Uses only data up to each date (expanding mean/std with min_periods=z_window)."""
    mu = signal.expanding(min_periods=z_window).mean()
    sd = signal.expanding(min_periods=z_window).std()
    z = (signal - mu) / sd.replace(0.0, np.nan)
    return (z.clip(-clip_z, clip_z) / clip_z)


def signal_sleeve_returns(
    signal: pd.Series,
    returns: pd.Series,
    *,
    z_window: int = 12,
    clip_z: float = 2.0,
    cost_bps: float = 2.0,
) -> pd.Series:
    """Net monthly return stream of a single-instrument sleeve driven by ANY point-in-time signal.

    The signal is whatever oriented, decision-time series drives the position (price momentum, an
    activity nowcast, a real-rate gap, ...). It is turned into a position via the same causal expanding
    z-score, so a higher signal => a larger long position. ``sleeve[t] = position[t-1] * return[t] -
    |position[t-1] - position[t-2]| * cost``. The signal MUST already be point-in-time (value at t uses
    only data <= t); this function adds no look-ahead."""
    r = pd.Series(returns).dropna()
    sig = pd.Series(signal).reindex(r.index)
    pos = causal_position(sig, z_window=z_window, clip_z=clip_z)
    held = pos.shift(1)                      # decided last month, earns this month's return
    gross = held * r
    turnover = held.diff().abs()
    cost = turnover * (cost_bps / 10000.0)
    return (gross - cost).dropna()


def momentum_sleeve_returns(
    returns: pd.Series,
    *,
    lookback: int = 3,
    z_window: int = 12,
    clip_z: float = 2.0,
    cost_bps: float = 2.0,
) -> pd.Series:
    """Net monthly return stream of a single-instrument momentum sleeve (causal, costed).

    sleeve[t] = position[t-1] * return[t]  -  |position[t-1] - position[t-2]| * cost.
    A special case of ``signal_sleeve_returns`` with signal = trailing return momentum."""
    r = pd.Series(returns).dropna()
    return signal_sleeve_returns(momentum_signal(r, lookback), r,
                                 z_window=z_window, clip_z=clip_z, cost_bps=cost_bps)


def sleeve_stats(returns: pd.Series, n_trials: int = 1, vol_target_ann: float | None = None) -> dict:
    """Gated, deflated stats for a sleeve return stream. If ``vol_target_ann`` is given, also report
    the (leverage-invariant) leverage needed to hit it — Sharpe/DSR are unchanged by leverage."""
    r = pd.Series(returns).dropna()
    st = sharpe_stats(r.values, n_trials=n_trials)
    eq = (1.0 + r).cumprod()
    dd = (eq / eq.cummax() - 1.0).min()
    out = {
        "n": int(len(r)),
        "ann_ret": float(r.mean() * 12),
        "ann_vol": float(r.std(ddof=1) * np.sqrt(12)),
        "sharpe_ann": st["sr_annual"],
        "psr_vs_0": st["psr_vs_0"],
        "dsr": st["dsr"],
        "max_drawdown": float(dd),
        "hit_rate": float((r > 0).mean()),
    }
    if vol_target_ann and out["ann_vol"] > 0:
        out["leverage_for_vol_target"] = float(vol_target_ann / out["ann_vol"])
    return out
