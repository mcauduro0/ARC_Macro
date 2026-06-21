"""Phase 5 — confidence-scaled and inverse-vol position sizing (causal, leakage-safe).

These functions RESIZE an existing causal position; they do NOT create signal. The input
``base_position`` / ``signal_position`` is assumed to already be a strictly point-in-time bet
produced upstream (sign = direction, magnitude = conviction). Here we only rescale that bet:

  * ``confidence_scaled_position`` shrinks/keeps the bet according to how confident we are at t,
    where "confidence" is mapped through its own *causal* (expanding-percentile) normalization so a
    given confidence reading is judged only against confidence readings observed at index <= t.
  * ``inverse_vol_position`` targets a constant annualized risk by scaling the bet inversely with a
    causal predicted volatility (``arc.intelligence.uncertainty.predictive_vol``).

Causality contract (these modules get adversarial as-of tests): every output value at time t is a
function of inputs with index <= t ONLY. Appending future rows never changes an earlier output.
No network, no engine import; pure pandas/numpy.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

__all__ = ["confidence_scaled_position", "inverse_vol_position"]


def _expanding_percentile_rank(x: pd.Series) -> pd.Series:
    """Causal in-[0,1] rank of each value against its own past (index <= t), inclusive.

    rank[t] = (# of observed x[i], i <= t, with x[i] <= x[t]) / (# of observed x[i], i <= t).

    Uses only data at index <= t (the current point is included in its own reference set, which is
    point-in-time legitimate: x[t] is known at t). NaNs are ignored in both numerator and
    denominator and propagate to NaN output. The first observed point ranks 1.0 (it is the max so
    far). This is monotone non-decreasing in x[t] holding the past fixed.
    """
    vals = x.to_numpy(dtype="float64", copy=True)
    out = np.full(vals.shape, np.nan, dtype="float64")
    seen: list[float] = []
    for i, v in enumerate(vals):
        if np.isnan(v):
            continue
        # count of past+current observed values that are <= v (current included)
        le = sum(1 for s in seen if s <= v) + 1  # +1 for v itself
        seen.append(v)
        out[i] = le / len(seen)
    return pd.Series(out, index=x.index)


def confidence_scaled_position(
    base_position: pd.Series,
    confidence: pd.Series,
    *,
    lo: float = 0.25,
    hi: float = 1.0,
) -> pd.Series:
    """Scale a causal ``base_position`` by a confidence-derived factor in ``[lo, hi]``.

    The raw ``confidence`` series is first mapped through a CAUSAL normalization — the expanding
    percentile rank (index <= t) — so that the scale at t reflects how the current confidence ranks
    against confidence observed up to t, not against the full sample. Then::

        scale[t] = lo + (hi - lo) * causal_rank(confidence)[t]      in [lo, hi]
        out[t]   = base_position[t] * scale[t]

    Because ``scale in [lo, hi]`` (with ``0 <= lo <= hi``), the output magnitude is bounded
    elementwise to ``[lo * |base|, hi * |base|]`` and the sign of ``base_position`` is preserved.
    Output is NaN wherever ``base_position`` or ``confidence`` is NaN.

    Parameters
    ----------
    base_position : pd.Series
        Existing causal position (sign = direction, magnitude = conviction). Not created here.
    confidence : pd.Series
        Causal confidence reading (e.g. ``interval_confidence``). Higher => larger scale.
    lo, hi : float
        Scale bounds. Require ``0 <= lo <= hi``.
    """
    if not (0.0 <= lo <= hi):
        raise ValueError(f"require 0 <= lo <= hi, got lo={lo}, hi={hi}")

    base_position, confidence = base_position.align(confidence, join="outer")
    rank = _expanding_percentile_rank(confidence)  # causal, in (0,1]
    scale = lo + (hi - lo) * rank
    out = base_position * scale
    # NaN wherever either input (hence rank) is undefined
    out = out.where(base_position.notna() & rank.notna())
    return out


def inverse_vol_position(
    signal_position: pd.Series,
    pred_vol: pd.Series,
    *,
    target_vol_ann: float = 0.10,
    clip: float = 3.0,
) -> pd.Series:
    """Risk-target a causal ``signal_position`` by scaling inversely with predicted volatility.

    ``pred_vol`` is a CAUSAL per-period (e.g. monthly) volatility forecast such as
    ``arc.intelligence.uncertainty.predictive_vol``. It is annualized with ``sqrt(12)`` and the
    position is scaled to hit ``target_vol_ann``::

        gross[t] = target_vol_ann / (pred_vol[t] * sqrt(12))
        scale[t] = clip(gross[t], 0, clip)          # bound leverage; never flips sign
        out[t]   = signal_position[t] * scale[t]

    Properties (all per-row / pre-clip on the gross factor):
      * doubling ``pred_vol`` halves the gross scale (inverse proportionality);
      * the scale is non-negative and clipped to ``[0, clip]`` so |out| <= clip * |signal|;
      * the sign of ``signal_position`` is preserved (scale >= 0).
    Output is NaN wherever ``signal_position`` or ``pred_vol`` is NaN, or ``pred_vol <= 0``.

    Parameters
    ----------
    signal_position : pd.Series
        Existing causal position. Not created here.
    pred_vol : pd.Series
        Causal per-period predicted volatility (same frequency as the position, e.g. monthly).
    target_vol_ann : float
        Target annualized volatility (e.g. 0.10 == 10%).
    clip : float
        Maximum absolute scale (leverage cap). Require ``clip >= 0``.
    """
    if clip < 0:
        raise ValueError(f"clip must be >= 0, got {clip}")

    signal_position, pred_vol = signal_position.align(pred_vol, join="outer")
    pv = pred_vol.where(pred_vol > 0)  # non-positive vol -> undefined (NaN)
    pred_vol_ann = pv * np.sqrt(12.0)
    gross = target_vol_ann / pred_vol_ann          # inverse-proportional, >= 0
    scale = gross.clip(lower=0.0, upper=clip)       # bound; sign-preserving
    out = signal_position * scale
    out = out.where(signal_position.notna() & scale.notna())
    return out
