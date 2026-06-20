"""carry_hard must be the sovereign-SPREAD carry, not the cupom cambial (FX) — Phase 4 fix.

The `hard` instrument return earns the spread carry (embi/10000/12). The legacy code used the cupom
cambial (FX carry), whose correlation with sovereign signals is ~0, making carry-neutralization of
`hard` vacuous and overstating its edge. This guards the fix and the measurement toggle.

Guarded: needs the engine (xgboost/hmmlearn) + collected CSVs.
"""

from __future__ import annotations

import importlib.util
import os
import sys

import numpy as np
import pandas as pd
import pytest

_HAS_ML = all(importlib.util.find_spec(m) is not None for m in ("xgboost", "hmmlearn"))
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DATA = os.path.join(_ROOT, "server", "model", "data")
_HAS_DATA = os.path.isdir(_DATA) and len([f for f in os.listdir(_DATA) if f.endswith(".csv")]) > 20

pytestmark = pytest.mark.skipif(not (_HAS_ML and _HAS_DATA), reason="needs xgboost/hmmlearn + collected data")


def _carry_hard(spread_toggle: str):
    sys.path.insert(0, os.path.join(_ROOT, "server", "model"))
    sys.path.insert(0, _ROOT)
    import macro_risk_os_v2 as eng
    os.environ["ARC_CARRY_HARD_SPREAD"] = spread_toggle
    dl = eng.DataLayer(eng.DEFAULT_CONFIG)
    dl.load_all().build_monthly().compute_instrument_returns()
    fe = eng.FeatureEngine(dl, eng.DEFAULT_CONFIG)
    fe.build_all()
    return fe.features.get("carry_hard"), dl.monthly.get("embi_spread")


def test_carry_hard_is_spread_carry_by_default():
    carry_hard, embi = _carry_hard("1")
    assert carry_hard is not None and embi is not None and len(carry_hard) > 12
    expected = (embi / 10000.0 / 12.0)
    common = carry_hard.index.intersection(expected.index)
    m = carry_hard.reindex(common).notna() & expected.reindex(common).notna()
    assert m.sum() > 12
    assert (carry_hard.reindex(common)[m] - expected.reindex(common)[m]).abs().max() < 1e-12


def test_legacy_toggle_differs_from_spread():
    spread, _ = _carry_hard("1")
    cupom, _ = _carry_hard("0")
    # the legacy cupom carry must be a materially different series (not the spread carry)
    common = spread.index.intersection(cupom.index)
    m = spread.reindex(common).notna() & cupom.reindex(common).notna()
    assert m.sum() > 12
    assert (spread.reindex(common)[m] - cupom.reindex(common)[m]).abs().max() > 1e-6
    os.environ["ARC_CARRY_HARD_SPREAD"] = "1"  # restore default for other tests
