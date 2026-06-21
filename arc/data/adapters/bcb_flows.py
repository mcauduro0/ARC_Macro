"""BCB external-flow series (BPM6 financial account) — the missing 'idp_flow' /
'portfolio_flow' inputs the engine wires but whose CSVs were absent.

These are *monthly* balance-of-payments flows published by the BCB under the BPM6
framework and exposed through the SAME public SGS endpoint the rest of the BCB data
uses (https://api.bcb.gov.br/dados/serie/bcdata.sgs.{code}/dados). This module is a
THIN catalog + month-end normalizer: it does NOT re-implement the HTTP/parse logic —
it delegates to ``BcbSgsAdapter.parse`` (which already handles BR dates + comma
decimals). Network stays lazy (only ``BcbSgsAdapter.fetch_raw`` touches the wire).

Series chosen (evidence: BCB Portal de Dados Abertos dataset titles/URLs):
  - IDP_FLOW       -> SGS 22885  "Investimentos diretos no país - IDP - mensal - líquido"
  - PORTFOLIO_FLOW -> SGS 22924  "Investimentos em carteira - passivos - mensal - líquido"
                      (the aggregate of equities + debt securities + funds, net)

Both are monthly, in USD millions (US$ milhões), BPM6, history from Jan/1995.
Net (líquido) is used so the engine's rolling-sum z-score reflects net inflows
(positive) vs outflows (negative) — the FX-relevant signal.

FX flow ("fluxo cambial contratado") is intentionally NOT included: the BCB does not
publish it as a stable SGS code — it is a separate weekly/monthly press release with
its own statistics file. See ``FX_FLOW_NOTE`` and the final report for the caveat.
"""

from __future__ import annotations

from typing import Any, Optional

import pandas as pd

from arc.contracts import SeriesContract
from arc.data.adapters.bcb_sgs import BcbSgsAdapter

# BPM6 monthly external-sector flows are published "up to four weeks after the reference
# period"; we floor the publication lag at 30 calendar days (same convention as the debt
# series in the catalog). The bitemporal store still prefers a true publish_ts when given.
_BPM6_LAG_DAYS = 30
_BPM6_UNIT = "usd_mn"  # US$ millions

# The catalog of flow series. Each row is the data-contract seed for one series.
# ``name`` is the engine-facing series_id (matches macro_risk_os_v2 load_series keys).
FLOW_SERIES: list[dict[str, Any]] = [
    {
        "name": "IDP_FLOW",
        "sgs_code": "22885",
        "unit": _BPM6_UNIT,
        "lag_days": _BPM6_LAG_DAYS,
        "description": "Foreign direct investment in Brazil (IDP), monthly net, USD mn (SGS 22885, BPM6)",
    },
    {
        "name": "PORTFOLIO_FLOW",
        "sgs_code": "22924",
        "unit": _BPM6_UNIT,
        "lag_days": _BPM6_LAG_DAYS,
        "description": (
            "Foreign portfolio investment liabilities (equities+debt+funds), monthly net, "
            "USD mn (SGS 22924, BPM6)"
        ),
    },
]

# Documented-but-unavailable: BCB FX flow ("fluxo cambial") has no stable SGS code.
FX_FLOW_NOTE = (
    "BCB 'fluxo cambial contratado' (weekly/monthly contracted FX flow) is NOT a SGS "
    "series; it is a standalone press release/statistics file. It cannot be fetched via "
    "the SGS endpoint, so it is excluded from FLOW_SERIES. If needed, a dedicated adapter "
    "must scrape the BCB FX-flow statistics page (out of scope for this SGS-delegating module)."
)


def flow_contracts() -> list[SeriesContract]:
    """Build the :class:`SeriesContract` for each flow series.

    Pure (no network). These can be merged into the master ``_CATALOG`` so the standard
    BcbSgsAdapter ingest path (``fetch`` -> publication-lag-stamped Observations) works.
    valid_min/valid_max are deliberately wide and symmetric: net BPM6 flows can be large
    and negative (capital flight) or positive (strong months); +/- 50_000 USD mn comfortably
    bounds Brazil's monthly history while still catching unit/parse blowups.
    """
    contracts: list[SeriesContract] = []
    for row in FLOW_SERIES:
        contracts.append(
            SeriesContract(
                series_id=row["name"],
                source="BCB_SGS",
                source_code=row["sgs_code"],
                frequency="M",
                unit=row["unit"],
                publication_lag_days=row["lag_days"],
                valid_min=-50_000.0,
                valid_max=50_000.0,
                allowed_revision_abs=5_000.0,
                license="BCB open data",
                description=row["description"],
            )
        )
    return contracts


def to_month_end(series: pd.Series) -> pd.Series:
    """Snap an event-time-indexed flow Series to month-end stamps.

    BCB returns BPM6 monthly observations dated on the FIRST day of the reference month
    (dd=01). The engine aligns everything to month-end (``to_monthly``), so we normalize
    here to the period's month-end timestamp and keep the LAST value per month (defensive
    against any intra-month duplicates). Pure; no network.
    """
    if series.empty:
        return pd.Series(dtype="float64")
    s = series.copy()
    s.index = pd.to_datetime(s.index)
    s = s.sort_index()
    # collapse to one value per calendar month, then stamp at month-end
    s = s.groupby(s.index.to_period("M")).last()
    s.index = s.index.to_timestamp(how="end").normalize()
    s.index.name = series.index.name
    return s


def parse_flow(raw: Any) -> pd.Series:
    """Parse a raw SGS payload into a month-end flow Series.

    Delegates the BR-date / comma-decimal parsing to ``BcbSgsAdapter.parse`` (single source
    of truth), then applies :func:`to_month_end`. Pure; takes already-fetched ``raw``."""
    parsed = BcbSgsAdapter().parse(raw)
    return to_month_end(parsed)


def build_monthly_flow(
    name: str,
    *,
    adapter: Optional[BcbSgsAdapter] = None,
    since=None,
) -> pd.Series:
    """Fetch + parse one flow series to a tidy month-end Series (USD mn).

    This is the only function that touches the network, and it does so lazily via the
    existing ``BcbSgsAdapter`` (which imports ``requests`` lazily). Returns an empty Series
    for an unknown ``name`` is NOT desired — we raise, to fail loud on a typo'd series id.
    """
    contract = _contract_by_name(name)
    a = adapter or BcbSgsAdapter()
    raw = a.fetch_raw(contract, since)
    return parse_flow(raw)


def _contract_by_name(name: str) -> SeriesContract:
    for c in flow_contracts():
        if c.series_id == name:
            return c
    have = [r["name"] for r in FLOW_SERIES]
    raise KeyError(f"no BCB flow series '{name}' (have: {have})")
