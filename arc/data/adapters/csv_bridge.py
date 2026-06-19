"""Bridge legacy event-time CSVs (data_collector.save_series output) into the bitemporal
store, applying the contract's publication lag so historical loads are point-in-time.

The legacy save_series writes one CSV per series (a date index + a value column) and
OVERWRITES it each run, destroying revisions. This bridge lets us ingest those CSVs as a
single best-known vintage while the real per-vintage adapters take over.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

import pandas as pd

from arc.contracts import SeriesContract
from arc.data.observation import Observation, observations_from_series


def observations_from_csv(
    path: str,
    contract: SeriesContract,
    *,
    date_col: Optional[str] = None,
    value_col: Optional[str] = None,
    ingest_run_id: Optional[str] = None,
    publish_ts: Optional[datetime] = None,
) -> list[Observation]:
    df = pd.read_csv(path)
    # default: first column is the date index, second is the value
    dc = date_col or df.columns[0]
    vc = value_col or (df.columns[1] if len(df.columns) > 1 else df.columns[0])
    s = pd.Series(pd.to_numeric(df[vc], errors="coerce").values, index=pd.to_datetime(df[dc]))
    s = s.dropna().sort_index()
    return observations_from_series(
        s, contract, source=contract.source, ingest_run_id=ingest_run_id, publish_ts=publish_ts
    )
