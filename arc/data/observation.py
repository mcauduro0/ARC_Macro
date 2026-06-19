"""The bitemporal observation row + publication-lag logic."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field

from arc.contracts import SeriesContract


class Observation(BaseModel):
    """One immutable datum as fetched. The system of record is an append-only ledger of
    these rows (ARCHITECTURE_SOTA.md §4.1)."""

    model_config = ConfigDict(extra="forbid")

    series_id: str
    event_time: datetime = Field(description="the period the datum describes (e.g. IPCA ref month)")
    knowledge_time: datetime = Field(description="earliest wall-clock instant the value was knowable")
    value: float
    source: str
    vintage_id: Optional[str] = None
    ingest_run_id: Optional[str] = None
    source_url: Optional[str] = None
    source_hash: Optional[str] = None


# Canonical column order for the store / Parquet lake.
COLUMNS = [
    "series_id", "event_time", "knowledge_time", "value",
    "source", "vintage_id", "ingest_run_id", "source_url", "source_hash",
]


def compute_knowledge_time(
    event_time: datetime,
    publication_lag_days: int,
    publish_ts: Optional[datetime] = None,
) -> datetime:
    """Earliest instant a value for ``event_time`` could be known.

    = max(event_time + publication_lag_days, publish_ts-if-known). Using the contracted
    lag prevents the look-ahead of stamping a macro release at its reference date (when it
    was not yet published). When the source provides a true publish timestamp, the later of
    the two wins (a release can only be later than the floor, never earlier).
    """
    floor = pd.Timestamp(event_time) + timedelta(days=int(publication_lag_days))
    if publish_ts is not None:
        return max(floor, pd.Timestamp(publish_ts)).to_pydatetime()
    return floor.to_pydatetime()


def observations_from_series(
    series: pd.Series,
    contract: SeriesContract,
    *,
    source: Optional[str] = None,
    vintage_id: Optional[str] = None,
    ingest_run_id: Optional[str] = None,
    publish_ts: Optional[datetime] = None,
) -> list[Observation]:
    """Convert a plain (event_time-indexed) Series into bitemporal Observations, applying
    the contract's publication lag to derive each knowledge_time. This is the bridge from
    the legacy event-time-only CSVs to the bitemporal store."""
    obs: list[Observation] = []
    for ev, val in series.dropna().items():
        kt = compute_knowledge_time(pd.Timestamp(ev).to_pydatetime(), contract.publication_lag_days, publish_ts)
        obs.append(
            Observation(
                series_id=contract.series_id,
                event_time=pd.Timestamp(ev).to_pydatetime(),
                knowledge_time=kt,
                value=float(val),
                source=source or contract.source,
                vintage_id=vintage_id,
                ingest_run_id=ingest_run_id,
            )
        )
    return obs
