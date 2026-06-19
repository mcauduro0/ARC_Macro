"""Adapter base class."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Optional

import pandas as pd

from arc.contracts import SeriesContract
from arc.data.observation import Observation, observations_from_series


class Adapter(ABC):
    """Fetch + parse one provider. Subclasses implement ``fetch_raw`` (network) and
    ``parse`` (pure). ``fetch`` ties them together and applies the publication lag."""

    source: str = "UNKNOWN"

    @abstractmethod
    def fetch_raw(self, contract: SeriesContract, since: Optional[datetime] = None) -> Any:
        """Network call. Returns the provider's raw payload (json/list/DataFrame)."""

    @abstractmethod
    def parse(self, raw: Any) -> pd.Series:
        """Pure: provider payload -> float Series indexed by event_time (sorted, no NaN)."""

    def fetch(
        self,
        contract: SeriesContract,
        since: Optional[datetime] = None,
        *,
        ingest_run_id: Optional[str] = None,
        publish_ts: Optional[datetime] = None,
    ) -> list[Observation]:
        raw = self.fetch_raw(contract, since)
        series = self.parse(raw)
        return observations_from_series(
            series, contract, source=self.source, ingest_run_id=ingest_run_id, publish_ts=publish_ts
        )

    @staticmethod
    def _clean(series: pd.Series) -> pd.Series:
        s = pd.to_numeric(series, errors="coerce").dropna()
        s.index = pd.to_datetime(s.index)
        return s.sort_index()
