"""Strictly point-in-time mixed-frequency activity nowcast (Phase 4.4 — close the IBC-Br blindspot).

IBC-Br (the monthly activity proxy) publishes with a ~45-day lag, so at decision month E the engine's
activity read is 1-2 months stale. A nowcast estimates current-month activity by combining the laggy
official series with TIMELIER monthly series (Brazil equity, commodities, terms of trade) that are
already known at E — filling the "ragged edge" the way a Stock-Watson / Giannone-Reichlin-Small nowcast
does, but kept deliberately simple and transparent.

Honest-measurement discipline (the whole reason this project exists): the factor at month t uses ONLY
data with index <= t. Standardization is expanding (no full-sample mean/std), the factor loadings are
re-estimated each month on data <= t, and the ragged edge is projected forward with those loadings.
The construction is therefore AS-OF-INVARIANT BY CONSTRUCTION: ``pit_dynamic_factor(panel)[E] ==
pit_dynamic_factor(panel.loc[:E])[E]`` — proven in ``tests/test_nowcast.py`` (the crown-jewel leak gate).
The PCA sign indeterminacy across refits is removed by orienting the factor to a reference series.
"""

from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd


def _factor_at(sub: pd.DataFrame, min_obs: int, ref: Optional[str]) -> float:
    """Nowcast value for the LAST row of ``sub`` using only the rows of ``sub`` (data <= t).

    Expanding-standardize every column with up-to-t mean/std; estimate the first principal component on
    the balanced (no-NaN) sub-panel; orient its sign by the reference column; project the ragged last
    row onto the loadings using only the series available at t."""
    mu = sub.mean()
    sd = sub.std(ddof=0).replace(0.0, np.nan)
    z = (sub - mu) / sd
    z = z.dropna(axis=1, how="all")
    if z.shape[1] == 0:
        return float("nan")

    last = z.iloc[-1]
    avail = last.notna()
    if not avail.any():
        return float("nan")

    bal = z.dropna(axis=0, how="any")
    cols = list(z.columns)
    # Fallback when the balanced panel is too thin or single-column: equal-weight the available z's.
    if len(bal) < min_obs or bal.shape[1] < 2:
        return float(last[avail].mean())

    C = np.corrcoef(bal.values, rowvar=False)
    if not np.all(np.isfinite(C)):
        return float(last[avail].mean())
    _, vecs = np.linalg.eigh(C)
    load = vecs[:, -1]  # eigenvector of the largest eigenvalue

    # Orient the sign deterministically (PCA is sign-ambiguous; an un-oriented refit flips the series).
    if ref is not None and ref in cols and load[cols.index(ref)] != 0:
        if load[cols.index(ref)] < 0:
            load = -load
    elif load.sum() < 0:
        load = -load

    lv = pd.Series(load, index=cols)
    a = lv[avail.values if hasattr(avail, "values") else avail]
    x = last[avail]
    denom = float(a.abs().sum()) or 1.0
    return float((a * x).sum() / denom)


def pit_dynamic_factor(
    panel: pd.DataFrame,
    *,
    ref_col: Optional[str] = None,
    min_obs: int = 24,
) -> pd.Series:
    """A coincident activity factor available at each month-end, ragged-edge aware and strictly causal.

    ``panel`` is a monthly DataFrame (columns = standardizable activity indicators; laggy series carry
    NaN at the ragged edge). The value at index ``t`` is computed from ``panel.loc[:t]`` ONLY, so the
    series is as-of-invariant. ``ref_col`` (default the first column) fixes the factor's sign so a higher
    value means "more activity"."""
    panel = panel.sort_index()
    ref = ref_col if ref_col is not None else (panel.columns[0] if len(panel.columns) else None)
    out = pd.Series(index=panel.index, dtype="float64")
    for i in range(len(panel.index)):
        out.iloc[i] = _factor_at(panel.iloc[: i + 1], min_obs, ref)
    return out


def nowcast_surprise(factor: pd.Series, *, min_periods: int = 12) -> pd.Series:
    """Standardized surprise of the nowcast vs its own expanding mean/std (causal). Positive => activity
    running above its own recent norm."""
    f = factor.astype("float64")
    mu = f.expanding(min_periods=min_periods).mean()
    sd = f.expanding(min_periods=min_periods).std().replace(0.0, np.nan)
    return (f - mu) / sd


def activity_nowcast(
    monthly: dict,
    series_keys: list[str],
    *,
    ref_col: str = "ibc_br",
    min_obs: int = 24,
) -> pd.Series:
    """Convenience: build the panel from the engine's ``monthly`` dict (a {name: Series} map) over the
    given keys and return the PIT nowcast factor. Missing keys are skipped (logged by the caller)."""
    cols = {k: monthly[k] for k in series_keys if k in monthly and monthly[k] is not None
            and len(monthly[k].dropna()) > 0}
    if not cols:
        return pd.Series(dtype="float64")
    panel = pd.DataFrame(cols).sort_index()
    ref = ref_col if ref_col in panel.columns else panel.columns[0]
    return pit_dynamic_factor(panel, ref_col=ref, min_obs=min_obs)


__all__ = ["pit_dynamic_factor", "nowcast_surprise", "activity_nowcast"]
