"""Per-series feature coverage filter (_select_covered_features) — fixes fx/hard degeneracy.

A single short-history feature (e.g. Z_hy_spread, 8 months) in an instrument's FEATURE_MAP used to
collapse the complete-case dropna below the 36-row training floor, silently skipping the instrument
(mu defaulted to 0 → IC undefined). The filter drops such columns BEFORE the dropna. Engine import
needs the full ML stack, so this is guarded like the other engine tests.
"""

from __future__ import annotations

import importlib.util
import os
import sys

import numpy as np
import pandas as pd
import pytest

_HAS_ML = all(importlib.util.find_spec(m) is not None for m in ("xgboost", "hmmlearn"))
pytestmark = pytest.mark.skipif(not _HAS_ML, reason="full ML stack (xgboost/hmmlearn) not installed")


def _eng():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sys.path.insert(0, os.path.join(root, "server", "model"))
    sys.path.insert(0, root)
    import macro_risk_os_v2 as eng
    return eng


def _frame():
    idx = pd.date_range("2010-01-31", periods=120, freq="ME")
    rng = np.random.default_rng(0)
    return pd.DataFrame({
        "long_a": rng.normal(size=120),
        "long_b": rng.normal(size=120),
        "long_c": rng.normal(size=120),
        # short-history feature: only the last 8 months are present (the Z_hy_spread pattern)
        "short": pd.Series([np.nan] * 112 + list(rng.normal(size=8)), index=idx).values,
    }, index=idx)


def test_drops_short_history_feature():
    eng = _eng()
    X = _frame()
    # global dropna would collapse to 8 rows; the filter must drop "short" and keep the 3 long ones
    assert len(X.dropna()) == 8
    Xf, keep = eng._select_covered_features(X, 36)
    assert "short" not in keep
    assert set(keep) == {"long_a", "long_b", "long_c"}
    assert len(Xf.dropna()) == 120


def test_noop_when_all_covered():
    eng = _eng()
    idx = pd.date_range("2010-01-31", periods=80, freq="ME")
    X = pd.DataFrame({"a": np.arange(80.0), "b": np.arange(80.0)}, index=idx)
    Xf, keep = eng._select_covered_features(X, 36)
    assert set(keep) == {"a", "b"}


def test_falls_back_when_too_strict():
    """If the threshold would leave <2 columns, keep the original frame rather than over-prune."""
    eng = _eng()
    idx = pd.date_range("2010-01-31", periods=20, freq="ME")
    X = pd.DataFrame({"a": np.arange(20.0), "b": np.arange(20.0)}, index=idx)
    Xf, keep = eng._select_covered_features(X, 36)  # neither column reaches 36
    assert set(keep) == {"a", "b"}  # no-op fallback


def test_toggle_off_restores_global_dropna(monkeypatch):
    eng = _eng()
    monkeypatch.setenv("ARC_FEAT_PER_SERIES", "0")
    X = _frame()
    Xf, keep = eng._select_covered_features(X, 36)
    assert "short" in keep  # disabled => no filtering
    assert len(Xf.dropna()) == 8
