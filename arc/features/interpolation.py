"""Causal annual->monthly resampling (strangler-fig, fixes the interpolation look-ahead).

The legacy engine upsampled sparse annual series (ppp_factor, gdppc_ratio, ca_pct_gdp,
trade_openness) to monthly with ``resample('D').interpolate('linear').resample('ME').last()``.
Linear interpolation between two annual anchors blends toward the **next** (future) anchor, so a
month in mid-year already encodes the year-end value that had not been released yet — a real
look-ahead (adversarially confirmed, 2026-06 leak hunt). It biases the early sample most (its
"future" anchors are most of the series), feeding the H1>>H2 IC inflation.

The causal transform holds the **last known** anchor (a step function): at month M you only ever see
the most recent annual value released on or before M. This is invariant to future data — appending a
later anchor cannot change any earlier month — which the linear version is not.
"""

from __future__ import annotations

import pandas as pd


def causal_annual_to_monthly(series: pd.Series) -> pd.Series:
    """Upsample a sparse (annual) series to a month-end grid by holding the last known value.

    Point-in-time: value[M] = most recent anchor with date <= M. Does NOT interpolate toward future
    anchors. Returns a month-end-indexed Series spanning the anchors (NaN before the first anchor is
    dropped). Use this instead of linear interpolation for annual fundamentals.
    """
    if series is None or len(series) == 0:
        return series
    s = series.sort_index()
    monthly = s.resample("ME").last()  # anchors land on their month-end; gaps are NaN
    return monthly.ffill().dropna()


def linear_annual_to_monthly(series: pd.Series) -> pd.Series:
    """Legacy (look-ahead) upsampling kept ONLY for measurement/comparison: linear interpolation
    between annual anchors uses the next (future) anchor. Do not use in the causal path."""
    if series is None or len(series) == 0:
        return series
    daily = series.sort_index().resample("D").interpolate(method="linear")
    return daily.resample("ME").last().dropna()
