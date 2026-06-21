"""CFTC Commitments of Traders (COT) adapter — Brazilian Real net speculative positioning.

The CFTC publishes the COT report WEEKLY (Tuesday snapshot, released the following Friday
~3 days later). The Public Reporting Environment exposes it via a Socrata API:

  Legacy "Futures Only" dataset:
    https://publicreporting.cftc.gov/resource/6dca-aqww.json

The CME Brazilian Real contract is identified by:
  - ``cftc_contract_market_code`` == "102741"  (stable numeric id; preferred filter), or
  - ``market_and_exchange_names`` == "BRAZILIAN REAL - CHICAGO MERCANTILE EXCHANGE".

Legacy report classifies reportable open interest into NON-COMMERCIAL (the speculators) and
COMMERCIAL (hedgers). Net speculative positioning is:

  NET = noncomm_positions_long_all - noncomm_positions_short_all   (in number of contracts)

Each row carries ``report_date_as_yyyy_mm_dd`` = the Tuesday the positions were observed
(an ISO-8601 timestamp). That is the event_time; the contract's publication_lag_days (~3,
Tue snapshot -> Fri release) gives the knowledge_time, so no look-ahead from late release.

This module is PURE in ``parse`` (works on a list-of-dict payload identical to the Socrata
JSON rows) and only touches the network in ``fetch_raw`` (requests imported lazily).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

import pandas as pd

from arc.contracts import SeriesContract
from arc.data.adapters.base import Adapter

# Socrata "Legacy - Futures Only" resource. JSON rows; filter + select server-side.
BASE_URL = "https://publicreporting.cftc.gov/resource/6dca-aqww.json"

# CME Brazilian Real, CFTC contract market code (stable numeric id).
BRL_CONTRACT_CODE = "102741"

# Column names in the legacy futures-only dataset.
COL_DATE = "report_date_as_yyyy_mm_dd"          # ISO-8601 timestamp; Tuesday of report week
COL_LONG = "noncomm_positions_long_all"         # non-commercial (speculative) longs, # contracts
COL_SHORT = "noncomm_positions_short_all"       # non-commercial (speculative) shorts, # contracts
COL_CODE = "cftc_contract_market_code"          # "102741" for Brazilian Real


class CftcCotAdapter(Adapter):
    """Weekly CFTC COT net speculative (non-commercial long - short) for the CME contract
    named by ``contract.source_code`` (the CFTC numeric market code; defaults to BRL)."""

    source = "CFTC_COT"

    def __init__(self, timeout: float = 30.0, limit: int = 5000) -> None:
        self.timeout = timeout
        self.limit = limit  # weekly data: 5000 rows ~ 96 years; ample for one contract.

    def fetch_raw(self, contract: SeriesContract, since: Optional[datetime] = None) -> Any:
        import requests  # lazy: keeps module import light for tests/CI

        code = contract.source_code or BRL_CONTRACT_CODE
        params = {
            COL_CODE: code,
            "$select": f"{COL_DATE},{COL_LONG},{COL_SHORT}",
            "$order": f"{COL_DATE} ASC",
            "$limit": str(self.limit),
        }
        if since is not None:
            # Socrata SoQL accepts a floating-timestamp literal (no quotes needed for $where).
            params["$where"] = f"{COL_DATE} >= '{pd.Timestamp(since).strftime('%Y-%m-%dT00:00:00')}'"
        r = requests.get(BASE_URL, params=params, timeout=self.timeout)
        r.raise_for_status()
        return r.json()

    def parse(self, raw: Any) -> pd.Series:
        """Socrata rows -> weekly NET speculative positioning Series (event_time-indexed).

        Accepts the list-of-dict JSON the Socrata endpoint returns. Each row must carry the
        date + non-commercial long/short columns. NET = long - short (number of contracts).
        Rows missing either leg are dropped (``_clean`` coerces + sorts + drops NaN)."""
        if not raw:
            return pd.Series(dtype="float64")
        df = pd.DataFrame(raw)
        if COL_DATE not in df or COL_LONG not in df or COL_SHORT not in df:
            return pd.Series(dtype="float64")
        idx = pd.to_datetime(df[COL_DATE])  # ISO-8601 -> Tuesday snapshot date
        longs = pd.to_numeric(df[COL_LONG], errors="coerce")
        shorts = pd.to_numeric(df[COL_SHORT], errors="coerce")
        net = longs - shorts
        return self._clean(pd.Series(net.values, index=idx))
