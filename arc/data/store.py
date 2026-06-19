"""Append-only bitemporal store + the single ``as_of`` primitive.

Pandas-backed for portability (runs in CI/research with no extra deps). DuckDB is the
production accelerator over the same Parquet lake (ARCHITECTURE_SOTA.md §2/§4.1); the
``as_of`` semantics here are the contract DuckDB's ASOF JOIN must match.
"""

from __future__ import annotations

from datetime import datetime
from typing import Iterable, Optional

import pandas as pd

from arc.data.observation import COLUMNS, Observation


def _empty_frame() -> pd.DataFrame:
    df = pd.DataFrame({c: pd.Series(dtype="object") for c in COLUMNS})
    df["event_time"] = pd.to_datetime(df["event_time"])
    df["knowledge_time"] = pd.to_datetime(df["knowledge_time"])
    df["value"] = df["value"].astype("float64")
    return df


def as_of_long(
    df: pd.DataFrame,
    asof_ts: datetime,
    series_ids: Optional[Iterable[str]] = None,
) -> pd.DataFrame:
    """Pure as-of selection: per (series_id, event_time), the row with the greatest
    knowledge_time <= asof_ts. Deterministic tie-break on the append sequence (_seq)."""
    asof = pd.Timestamp(asof_ts)
    d = df[df["knowledge_time"] <= asof]
    if series_ids is not None:
        d = d[d["series_id"].isin(list(series_ids))]
    if d.empty:
        return d.copy()
    sort_cols = ["series_id", "event_time", "knowledge_time"]
    if "_seq" in d.columns:
        sort_cols.append("_seq")
    d = d.sort_values(sort_cols)
    # last row per (series_id, event_time) == max knowledge_time (then max _seq on ties)
    return d.groupby(["series_id", "event_time"], as_index=False, sort=False).tail(1).reset_index(drop=True)


def as_of_wide(
    df: pd.DataFrame,
    asof_ts: datetime,
    series_ids: Optional[Iterable[str]] = None,
) -> pd.DataFrame:
    """as_of view pivoted to event_time (index) x series_id (columns) — what features consume."""
    long = as_of_long(df, asof_ts, series_ids)
    if long.empty:
        return pd.DataFrame()
    wide = long.pivot(index="event_time", columns="series_id", values="value").sort_index()
    wide.columns.name = None
    return wide


class BitemporalStore:
    """Append-only ledger of Observations. Never updates or deletes existing rows."""

    def __init__(self) -> None:
        self._df = _empty_frame()
        self._df["_seq"] = pd.Series(dtype="int64")
        self._seq = 0

    def __len__(self) -> int:
        return len(self._df)

    def append(self, observations: Iterable[Observation]) -> int:
        rows = []
        for o in observations:
            d = o.model_dump()
            d["_seq"] = self._seq
            self._seq += 1
            rows.append(d)
        if not rows:
            return 0
        new = pd.DataFrame(rows)
        new["event_time"] = pd.to_datetime(new["event_time"])
        new["knowledge_time"] = pd.to_datetime(new["knowledge_time"])
        new["value"] = new["value"].astype("float64")
        self._df = pd.concat([self._df, new], ignore_index=True)
        return len(rows)

    def frame(self) -> pd.DataFrame:
        """Defensive copy of the full ledger (all vintages)."""
        return self._df.copy()

    def as_of(
        self,
        asof_ts: datetime,
        series_ids: Optional[Iterable[str]] = None,
        *,
        wide: bool = True,
    ) -> pd.DataFrame:
        """THE causal primitive. Returns values knowable at asof_ts."""
        if wide:
            return as_of_wide(self._df, asof_ts, series_ids)
        return as_of_long(self._df, asof_ts, series_ids)

    def as_of_series(self, asof_ts: datetime, series_id: str) -> pd.Series:
        """Convenience: a single series' as-of view as a Series indexed by event_time."""
        long = as_of_long(self._df, asof_ts, [series_id])
        if long.empty:
            return pd.Series(dtype="float64", name=series_id)
        s = long.set_index("event_time")["value"].sort_index()
        s.name = series_id
        return s

    def freshness_gap(self, series_id: str, asof_ts: datetime) -> Optional[pd.Timedelta]:
        """How stale a series is at asof_ts: asof_ts - max(knowledge_time<=asof). None if
        never seen. Feeds the freshness gate that replaces silent stale fallbacks."""
        d = self._df[(self._df["series_id"] == series_id) & (self._df["knowledge_time"] <= pd.Timestamp(asof_ts))]
        if d.empty:
            return None
        return pd.Timestamp(asof_ts) - d["knowledge_time"].max()

    # --- persistence (Parquet preferred, CSV fallback for envs without pyarrow) ---
    def save(self, path: str) -> None:
        if path.endswith(".parquet"):
            self._df.to_parquet(path, index=False)
        else:
            self._df.to_csv(path, index=False)

    @classmethod
    def load(cls, path: str) -> "BitemporalStore":
        store = cls()
        df = pd.read_parquet(path) if path.endswith(".parquet") else pd.read_csv(path, parse_dates=["event_time", "knowledge_time"])
        if "_seq" not in df.columns:
            df["_seq"] = range(len(df))
        store._df = df
        store._seq = int(df["_seq"].max()) + 1 if len(df) else 0
        return store
