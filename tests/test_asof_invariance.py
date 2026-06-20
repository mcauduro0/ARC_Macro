"""As-of-invariance gate on the REAL engine pipeline (Phase 3 safety net).

The whole anti-leak program rests on one property: the value the engine computes for a decision
month E must depend ONLY on data knowable at E. The engine builds its monthly frame ONCE from the
full series, so any feature that secretly uses post-E data (the interpolation leak we just fixed, a
full-sample fit, a future-blended resample) will differ from the honest as-of-E value.

This gate exercises ``DataLayer.build_monthly`` at several HISTORICAL decision dates E (far from the
data frontier, so legitimate frontier ffill/extension does not confound the comparison) and asserts
that the value AT month E is identical whether built from the as-of-E vintage of the RAW data or from
the full series. It would have caught the linear-interpolation look-ahead; it now guards against
regressions and any new pipeline leak.

Guarded: importing the engine needs xgboost/hmmlearn and the comparison needs the collected CSVs.
Heavy (rebuilds the monthly frame per as-of date) but only a handful of dates.
"""

from __future__ import annotations

import importlib.util
import os
import sys

import pandas as pd
import pytest

_HAS_ML = all(importlib.util.find_spec(m) is not None for m in ("xgboost", "hmmlearn"))
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DATA = os.path.join(_ROOT, "server", "model", "data")
_HAS_DATA = os.path.isdir(_DATA) and len([f for f in os.listdir(_DATA) if f.endswith(".csv")]) > 20

pytestmark = pytest.mark.skipif(not (_HAS_ML and _HAS_DATA), reason="needs xgboost/hmmlearn + collected data")

# Decision dates well inside the sample (data runs ~2010..2026), so frontier effects (reer/ppp
# forward-fill-beyond-last, lag-shift NaNs) do not touch month E.
_DECISION_DATES = ["2016-06-30", "2018-09-30", "2020-06-30", "2022-06-30"]
# The confirmed-leak columns: annual fundamentals upsampled to monthly. These MUST be PIT.
_INTERPOLATED = ["ppp_factor", "gdppc_ratio", "ca_pct_gdp", "trade_openness"]


def _trimmed_layer(asof):
    """A DataLayer with raw data trimmed to event_time <= asof (the as-of-asof vintage)."""
    sys.path.insert(0, os.path.join(_ROOT, "server", "model"))
    sys.path.insert(0, _ROOT)
    import macro_risk_os_v2 as eng

    dl = eng.DataLayer(eng.DEFAULT_CONFIG)
    dl.load_all()
    asof_ts = pd.Timestamp(asof)
    for k, s in list(dl.data.items()):
        if isinstance(s, pd.Series) and len(s):
            dl.data[k] = s[pd.to_datetime(s.index) <= asof_ts]
    return eng, dl


def _monthly_asof(asof) -> pd.DataFrame:
    """Build the monthly frame using only RAW data with event_time <= asof (the as-of-asof vintage)."""
    _eng, dl = _trimmed_layer(asof)
    dl.build_monthly()
    cols = {k: v for k, v in dl.monthly.items() if isinstance(v, pd.Series) and len(v)}
    return pd.DataFrame(cols)


def _features_asof(asof) -> pd.DataFrame:
    """Build the FULL feature_df (FeatureEngine.build_all) from the as-of-asof raw vintage."""
    eng, dl = _trimmed_layer(asof)
    dl.build_monthly()
    dl.compute_instrument_returns()
    fe = eng.FeatureEngine(dl, eng.DEFAULT_CONFIG)
    fe.build_all()
    return fe.feature_df


def _full_frame() -> pd.DataFrame:
    return _monthly_asof("2026-12-31")


def test_interpolated_fundamentals_are_point_in_time():
    """The columns whose look-ahead we fixed must be invariant at the decision date."""
    full = _full_frame()
    for E in _DECISION_DATES:
        asof = _monthly_asof(E)
        Ets = pd.Timestamp(E)
        for c in _INTERPOLATED:
            if c in asof.columns and c in full.columns and Ets in asof.index and Ets in full.index:
                a, f = asof[c].get(Ets), full[c].get(Ets)
                if pd.notna(a) and pd.notna(f):
                    assert abs(a - f) < 1e-9, (
                        f"LOOK-AHEAD: {c} at {E} differs as-of={a} vs full={f} "
                        f"(value at E depends on post-E data)")


def test_no_column_uses_future_data_at_decision_date():
    """Strong gate: at a historical decision month E, EVERY monthly column's value at E must be the
    same built from the as-of-E vintage or the full series. A difference means that column leaks
    post-E data into the decision. (Restricted to dates far from the frontier; tolerance is numerical.)"""
    full = _full_frame()
    leaks = []
    for E in _DECISION_DATES:
        asof = _monthly_asof(E)
        Ets = pd.Timestamp(E)
        if Ets not in asof.index or Ets not in full.index:
            continue
        common = [c for c in asof.columns if c in full.columns]
        for c in common:
            a, f = asof[c].get(Ets), full[c].get(Ets)
            if pd.notna(a) and pd.notna(f):
                denom = max(1.0, abs(f))
                if abs(a - f) / denom > 1e-6:
                    leaks.append(f"{c}@{E}: as-of={a:.6g} full={f:.6g} (rel diff {abs(a-f)/denom:.2e})")
    assert not leaks, "as-of-invariance violations at the decision date:\n  " + "\n  ".join(leaks)


def test_full_feature_pipeline_is_point_in_time():
    """The crown-jewel gate: EVERY column of the full FeatureEngine.build_all() output (Z-scores,
    carry, FX valuation, term premium, the equilibrium r* composite, etc.) must be invariant at the
    decision month E — built from the as-of-E raw vintage vs the full series. This proves the entire
    feature construction is point-in-time, so the build-once feature_df the engine slices per step is
    already honest (no per-step rebuild needed for correctness). It catches the interpolation leak:
    with ARC_CAUSAL_INTERP=0 it flags ppp_fair_ts."""
    full = _features_asof("2026-12-31")
    leaks = []
    for E in ["2018-09-30", "2020-06-30", "2022-06-30"]:
        asof = _features_asof(E)
        Ets = pd.Timestamp(E)
        if Ets not in asof.index or Ets not in full.index:
            continue
        for c in [c for c in asof.columns if c in full.columns]:
            a, f = asof[c].get(Ets), full[c].get(Ets)
            if pd.notna(a) and pd.notna(f):
                denom = max(1.0, abs(f))
                if abs(a - f) / denom > 1e-6:
                    leaks.append(f"{c}@{E}: as-of={a:.6g} full={f:.6g} (rel diff {abs(a-f)/denom:.2e})")
    assert not leaks, "feature-pipeline as-of-invariance violations at the decision date:\n  " + "\n  ".join(leaks)
