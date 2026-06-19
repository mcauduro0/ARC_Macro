"""FRED adapter.

API: https://api.stlouisfed.org/fred/series/observations?series_id=DGS10&api_key=..&file_type=json
Returns: {"observations": [{"date": "yyyy-MM-dd", "value": "4.5"}, ...]} ("." = missing).

TODO(vintage): switch to ALFRED (realtime_start/realtime_end) to record true vintages
instead of the catalog's fixed publication-lag approximation (ARCHITECTURE_SOTA.md §4.1).
"""

from __future__ import annotations

import os
from datetime import datetime
from typing import Any, Optional

import pandas as pd

from arc.contracts import SeriesContract
from arc.data.adapters.base import Adapter

BASE_URL = "https://api.stlouisfed.org/fred/series/observations"
# Owner opted to keep the existing key as fallback (see memory: arc-macro-secrets-decision).
_FALLBACK_KEY = "e63bf4ad4b21136be0b68c27e7e510d9"


class FredAdapter(Adapter):
    source = "FRED"

    def __init__(self, api_key: Optional[str] = None, timeout: float = 15.0) -> None:
        self.api_key = api_key or os.environ.get("FRED_API_KEY", _FALLBACK_KEY)
        self.timeout = timeout

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
