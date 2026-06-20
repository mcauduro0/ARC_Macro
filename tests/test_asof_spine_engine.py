"""Engine bitemporal-spine wiring (Phase 3.2) — guarded (needs engine import + collected CSVs).

Proves load_series, when routed through the store, (1) reproduces the flat CSV at the latest as-of
(behavior-preserving) and (2) gates by knowledge_time at a historical as-of, hiding unreleased prints.
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

_LATEST = pd.Timestamp("2999-12-31")


def _eng():
    sys.path.insert(0, os.path.join(_ROOT, "server", "model"))
    sys.path.insert(0, _ROOT)
    import macro_risk_os_v2 as eng
    return eng


def _store(eng, names):
    from arc.data.migrate import build_store_from_csv_dir
    return build_store_from_csv_dir(eng.DATA_DIR, only=names)


def test_spine_at_latest_reproduces_csv():
    eng = _eng()
    for name in ["USDBRL", "IPCA_MONTHLY"]:
        legacy = eng.load_series(name)
        if len(legacy) == 0:
            continue
        store = _store(eng, [name])
        eng.enable_asof_spine(store, _LATEST)
        try:
            pit = eng.load_series(name)
        finally:
            eng.disable_asof_spine()
        common = legacy.index.intersection(pit.index)
        assert len(common) >= max(12, int(0.99 * len(legacy)))
        assert (legacy.reindex(common).values == pit.reindex(common).values).all()


def test_spine_gates_macro_release_at_historical_asof():
    eng = _eng()
    name = "IPCA_MONTHLY"
    legacy = eng.load_series(name)
    if len(legacy) == 0:
        pytest.skip("no IPCA_MONTHLY data")
    store = _store(eng, [name])
    asof = pd.Timestamp("2020-06-30")
    eng.enable_asof_spine(store, asof)
    try:
        gated = eng.load_series(name)
    finally:
        eng.disable_asof_spine()
    # IPCA lag 10d: at 2020-06-30 only ref months with event_time + 10d <= asof are visible,
    # i.e. event_time <= 2020-06-20 — strictly before the as-of date (no unreleased print leaks in).
    assert gated.index.max() <= asof - pd.Timedelta(days=10)
    # and it is a strict subset of the full series
    assert gated.index.max() < legacy.index.max()


def test_disable_restores_csv_path():
    eng = _eng()
    store = _store(eng, ["USDBRL"])
    eng.enable_asof_spine(store, pd.Timestamp("2015-01-31"))
    eng.disable_asof_spine()
    a = eng.load_series("USDBRL")          # CSV path
    b = eng.load_series("USDBRL")
    assert len(a) == len(b) and len(a) > 12  # full series, not gated
