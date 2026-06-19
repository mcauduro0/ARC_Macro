"""BCB SGS adapter (public, no API key).

API: https://api.bcb.gov.br/dados/serie/bcdata.sgs.{code}/dados?formato=json
Returns: [{"data": "dd/MM/yyyy", "valor": "0.46"}, ...] (BR date format).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

import pandas as pd

from arc.contracts import SeriesContract
from arc.data.adapters.base import Adapter

BASE_URL = "https://api.bcb.gov.br/dados/serie/bcdata.sgs.{code}/dados"


class BcbSgsAdapter(Adapter):
    source = "BCB_SGS"

    def __init__(self, timeout: float = 15.0) -> None:
        self.timeout = timeout

    def fetch_raw(self, contract: SeriesContract, since: Optional[datetime] = None) -> Any:
        import requests  # lazy: keeps module import light for tests/CI

        if not contract.source_code:
            raise ValueError(f"{contract.series_id}: BCB SGS requires source_code")
        params = {"formato": "json"}
        if since is not None:
            params["dataInicial"] = pd.Timestamp(since).strftime("%d/%m/%Y")
        r = requests.get(BASE_URL.format(code=contract.source_code), params=params, timeout=self.timeout)
        r.raise_for_status()
        return r.json()

    def parse(self, raw: Any) -> pd.Series:
        """[{'data': 'dd/MM/yyyy', 'valor': '0.46'}] -> float Series indexed by date.
        Handles both dot and comma decimals."""
        if not raw:
            return pd.Series(dtype="float64")
        df = pd.DataFrame(raw)
        idx = pd.to_datetime(df["data"], format="%d/%m/%Y")
        vals = df["valor"].astype(str).str.replace(",", ".", regex=False)
        return self._clean(pd.Series(vals.values, index=idx))
