"""BCB Focus (Olinda Expectativas) adapter — the survey of market expectations.

Olinda endpoint (12-month-ahead smoothed inflation expectations):
  https://olinda.bcb.gov.br/olinda/servico/Expectativas/versao/v1/odata/ExpectativasMercadoInflacao12Meses
Returns OData: {"value": [{"Indicador": "IPCA", "Data": "yyyy-MM-dd", "Mediana": x, "Media": y, ...}]}.

Key vintage advantage: ``Data`` is the survey/publication date, so each forecast is stored
with the date it became known — no look-ahead from later survey rounds.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

import pandas as pd

from arc.contracts import SeriesContract
from arc.data.adapters.base import Adapter

BASE_URL = (
    "https://olinda.bcb.gov.br/olinda/servico/Expectativas/versao/v1/odata/"
    "ExpectativasMercadoInflacao12Meses"
)


class BcbFocusAdapter(Adapter):
    source = "BCB_FOCUS"

    def __init__(self, stat: str = "Mediana", timeout: float = 30.0, top: int = 2000) -> None:
        self.stat = stat  # Mediana | Media
        self.timeout = timeout
        self.top = top  # cap response size; Olinda's OData date filter is finicky, so we
        # fetch the most-recent N and filter by `since` client-side in fetch().

    def fetch_raw(self, contract: SeriesContract, since: Optional[datetime] = None) -> Any:
        import urllib.parse

        import requests  # lazy

        # Olinda's OData date filter is finicky (400/504); fetch the most-recent N and
        # filter by `since` client-side in fetch(). `since` is intentionally not sent here.
        # IMPORTANT: spaces in $filter MUST be %20, not '+' — requests' default quote_plus
        # makes Olinda misparse the expression ("Edm.Boolean and Edm.String not compatible").
        indicator = contract.source_code or "IPCA"
        query = urllib.parse.urlencode(
            {
                "$format": "json",
                "$orderby": "Data desc",
                "$top": str(self.top),
                "$filter": f"Indicador eq '{indicator}'",
            },
            quote_via=urllib.parse.quote,
        )
        r = requests.get(f"{BASE_URL}?{query}", timeout=self.timeout)
        r.raise_for_status()
        return r.json()

    def parse(self, raw: Any) -> pd.Series:
        rows = (raw or {}).get("value", [])
        if not rows:
            return pd.Series(dtype="float64")
        df = pd.DataFrame(rows)
        idx = pd.to_datetime(df["Data"])
        return self._clean(pd.Series(df[self.stat].values, index=idx))

    def fetch(self, contract, since=None, *, ingest_run_id=None, publish_ts=None):
        # Apply `since` client-side (Olinda date filtering is unreliable).
        obs = super().fetch(contract, since, ingest_run_id=ingest_run_id, publish_ts=publish_ts)
        if since is not None:
            since_ts = pd.Timestamp(since)
            obs = [o for o in obs if pd.Timestamp(o.event_time) >= since_ts]
        return obs
