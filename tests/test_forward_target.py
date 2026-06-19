"""Engine forward-target wiring (audit backtest/quant-1: contemporaneous-target bug)."""

from __future__ import annotations

import importlib.util
import os
import sys

import pandas as pd
import pytest

_HAS_ML = all(importlib.util.find_spec(m) is not None for m in ("xgboost", "hmmlearn"))


@pytest.mark.skipif(not _HAS_ML, reason="full ML stack (xgboost/hmmlearn) not installed")
def test_engine_forward_target_default_and_legacy_toggle(monkeypatch):
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sys.path.insert(0, os.path.join(root, "server", "model"))
    sys.path.insert(0, root)
    import macro_risk_os_v2 as eng

    idx = pd.date_range("2020-01-31", periods=5, freq="ME")
    ret = pd.Series([0.0, 0.1, 0.2, 0.3, 0.4], index=idx)

    # default (fix ON): y[t] = ret[t+1]; last forward unknown
    monkeypatch.delenv("ARC_FORWARD_TARGET", raising=False)
    y = eng._forward_target(ret, 1)
    assert y.iloc[0] == pytest.approx(0.1)
    assert y.iloc[2] == pytest.approx(0.3)
    assert pd.isna(y.iloc[-1])

    # legacy toggle (OFF): contemporaneous target unchanged
    monkeypatch.setenv("ARC_FORWARD_TARGET", "0")
    y0 = eng._forward_target(ret, 1)
    assert y0.iloc[0] == ret.iloc[0]
    assert y0.equals(ret)
