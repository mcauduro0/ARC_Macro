"""Publication-lag shift in DataLayer.build_monthly (audit P5).

Macro series are indexed by reference month but released weeks later; using value[M] at the end of
month M is a look-ahead. build_monthly shifts each lagged series forward by its release lag (toggle
ARC_PUBLICATION_LAG). This checks the shift happens for a lagged series, by the right amount, and not
for real-time market data. Engine import + data load are needed, so this is guarded.
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
_HAS_DATA = os.path.isdir(_DATA) and len([f for f in os.listdir(_DATA) if f.endswith(".csv")]) > 20 if os.path.isdir(_DATA) else False

pytestmark = pytest.mark.skipif(not (_HAS_ML and _HAS_DATA), reason="needs xgboost/hmmlearn + collected data")


def _build(pub_lag: str):
    sys.path.insert(0, os.path.join(_ROOT, "server", "model"))
    sys.path.insert(0, _ROOT)
    import macro_risk_os_v2 as eng
    os.environ["ARC_PUBLICATION_LAG"] = pub_lag
    dl = eng.DataLayer(eng.DEFAULT_CONFIG)
    dl.load_all(); dl.build_monthly()
    return dl


def test_lagged_series_shifted_by_release_lag(monkeypatch):
    off = _build("0")
    on = _build("1")
    # ibc_br has a 2-month release lag: the ON series at date M should equal the OFF series at M-2
    a = off.monthly.get("ibc_br")
    b = on.monthly.get("ibc_br")
    assert a is not None and b is not None and len(a) > 12
    common = a.index.intersection(b.index)[6:]  # skip the leading NaNs introduced by the shift
    # b == a.shift(2) on the common index
    expected = a.shift(2).reindex(common)
    got = b.reindex(common)
    m = expected.notna() & got.notna()
    assert m.sum() > 12
    assert (expected[m] - got[m]).abs().max() < 1e-9


def test_market_series_not_shifted(monkeypatch):
    off = _build("0")
    on = _build("1")
    # ptax (FX, real-time) must be identical with and without the publication-lag toggle
    a, b = off.monthly.get("ptax"), on.monthly.get("ptax")
    common = a.index.intersection(b.index)
    m = a.reindex(common).notna() & b.reindex(common).notna()
    assert (a.reindex(common)[m] - b.reindex(common)[m]).abs().max() < 1e-9
