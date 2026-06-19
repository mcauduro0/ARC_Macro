"""FRED / ALFRED adapter.

FRED (latest):  /fred/series/observations?series_id=DGS10&file_type=json
  -> {"observations": [{"date": "yyyy-MM-dd", "value": "4.5"}, ...]} ("." = missing).

ALFRED (vintages): same endpoint with realtime_start/realtime_end. Requesting the full
realtime range returns EVERY vintage; each row carries its own ``realtime_start`` = the date
that value became publicly known. That is the TRUE knowledge_time — no fixed-lag guess, no
revision look-ahead. ``fetch_vintages`` uses this; it is the point-in-time-correct path.
"""

from __future__ import annotations

import os
from datetime import datetime
from typing import Any, Optional

import pandas as pd

from arc.contracts import SeriesContract
from arc.data.adapters.base import Adapter
from arc.data.observation import Observation

BASE_URL = "https://api.stlouisfed.org/fred/series/observations"
# Owner opted to keep the existing key as fallback (see memory: arc-macro-secrets-decision).
_FALLBACK_KEY = "e63bf4ad4b21136be0b68c27e7e510d9"
_REALTIME_MIN = "1776-07-04"
_REALTIME_MAX = "9999-12-31"


class FredAdapter(Adapter):
    source = "FRED"

    def __init__(self, api_key: Optional[str] = None, timeout: float = 15.0) -> None:
        self.api_key = api_key or os.environ.get("FRED_API_KEY", _FALLBACK_KEY)
        self.timeout = timeout

    # --- latest-only path (knowledge_time via catalog fixed lag) ---
    def fetch_raw(self, contract: SeriesContract, since: Optional[datetime] = None) -> Any:
        import requests  # lazy

        if not contract.source_code:
            raise ValueError(f"{contract.series_id}: FRED requires source_code (e.g. DGS10)")
        params = {"series_id": contract.source_code, "api_key": self.api_key, "file_type": "json"}
        if since is not None:
            params["observation_start"] = pd.Timestamp(since).strftime("%Y-%m-%d")
        r = requests.get(BASE_URL, params=params, timeout=self.timeout)
        r.raise_for_status()
        return r.json()

    def parse(self, raw: Any) -> pd.Series:
        obs = (raw or {}).get("observations", [])
        if not obs:
            return pd.Series(dtype="float64")
        df = pd.DataFrame(obs)
        idx = pd.to_datetime(df["date"])
        vals = df["value"].replace(".", pd.NA)  # FRED missing marker
        return self._clean(pd.Series(vals.values, index=idx))

    # --- ALFRED vintage path (TRUE knowledge_time = realtime_start) ---
    def fetch_raw_vintages(self, contract: SeriesContract, since: Optional[datetime] = None) -> Any:
        import requests  # lazy

        if not contract.source_code:
            raise ValueError(f"{contract.series_id}: FRED requires source_code")
        params = {
            "series_id": contract.source_code, "api_key": self.api_key, "file_type": "json",
            "realtime_start": _REALTIME_MIN, "realtime_end": _REALTIME_MAX,
        }
        if since is not None:
            params["observation_start"] = pd.Timestamp(since).strftime("%Y-%m-%d")
        r = requests.get(BASE_URL, params=params, timeout=self.timeout)
        r.raise_for_status()
        return r.json()

    def parse_vintages(self, raw: Any, contract: SeriesContract,
                       *, ingest_run_id: Optional[str] = None) -> list[Observation]:
        """ALFRED rows -> Observations. event_time=date, knowledge_time=realtime_start (true
        vintage). Each (date, vintage) is a distinct append-only row; revisions are preserved."""
        out: list[Observation] = []
        for o in (raw or {}).get("observations", []):
            val = o.get("value")
            if val in (None, ".", ""):
                continue
            out.append(Observation(
                series_id=contract.series_id,
                event_time=pd.Timestamp(o["date"]).to_pydatetime(),
                knowledge_time=pd.Timestamp(o["realtime_start"]).to_pydatetime(),
                value=float(val),
                source=self.source,
                vintage_id=o.get("realtime_start"),
                ingest_run_id=ingest_run_id,
            ))
        return out

    def fetch_vintages(self, contract: SeriesContract, since: Optional[datetime] = None,
                       *, ingest_run_id: Optional[str] = None) -> list[Observation]:
        raw = self.fetch_raw_vintages(contract, since)
        return self.parse_vintages(raw, contract, ingest_run_id=ingest_run_id)
