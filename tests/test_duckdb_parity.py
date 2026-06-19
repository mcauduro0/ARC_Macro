"""DuckDB as_of backend must match the pandas reference exactly (skips if duckdb absent)."""

from __future__ import annotations

import pandas as pd
import pytest

duckdb = pytest.importorskip("duckdb")

from arc.data import BitemporalStore, Observation
from arc.data.duckdb_store import as_of_wide_duckdb
from arc.data.store import as_of_wide


def _ts(s: str) -> pd.Timestamp:
    return pd.Timestamp(s)


def build_store() -> BitemporalStore:
    store = BitemporalStore()
    store.append([
        Observation(series_id="A", event_time=_ts("2024-01-31"), knowledge_time=_ts("2024-02-10"), value=1.0, source="s"),
        Observation(series_id="A", event_time=_ts("2024-01-31"), knowledge_time=_ts("2024-05-01"), value=1.5, source="s"),  # revision
        Observation(series_id="A", event_time=_ts("2024-02-29"), knowledge_time=_ts("2024-03-10"), value=2.0, source="s"),
        Observation(series_id="B", event_time=_ts("2024-01-31"), knowledge_time=_ts("2024-02-05"), value=9.0, source="s"),
    ])
    return store


@pytest.mark.parametrize("asof", ["2024-02-06", "2024-02-15", "2024-04-01", "2024-06-01"])
def test_duckdb_matches_pandas(asof):
    df = build_store().frame()
    a = as_of_wide(df, _ts(asof))
    b = as_of_wide_duckdb(df, _ts(asof))
    if a.empty and b.empty:
        return
    a = a.sort_index().sort_index(axis=1)
    b = b.sort_index().sort_index(axis=1)
    # Column-index dtype can differ by pandas version (object vs StringDtype when the
    # duckdb .df() path infers str); we only care that the labels+values match.
    a.columns = a.columns.astype("object")
    b.columns = b.columns.astype("object")
    pd.testing.assert_frame_equal(a, b, check_dtype=False, check_column_type=False)


def test_duckdb_respects_revision_and_lag():
    df = build_store().frame()
    # before the revision (2024-05-01): A@Jan = first print 1.0
    assert as_of_wide_duckdb(df, _ts("2024-04-01")).loc[_ts("2024-01-31"), "A"] == 1.0
    # after: revised 1.5
    assert as_of_wide_duckdb(df, _ts("2024-06-01")).loc[_ts("2024-01-31"), "A"] == 1.5
