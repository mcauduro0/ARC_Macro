"""DuckDB backend for as_of() — the production accelerator over the same Parquet/Arrow lake.

Implements identical semantics to the pandas ``as_of_long``/``as_of_wide`` (per
(series_id, event_time): the row with the greatest knowledge_time <= asof, deterministic
tie-break on _seq). A parity test asserts the two engines agree, so the fast path can be
trusted. DuckDB is an optional dependency (``pip install duckdb``); import is lazy.
"""

from __future__ import annotations

from datetime import datetime
from typing import Iterable, Optional

import pandas as pd

_ASOF_SQL = """
SELECT series_id, event_time, value FROM (
    SELECT series_id, event_time, value,
           row_number() OVER (
               PARTITION BY series_id, event_time
               ORDER BY knowledge_time DESC, _seq DESC
           ) AS rn
    FROM obs
    WHERE knowledge_time <= ?
) WHERE rn = 1
ORDER BY series_id, event_time
"""


def as_of_long_duckdb(
    df: pd.DataFrame,
    asof_ts: datetime,
    series_ids: Optional[Iterable[str]] = None,
) -> pd.DataFrame:
    import duckdb  # lazy/optional

    d = df if series_ids is None else df[df["series_id"].isin(list(series_ids))]
    cols = ["series_id", "event_time", "value"]
    if d.empty:
        return pd.DataFrame({c: pd.Series(dtype=df[c].dtype if c in df else "object") for c in cols})
    d = d.copy()
    if "_seq" not in d.columns:
        d["_seq"] = range(len(d))
    con = duckdb.connect()
    try:
        con.register("obs", d)
        res = con.execute(_ASOF_SQL, [pd.Timestamp(asof_ts)]).df()
    finally:
        con.close()
    return res


def as_of_wide_duckdb(
    df: pd.DataFrame,
    asof_ts: datetime,
    series_ids: Optional[Iterable[str]] = None,
) -> pd.DataFrame:
    long = as_of_long_duckdb(df, asof_ts, series_ids)
    if long.empty:
        return pd.DataFrame()
    long["event_time"] = pd.to_datetime(long["event_time"])
    wide = long.pivot(index="event_time", columns="series_id", values="value").sort_index()
    wide.columns.name = None
    return wide
