"""Phase 5 — causal online / adaptive combination weights (point-in-time, leakage-safe).

WHAT THIS IS (and is NOT):
    Infrastructure to combine several already-built CAUSAL return streams (e.g. the three booked candidate
    sleeves) into ONE book with weights that ADAPT over time to each stream's recent, strictly-past
    behaviour. It is NOT an alpha claim and NOT a forecast of profit. Whether online weights actually beat a
    flat equal-weight combination — on a deflated, leverage-invariant ruler — is an empirical question
    answered downstream by ``scripts/measure_online_weights.py`` (the honest, likely-marginal verdict),
    never asserted here. The project's honesty law stands: no demonstrated alpha beyond carry.

    SCOPE: this is online *combination weighting* of a FIXED set of streams. Online FEATURE selection
    (adaptively choosing which inputs/signals enter a model) is explicitly OUT OF SCOPE and DEFERRED.

CAUSALITY (non-negotiable — these get adversarial as-of tests):
    The weight ROW at time ``t`` uses ONLY returns with index STRICTLY < t. That is the tradable contract:
    weights[t] are decided from history available before t and can be applied to the streams' returns AT t
    without look-ahead. We deliberately use ``.shift(1)`` after a trailing/EW statistic so the current row's
    own return never enters its own weight. Appending later rows never changes an earlier weight row
    (as-of-invariance). No centered windows, no full-sample fit, no peeking at the row being weighted.

API (consumed by scripts/measure_online_weights.py):
    ewma_performance_weights(returns_panel, *, halflife=12, min_periods=12, floor=0.0) -> pd.DataFrame
    rolling_inverse_variance_weights(returns_panel, *, window=12, min_periods=12) -> pd.DataFrame

Both return a DataFrame aligned to ``returns_panel`` (same index & columns). Each defined row sums to 1
across the columns that have a usable weight, every weight is >= floor (>= 0), and rows without enough
strictly-past history fall back to EQUAL weights across the columns that are present (non-NaN) at that row.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

__all__ = ["ewma_performance_weights", "rolling_inverse_variance_weights"]


def _equal_weights_row(present_mask: np.ndarray) -> np.ndarray:
    """Equal weights across the columns flagged present (True); NaN where absent. Sums to 1 if any present.

    ``present_mask`` is a boolean row (one entry per column). Returns a float row with ``1/k`` on the ``k``
    present columns and NaN on the rest; an all-absent row is all-NaN (no weights definable)."""
    out = np.full(present_mask.shape, np.nan, dtype="float64")
    k = int(present_mask.sum())
    if k > 0:
        out[present_mask] = 1.0 / k
    return out


def _normalize_with_fallback(
    raw: np.ndarray,
    present_mask: np.ndarray,
    *,
    floor: float,
) -> np.ndarray:
    """Normalize a single raw weight row to sum 1 with a guaranteed EMITTED floor + equal-weight fallback.

    ``raw`` holds the (possibly NaN/negative) un-normalized scores for one row; ``present_mask`` marks which
    columns are tradable at that row (the underlying return is observed). Steps:
      1. consider only columns that are BOTH present AND have a finite raw score (the "scored" set, size k);
      2. drop the non-positive part of the scores (clip the raw score at 0) — a stream with a non-positive
         score gets only the floor, never negative weight;
      3. reserve ``floor`` for EACH scored column, then distribute the remaining mass ``1 - k*floor``
         proportionally to the clipped scores; this guarantees every EMITTED weight is exactly >= ``floor``
         and the row sums to 1 (the standard portfolio "minimum weight" construction);
      4. fall back to EQUAL weights across the PRESENT columns when there is no usable score, when the
         clipped scores sum to 0 (so proportional split is undefined), or when ``k*floor > 1`` (the floor is
         infeasible for that many columns).
    The result is NaN on absent columns, >= floor on the columns it weights, and sums to 1 whenever any
    column is present."""
    out = np.full(raw.shape, np.nan, dtype="float64")
    scored = present_mask & np.isfinite(raw)
    k = int(scored.sum())
    if k == 0:
        # No usable score anywhere -> equal weight across whatever is present (or all-NaN if nothing is).
        return _equal_weights_row(present_mask)

    # floor reserved for every scored column; if that is infeasible, equal-weight the present columns.
    reserved = k * floor
    if reserved > 1.0 + 1e-12:
        return _equal_weights_row(present_mask)

    pos_scores = np.where(scored, np.clip(raw, 0.0, None), 0.0)
    total = float(np.nansum(pos_scores))
    if not np.isfinite(total) or total <= 0.0:
        # Every score floored away to 0 (degenerate) -> equal weight across present columns.
        return _equal_weights_row(present_mask)

    free = 1.0 - reserved  # mass to distribute proportionally above the per-column floor
    out[scored] = floor + free * (pos_scores[scored] / total)
    return out


def ewma_performance_weights(
    returns_panel: pd.DataFrame,
    *,
    halflife: int = 12,
    min_periods: int = 12,
    floor: float = 0.0,
) -> pd.DataFrame:
    """Causal performance weights: each column weighted by its EW trailing risk-adjusted return.

    At every row ``t`` and for every column ``c`` we form a causal Sharpe-like score from returns with
    index STRICTLY < t::

        ew_mean[c]  = EWMA(returns[c], halflife)              # exponentially-weighted mean of past returns
        ew_var[c]   = EWMA((returns[c] - ew_mean[c])^2, halflife)  # EW variance
        score_t[c]  = ew_mean_{<t}[c] / sqrt(ew_var_{<t}[c])  # EW Sharpe proxy, computed then SHIFTED 1

    The ``.shift(1)`` is what makes the score at ``t`` depend only on returns strictly before ``t`` (so the
    weight is tradable AT ``t``). Each score row's negative part is dropped (a stream with negative trailing
    risk-adjusted return is never SHORTED via the weights), then ``floor`` is reserved for every present
    column and the remaining mass distributed proportionally to the scores, so every EMITTED weight is
    >= ``floor`` and the row sums to 1 across the columns present at ``t``. A column with consistently higher
    past risk-adjusted return earns a higher EW score and hence a larger weight. Rows with insufficient
    strictly-past history (any score not yet defined, i.e. before ``min_periods`` + the one-step lag) fall
    back to EQUAL weights across the columns present at that row.

    Notes
    -----
    * Negative EW Sharpe proxies contribute 0 above the floor: a column with a negative trailing
      risk-adjusted return gets only the ``floor`` (default 0 => no weight) — we never short a stream via the
      combination weights. If every scored column's score is non-positive at some row, that row falls back to
      equal weights (so it still sums to 1).
    * ``floor`` is a floor on the EMITTED (post-normalization) weight, not on the raw score, so the contract
      "every weight >= floor" holds exactly. If ``k * floor > 1`` for the ``k`` present columns the floor is
      infeasible and that row falls back to equal weights.
    * ``ew_var`` uses pandas' EW variance with ``bias=False`` (debiased); a column with zero EW variance
      (a flat segment) yields a non-finite score and is treated as unscored -> excluded from that row's
      normalization (or equal-weighted if it is the only one).

    Parameters
    ----------
    returns_panel : pd.DataFrame
        One column per stream/sleeve; rows are periods (e.g. months), index sorted ascending. NaN entries
        mark a stream that is not tradable that period (absent from that row's weighting).
    halflife : int
        EWMA halflife (in rows) for both the mean and the variance. Larger => slower adaptation.
    min_periods : int
        Minimum non-NaN observations a column needs before its EW statistic (and thus its score) is defined.
    floor : float
        Lower clip on each (pre-normalization) weight, >= 0. Guarantees every emitted weight is >= floor.

    Returns
    -------
    pd.DataFrame
        Same index & columns as ``returns_panel``. Each defined row sums to 1 across present columns; every
        weight is >= floor; insufficient-history rows are equal-weighted across present columns. Strictly
        causal: an interior row is unchanged when later rows are appended.
    """
    if floor < 0.0:
        raise ValueError(f"floor must be >= 0, got {floor}")
    if halflife <= 0:
        raise ValueError(f"halflife must be > 0, got {halflife}")

    panel = returns_panel.astype("float64")

    # EW mean and EW variance of PAST returns (computed on index <= t), then SHIFTED so row t uses < t only.
    ew_mean = panel.ewm(halflife=halflife, min_periods=min_periods).mean()
    ew_var = panel.ewm(halflife=halflife, min_periods=min_periods).var(bias=False)

    with np.errstate(divide="ignore", invalid="ignore"):
        ew_sharpe = ew_mean / np.sqrt(ew_var)
    # Strict-past lag: the score available AT t is built from returns strictly before t.
    score = ew_sharpe.shift(1)

    present = panel.notna().to_numpy()        # which streams are tradable at each row
    raw = score.to_numpy()

    n_rows = panel.shape[0]
    out = np.full(panel.shape, np.nan, dtype="float64")
    for i in range(n_rows):
        out[i, :] = _normalize_with_fallback(raw[i, :], present[i, :], floor=floor)

    return pd.DataFrame(out, index=panel.index, columns=panel.columns)


def rolling_inverse_variance_weights(
    returns_panel: pd.DataFrame,
    *,
    window: int = 12,
    min_periods: int = 12,
) -> pd.DataFrame:
    """Causal inverse-variance (risk-parity-ish) weights from a trailing window of PAST returns.

    At every row ``t`` and column ``c``::

        var_t[c]    = rolling_var(returns[c], window)_{<t}    # trailing-window variance, computed then SHIFTED 1
        weight_t[c] proportional to 1 / var_t[c]              # lower past variance => larger weight
        weight_t    normalized to sum 1 across present columns

    The ``.shift(1)`` makes ``var_t`` depend only on returns with index strictly < ``t`` (tradable at ``t``).
    Lower-variance streams receive proportionally more weight (risk-parity intuition: equalize each stream's
    risk contribution). Rows before enough trailing history (``min_periods``) — or where no column has a
    finite, positive trailing variance — fall back to EQUAL weights across the columns present at that row.

    Floor is implicitly 0 (inverse variance is strictly positive where defined). A column with zero trailing
    variance (a flat segment) yields a non-finite ``1/var`` and is treated as unscored at that row (excluded
    from the normalization, or equal-weighted if it is the only column).

    Parameters
    ----------
    returns_panel : pd.DataFrame
        One column per stream/sleeve; rows are periods, index sorted ascending. NaN marks an untradable
        stream for that period.
    window : int
        Trailing window length for the variance estimate.
    min_periods : int
        Minimum non-NaN observations in the window before the variance (and thus the weight) is defined.

    Returns
    -------
    pd.DataFrame
        Same index & columns as ``returns_panel``. Each defined row sums to 1 across present columns; every
        weight is >= 0; insufficient-history rows are equal-weighted across present columns. Strictly causal:
        an interior row is unchanged when later rows are appended.
    """
    if window <= 0:
        raise ValueError(f"window must be > 0, got {window}")

    panel = returns_panel.astype("float64")

    # Trailing-window variance (sample, ddof=1) computed on index <= t, then SHIFTED so row t uses < t only.
    var = panel.rolling(window=window, min_periods=min_periods).var(ddof=1)
    var_past = var.shift(1)

    with np.errstate(divide="ignore", invalid="ignore"):
        inv_var = 1.0 / var_past
    # A non-positive / non-finite trailing variance gives a non-finite inverse -> treated as unscored.
    inv_var = inv_var.where(np.isfinite(inv_var) & (var_past > 0.0))

    present = panel.notna().to_numpy()
    raw = inv_var.to_numpy()

    n_rows = panel.shape[0]
    out = np.full(panel.shape, np.nan, dtype="float64")
    for i in range(n_rows):
        # floor=0.0: inverse-variance scores are already positive where finite.
        out[i, :] = _normalize_with_fallback(raw[i, :], present[i, :], floor=0.0)

    return pd.DataFrame(out, index=panel.index, columns=panel.columns)
