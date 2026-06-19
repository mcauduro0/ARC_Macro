"""Bounded, lag-aware forward-fill — fixes the unbounded ``ffill`` staleness leak (audit feat-3).

The monolith builds its feature matrix with ``feature_df.ffill()`` and no limit, so a value that
stopped updating is carried forward indefinitely and presented as if fresh: a quarterly (or
discontinued, or simply not-yet-published) series can masquerade as current for years. That is not
a PnL-accounting look-ahead (ffill only ever uses past values), but it injects stale, over-confident
inputs the model treats as live signal.

``bounded_ffill`` carries each value forward at most ``limit`` periods (rows), after which the cell
goes NaN — honest about staleness — and supports a per-column override so a quarterly series can be
allowed a longer reach than a monthly one (lag-aware). It never pulls a value backward, so it stays
point-in-time safe.
"""

from __future__ import annotations

from typing import Mapping, Optional, Union

import pandas as pd

_PandasObj = Union[pd.DataFrame, pd.Series]


def bounded_ffill(
    df: _PandasObj,
    limit: int = 12,
    per_column: Optional[Mapping[str, int]] = None,
) -> _PandasObj:
    """Forward-fill with a per-cell staleness cap of ``limit`` consecutive periods.

    Parameters
    ----------
    df : DataFrame or Series of monthly (row-indexed) features.
    limit : default max number of consecutive periods a value may be carried forward. A value
        <= 0 disables filling.
    per_column : optional {column: limit} overrides (lag-aware caps; e.g. quarterly debt/GDP gets
        a larger cap than a monthly policy rate). Columns not listed use ``limit``.
    """
    if isinstance(df, pd.Series):
        return df.ffill(limit=limit) if limit and limit > 0 else df

    out = df.copy()
    for col in out.columns:
        lim = per_column.get(col, limit) if per_column else limit
        if lim and lim > 0:
            out[col] = out[col].ffill(limit=lim)
    return out
