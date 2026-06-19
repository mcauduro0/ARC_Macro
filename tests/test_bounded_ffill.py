"""Bounded, lag-aware forward-fill (audit feat-3)."""

from __future__ import annotations

import numpy as np
import pandas as pd

from arc.features import bounded_ffill


def _frame():
    idx = pd.date_range("2020-01-31", periods=10, freq="ME")
    # value at month 0, then a long gap
    s = pd.Series([1.0] + [np.nan] * 9, index=idx)
    return pd.DataFrame({"x": s})


def test_caps_staleness():
    df = _frame()
    out = bounded_ffill(df, limit=3)
    # carried for 3 months after the observation, NaN thereafter
    assert out["x"].iloc[0] == 1.0
    assert (out["x"].iloc[1:4] == 1.0).all()
    assert out["x"].iloc[4:].isna().all()


def test_unbounded_would_fill_all():
    df = _frame()
    # legacy behavior, for contrast
    assert df["x"].ffill().notna().all()
    assert bounded_ffill(df, limit=3)["x"].isna().any()


def test_per_column_override():
    idx = pd.date_range("2020-01-31", periods=8, freq="ME")
    df = pd.DataFrame({
        "monthly": pd.Series([1.0] + [np.nan] * 7, index=idx),
        "quarterly": pd.Series([5.0] + [np.nan] * 7, index=idx),
    })
    out = bounded_ffill(df, limit=2, per_column={"quarterly": 6})
    assert out["monthly"].iloc[3:].isna().all()       # capped at 2
    assert out["quarterly"].iloc[1:7].eq(5.0).all()    # extended to 6


def test_limit_zero_disables_fill():
    df = _frame()
    out = bounded_ffill(df, limit=0)
    assert out["x"].iloc[1:].isna().all()


def test_is_causal_no_backfill():
    idx = pd.date_range("2020-01-31", periods=5, freq="ME")
    s = pd.Series([np.nan, np.nan, 3.0, np.nan, np.nan], index=idx)
    out = bounded_ffill(pd.DataFrame({"x": s}), limit=5)
    # nothing pulled backward into the leading NaNs
    assert out["x"].iloc[:2].isna().all()
    assert out["x"].iloc[2] == 3.0
    assert (out["x"].iloc[3:] == 3.0).all()


def test_series_input():
    idx = pd.date_range("2020-01-31", periods=6, freq="ME")
    s = pd.Series([2.0, np.nan, np.nan, np.nan, 4.0, np.nan], index=idx)
    out = bounded_ffill(s, limit=2)
    assert isinstance(out, pd.Series)
    assert out.iloc[3].__class__ is not None and pd.isna(out.iloc[3])  # capped after 2
    assert out.iloc[5] == 4.0
