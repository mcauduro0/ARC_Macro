"""ALFRED (FRED vintage) parsing + Dagster asset-module smoke."""

from __future__ import annotations

import importlib

import pandas as pd
import pytest

from arc.data import BitemporalStore
from arc.data.adapters import FredAdapter
from arc.data.catalog import get_contract


def _raw():
    return {"observations": [
        {"date": "2024-03-31", "realtime_start": "2024-04-25", "realtime_end": "2024-05-29", "value": "1.0"},
        {"date": "2024-03-31", "realtime_start": "2024-05-30", "realtime_end": "9999-12-31", "value": "1.3"},  # revision
        {"date": "2024-06-30", "realtime_start": "2024-07-25", "realtime_end": "9999-12-31", "value": "2.0"},
    ]}


def test_alfred_vintages_use_realtime_start_as_knowledge_time():
    obs = FredAdapter(api_key="x").parse_vintages(_raw(), get_contract("US_CPI"))
    assert len(obs) == 3
    march = [o for o in obs if pd.Timestamp(o.event_time) == pd.Timestamp("2024-03-31")]
    kts = {pd.Timestamp(o.knowledge_time): o.value for o in march}
    assert kts == {pd.Timestamp("2024-04-25"): 1.0, pd.Timestamp("2024-05-30"): 1.3}


def test_alfred_skips_missing():
    raw = {"observations": [{"date": "2024-03-31", "realtime_start": "2024-04-25", "realtime_end": "x", "value": "."}]}
    assert FredAdapter(api_key="x").parse_vintages(raw, get_contract("US_CPI")) == []


def test_alfred_vintages_into_store_respect_revision():
    store = BitemporalStore()
    store.append(FredAdapter(api_key="x").parse_vintages(_raw(), get_contract("US_CPI")))
    # before the 2024-05-30 revision: first print 1.0; after: revised 1.3 (true vintage, no look-ahead)
    assert store.as_of(pd.Timestamp("2024-05-01")).loc[pd.Timestamp("2024-03-31"), "US_CPI"] == 1.0
    assert store.as_of(pd.Timestamp("2024-06-01")).loc[pd.Timestamp("2024-03-31"), "US_CPI"] == 1.3


def test_dagster_assets_module_defines_definitions():
    pytest.importorskip("dagster")
    mod = importlib.import_module("orchestration.dagster.assets")
    assert hasattr(mod, "defs")
    assert hasattr(mod, "bitemporal_observations") and hasattr(mod, "ingestion_health")
