"""Strangler shadow-diff: arc.features.rolling_zscore must reproduce the engine's original
_z_score_rolling exactly (behavior-preserving extraction)."""

from __future__ import annotations

import importlib.util
import os
import sys

import numpy as np
import pytest

from arc.causal import causal_winsorize
from arc.features import rolling_zscore
from tests.canary import make_series

_HAS_ML = all(importlib.util.find_spec(m) is not None for m in ("xgboost", "hmmlearn"))


def test_rolling_zscore_matches_manual_window():
    s = make_series(n=120, seed=3)
    z = rolling_zscore(s, 36, 0.5, winsorize_fn=lambda x: x)  # identity winsorize
    i = s.index[80]
    win = s.iloc[80 - 36 + 1 : 80 + 1]
    expected = (s.loc[i] - win.mean()) / max(win.std(), 0.5)
    assert abs(z.loc[i] - expected) < 1e-9


def test_rolling_zscore_with_causal_winsorize_is_as_of_invariant():
    # rolling_zscore drops leading NaNs, so compare by index (not position): future data
    # must not change z at any shared past event_time.
    s = make_series(n=140, future_shock=True)
    fn = lambda x: rolling_zscore(x, 60, 0.5, winsorize_fn=lambda z: causal_winsorize(z, 0.05, 0.95, min_periods=10))
    full = fn(s)
    for k in (80, 110):
        prefix = fn(s.iloc[:k])
        common = full.index.intersection(prefix.index)
        assert len(common) > 0
        assert np.allclose(full.loc[common].to_numpy(), prefix.loc[common].to_numpy(), equal_nan=True)


@pytest.mark.skipif(not _HAS_ML, reason="full ML stack (xgboost/hmmlearn) not installed")
def test_extracted_zscore_reproduces_original_engine_logic():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sys.path.insert(0, os.path.join(root, "server", "model"))
    sys.path.insert(0, root)
    import macro_risk_os_v2 as eng

    cfg = eng.DEFAULT_CONFIG
    s = make_series(n=140, future_shock=True, seed=11)

    # the engine's (now-delegating) method
    fe = eng.FeatureEngine.__new__(eng.FeatureEngine)
    fe.cfg = cfg
    engine_out = fe._z_score_rolling(s)

    # inline replica of the ORIGINAL pre-extraction logic (shadow baseline)
    w = cfg["standardization_window_months"]
    f = cfg["std_floor"]
    mean_r = s.rolling(w, min_periods=max(24, w // 2)).mean()
    std_r = s.rolling(w, min_periods=max(24, w // 2)).std().clip(lower=f)
    z = (s - mean_r) / std_r
    original_out = eng.winsorize(z.dropna())

    assert engine_out.index.equals(original_out.index)
    assert np.allclose(engine_out.to_numpy(), original_out.to_numpy(), equal_nan=True)
