"""Phase 5 — predictive uncertainty / credible intervals (point-in-time, leakage-safe).

WHAT THIS IS (and is NOT):
    These functions quantify *uncertainty around a prediction* — how wide a credible band the recent,
    strictly-past errors imply. They are NOT forecasts of profit, edge, or direction. A narrow interval
    means "the model has historically been precise here", never "this trade will make money". The project's
    honesty law stands: there is no demonstrated alpha beyond carry; this is measured machinery whose value
    is decided empirically downstream, never asserted here.

CAUSALITY (non-negotiable — these get adversarial as-of tests):
    Every value at time ``t`` uses ONLY data with index <= t (and for calibration, STRICTLY < t). Appending
    later observations must never change an earlier output. We use trailing/expanding windows with
    ``min_periods`` and split-conformal calibration on strictly-past residuals only. No centered windows, no
    full-sample fit, no peeking at the row being predicted.

API (consumed verbatim by sizing.py / meta_labeling.py and the measurement script):
    predictive_vol(returns, *, window=12, min_periods=12) -> pd.Series
    conformal_intervals(pred, realized, *, alpha=0.1, min_train=24) -> pd.DataFrame[point,lo,hi,width]
    interval_confidence(width, *, min_periods=24) -> pd.Series
"""

from __future__ import annotations

import numpy as np
import pandas as pd

__all__ = ["predictive_vol", "conformal_intervals", "interval_confidence"]


def predictive_vol(
    returns: pd.Series,
    *,
    window: int = 12,
    min_periods: int = 12,
) -> pd.Series:
    """Causal trailing volatility estimate.

    The value at ``t`` is the trailing rolling standard deviation of ``returns`` over the last ``window``
    observations with index <= t (sample std, ``ddof=1``). It is a *predictive* (one-step-ahead) volatility
    proxy in the sense that, used at the close of ``t``, it conditions only on data knowable at ``t`` — so it
    can size the position taken into ``t+1`` without leakage.

    Parameters
    ----------
    returns : pd.Series
        Periodic returns (any frequency); index assumed sorted ascending.
    window : int
        Trailing window length.
    min_periods : int
        Minimum non-NaN observations required; rows with fewer trailing points are NaN.

    Returns
    -------
    pd.Series
        Trailing std, same index as ``returns``. Strictly causal: value at interior ``t`` is unchanged by
        appending later returns. Non-NaN values are >= 0 (and > 0 unless the window is exactly constant).
    """
    r = pd.Series(returns, dtype="float64")
    vol = r.rolling(window=window, min_periods=min_periods).std(ddof=1)
    return vol.rename("pred_vol")


def conformal_intervals(
    pred: pd.Series,
    realized: pd.Series,
    *,
    alpha: float = 0.1,
    min_train: int = 24,
) -> pd.DataFrame:
    """Split-conformal credible intervals, computed CAUSALLY (strictly-past calibration).

    Design
    ------
    Classic split-conformal prediction with an *online, expanding calibration set* so that the band at ``t``
    only ever uses residuals observed strictly before ``t``:

      1. Align ``pred`` and ``realized`` on a common index; let the absolute residual (nonconformity score)
         at a past time ``s`` be ``e[s] = |realized[s] - pred[s]|`` (only defined where both are present).
      2. For each prediction time ``t``, the calibration set is ``{e[s] : s < t}`` — residuals from rows
         STRICTLY before ``t``. If it holds at least ``min_train`` scores, the conformal half-width ``q[t]``
         is the conformal ``(1 - alpha)`` quantile of that calibration set; otherwise ``q[t]`` is NaN.
      3. The interval is ``pred[t] ± q[t]`` (symmetric, since the score is the absolute error).

    Conformal quantile
    ------------------
    With ``n`` strictly-past scores we take the ``ceil((n + 1) * (1 - alpha)) / n`` empirical quantile,
    clipped to 1.0 (the finite-sample-valid split-conformal level). This is the standard +1 correction that
    gives marginal coverage >= ``1 - alpha`` under exchangeability; as ``n`` grows it -> the plain
    ``(1 - alpha)`` quantile of ``|realized - pred|`` required by the API contract.

    Causality guarantee
    -------------------
    ``q[t]`` depends only on residuals at indices ``< t``; ``pred[t]`` is the current prediction (index == t).
    Nothing at index ``>= t`` (other than the row's own ``pred``) enters the band. Hence an interior row's
    interval is identical whether or not later data exists — the as-of-invariance the tests assert.

    Parameters
    ----------
    pred : pd.Series
        Point predictions.
    realized : pd.Series
        Realized outcomes on the same (or overlapping) index as ``pred``.
    alpha : float
        Miscoverage level; target coverage is ``1 - alpha`` (e.g. 0.1 -> ~90% bands). Must be in (0, 1).
    min_train : int
        Minimum number of strictly-past residuals required before a finite band is produced.

    Returns
    -------
    pd.DataFrame
        Columns ``["point", "lo", "hi", "width"]`` indexed by ``pred``'s index. ``point`` is ``pred``;
        ``lo``/``hi``/``width`` are NaN until ``min_train`` strictly-past residuals exist (and wherever
        ``pred`` itself is NaN). ``width == hi - lo == 2 * q``.
    """
    if not (0.0 < alpha < 1.0):
        raise ValueError(f"alpha must be in (0, 1), got {alpha!r}")

    p = pd.Series(pred, dtype="float64")
    out_index = p.index

    # Align realized onto the prediction index without disturbing pred's ordering/coverage.
    y = pd.Series(realized, dtype="float64").reindex(out_index)

    point = p.to_numpy()
    realized_arr = y.to_numpy()
    # Nonconformity score where BOTH pred and realized are present; NaN elsewhere (never calibrated on).
    resid = np.abs(realized_arr - point)

    n = len(out_index)
    q = np.full(n, np.nan, dtype="float64")

    # Online expanding calibration: accumulate only residuals from rows strictly before t.
    # We iterate in index order; `past_scores` holds e[s] for s < t at the moment we set q[t].
    past_scores: list[float] = []
    for i in range(n):
        # q[t] uses ONLY scores added for indices strictly before i.
        m = len(past_scores)
        if m >= min_train and np.isfinite(point[i]):
            scores = np.asarray(past_scores, dtype="float64")
            # Finite-sample split-conformal level with the +1 correction, clipped to a valid prob.
            level = np.ceil((m + 1) * (1.0 - alpha)) / m
            level = min(level, 1.0)
            q[i] = float(np.quantile(scores, level, method="higher"))
        # Only AFTER setting q[i] do we admit residual at index i into the calibration set for future rows,
        # preserving the strict s < t rule. Skip NaN residuals (missing pred or realized).
        if np.isfinite(resid[i]):
            past_scores.append(float(resid[i]))

    lo = point - q
    hi = point + q
    width = hi - lo  # == 2*q (NaN where q is NaN)

    return pd.DataFrame(
        {"point": point, "lo": lo, "hi": hi, "width": width},
        index=out_index,
    )


def interval_confidence(
    width: pd.Series,
    *,
    min_periods: int = 24,
) -> pd.Series:
    """Map interval width -> a confidence score in (0, 1], causally.

    Intuition: a band that is *narrower than the model has typically produced in the past* signals higher
    confidence; a wider-than-usual band signals lower confidence. We benchmark each width against the
    EXPANDING MEDIAN of past widths (index <= t only):

        confidence[t] = clip( expanding_median(width)[<= t] / width[t], 0, 1 )

    - When ``width[t]`` equals its trailing-typical level, confidence ~ 0.5..1 (median/width ~ 1 -> 1).
    - When ``width[t]`` is much larger than typical, the ratio -> 0 (low confidence).
    - Monotone: on a series of decreasing widths, confidence is non-decreasing.
    - The expanding median uses only widths at index <= t, so the score is strictly causal.

    Bounds: the result is clipped to ``[0, 1]``; to keep it in the *open-above-zero* range advertised by the
    API ``(0, 1]`` we floor strictly-positive-eligible rows at a tiny epsilon (a zero-confidence row would
    otherwise zero out any position it scales, which we treat as "minimal", not "exactly none"). Rows with
    NaN width, non-positive width, or fewer than ``min_periods`` observations are NaN.

    Parameters
    ----------
    width : pd.Series
        Interval widths (e.g. the ``width`` column of :func:`conformal_intervals`), >= 0.
    min_periods : int
        Minimum number of observations (index <= t) before a confidence is produced.

    Returns
    -------
    pd.Series
        Confidence in (0, 1], same index as ``width``. NaN before ``min_periods`` or where width is
        NaN/<= 0. Strictly causal and monotone-decreasing in current width.
    """
    w = pd.Series(width, dtype="float64")
    # Expanding median of widths seen so far (index <= t); causal by construction.
    typ = w.expanding(min_periods=min_periods).median()

    with np.errstate(divide="ignore", invalid="ignore"):
        ratio = typ / w

    conf = ratio.clip(lower=0.0, upper=1.0)
    # Invalid where width is NaN or non-positive (ratio is inf/NaN there), or before min_periods.
    invalid = w.isna() | (w <= 0.0) | typ.isna() | ~np.isfinite(ratio.to_numpy())
    conf = conf.mask(invalid)
    # Keep strictly within (0, 1]: nudge exact zeros up to a tiny epsilon on otherwise-valid rows.
    eps = np.finfo("float64").tiny
    conf = conf.where(invalid | (conf > 0.0), other=eps)
    return conf.rename("confidence")
