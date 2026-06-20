"""Causal annual->monthly upsampling — the as-of-invariance fix for the interpolation look-ahead.

The 2026-06 adversarial leak hunt confirmed that linear interpolation of annual fundamentals
(ppp_factor, gdppc_ratio, ca_pct_gdp, trade_openness) to monthly pulls the NEXT (future) annual
anchor into intermediate months. The causal transform holds the last KNOWN anchor instead. The
decisive property: appending a future anchor must not change any earlier month.
"""

from __future__ import annotations

import pandas as pd

from arc.features.interpolation import causal_annual_to_monthly, linear_annual_to_monthly


def _annual(values, start="2010-12-31"):
    idx = pd.date_range(start, periods=len(values), freq="YE")
    return pd.Series(values, index=idx, dtype="float64")


def test_causal_holds_last_known_value_not_future_blend():
    s = _annual([1.0, 2.0, 3.0])  # 2010, 2011, 2012 year-ends
    m = causal_annual_to_monthly(s)
    # mid-2011 must equal the 2011 anchor (2.0), NOT a blend toward the 2012 anchor (3.0)
    jun2012 = m.loc["2012-06-30"] if "2012-06-30" in m.index else m.asof(pd.Timestamp("2012-06-30"))
    assert jun2012 == 2.0
    # linear interp, by contrast, blends 2.0 -> 3.0 across 2012, so mid-2012 is strictly between
    lin = linear_annual_to_monthly(s)
    assert 2.0 < lin.asof(pd.Timestamp("2012-06-30")) < 3.0


def test_causal_is_invariant_to_future_data():
    """Point-in-time: the value at a mid-year month M must be the same whether computed from only the
    data known at M or from the full series. Linear interpolation violates this — at mid-2012 it
    blends toward the 2012 year-end anchor that was not released until Dec 2012 (a future value)."""
    full = _annual([1.0, 2.0, 3.0, 9.0])      # 2010..2013 year-ends
    M = pd.Timestamp("2012-06-30")            # next anchor (2012-12-31) not yet released at M
    vintage = full[full.index <= M]           # what was actually known at M: 2010, 2011 anchors

    # causal: identical value at M with or without future anchors
    c_full = causal_annual_to_monthly(full).asof(M)
    c_vint = causal_annual_to_monthly(vintage).asof(M)
    assert c_full == c_vint == 2.0

    # linear: the M value changes once the future anchor is known => look-ahead
    l_full = linear_annual_to_monthly(full).asof(M)
    l_vint = linear_annual_to_monthly(vintage).asof(M)
    assert abs(l_full - l_vint) > 0.3
    assert 2.0 < l_full < 3.0                 # blended toward the unreleased 2012 anchor


def test_causal_monthly_grid_and_no_nan():
    s = _annual([1.0, 2.0, 3.0])
    m = causal_annual_to_monthly(s)
    assert m.index.freqstr in ("ME", "M")
    assert not m.isna().any()
    assert len(m) >= 24  # ~3 years of months


def test_empty_and_short_inputs():
    assert len(causal_annual_to_monthly(pd.Series(dtype="float64"))) == 0
    one = causal_annual_to_monthly(_annual([5.0]))
    assert (one == 5.0).all()
