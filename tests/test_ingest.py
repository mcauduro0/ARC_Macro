"""Ingestion runner tests (stub adapters — no network)."""

from __future__ import annotations

import pandas as pd

from arc.data.adapters.base import Adapter
from arc.data.catalog import get_contract
from arc.data.ingest import ingest_series, report_frame, run_ingestion
from arc.data.store import BitemporalStore


class StubAdapter(Adapter):
    source = "STUB"

    def __init__(self, series: pd.Series) -> None:
        self._series = series

    def fetch_raw(self, contract, since=None):
        return self._series

    def parse(self, raw):
        return raw  # already a clean Series


def test_ingest_applies_publication_lag_and_appends():
    s = pd.Series([0.46], index=pd.to_datetime(["2024-05-31"]))
    store = BitemporalStore()
    res = ingest_series(get_contract("IPCA_MOM"), store, adapter=StubAdapter(s))  # lag=10
    assert res.ok and res.rows_appended == 1
    assert store.as_of(pd.Timestamp("2024-06-05")).empty  # not yet published
    assert store.as_of(pd.Timestamp("2024-06-15")).loc[pd.Timestamp("2024-05-31"), "IPCA_MOM"] == 0.46


def test_ingest_quarantines_out_of_range_values():
    s = pd.Series([5.0, 99.0], index=pd.to_datetime(["2024-04-30", "2024-05-31"]))  # 99 > valid_max 10
    store = BitemporalStore()
    res = ingest_series(get_contract("IPCA_MOM"), store, adapter=StubAdapter(s))
    assert res.rows_appended == 1 and res.rows_quarantined == 1
    assert res.violations  # the out-of-range value is reported, not silently stored


def test_ingest_reports_error_without_silent_substitution():
    class Boom(Adapter):
        source = "STUB"
        def fetch_raw(self, contract, since=None):
            raise RuntimeError("network down")
        def parse(self, raw):
            return raw

    store = BitemporalStore()
    res = ingest_series(get_contract("IPCA_MOM"), store, adapter=Boom())
    assert not res.ok and "network down" in res.error and res.rows_appended == 0


def test_run_ingestion_with_injected_registry():
    s = pd.Series([11.0], index=pd.to_datetime(["2024-01-31"]))
    registry = {"BCB_SGS": lambda: StubAdapter(s)}
    store, report = run_ingestion(["SELIC_TARGET"], registry=registry)
    assert len(report) == 1 and report[0].rows_appended == 1
    df = report_frame(report)
    assert bool(df.iloc[0]["ok"]) and df.iloc[0]["series_id"] == "SELIC_TARGET"
