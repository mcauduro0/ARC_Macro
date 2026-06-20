"""Publication-lag registry for the legacy engine's CSV series (Phase 3.2 bridge).

The monolith loads ~44 series by CSV basename via ``macro_risk_os_v2.load_series(name)``. To route
those reads through the bitemporal store we need, per basename, the **publication lag in calendar
days** so each value's ``knowledge_time = event_time + lag`` and ``as_of(t)`` refuses to show a print
before it was released. Market/price series confirm next day (1d); macro releases carry their real
Brazil/US calendar lags; annual fundamentals lag ~a year.

These are conservative floors consistent with ``arc/data/catalog.py`` (IPCA 10d, debt 30d, US CPI
14d). The bitemporal store still records a TRUE publish timestamp when a real adapter provides one;
this floor only governs the CSV bridge. Anything not listed defaults to 1 day.
"""

from __future__ import annotations

from arc.contracts import Frequency, SeriesContract

DEFAULT_LAG_DAYS = 1

# CSV basename (the `name` passed to load_series) -> publication lag in calendar days.
ENGINE_LAG_DAYS: dict[str, int] = {
    # Brazil macro (reference month, released weeks later)
    "IPCA_MONTHLY": 10,        # IPCA m/m released ~day 10 of M+1
    "IPCA_12M": 10,
    "DIVIDA_BRUTA_PIB": 30,    # BCB fiscal statistics ~end of M+1
    "PRIMARY_BALANCE": 30,
    "BOP_CURRENT": 30,         # BCB external accounts ~end of M+1
    "TERMS_OF_TRADE": 30,
    "IBC_BR": 45,              # IBC-Br activity index ~mid M+2
    "REER_BIS": 35,            # BIS REER ~M+1
    "REER_BCB": 35,
    # Annual structural fundamentals (released with ~1y lag)
    "PPP_FACTOR": 365,
    "GDP_PER_CAPITA": 365,
    "CURRENT_ACCOUNT": 365,
    "TRADE_OPENNESS": 365,
}

# Coarse frequency hint (only affects the synthesized contract, not as_of math).
_ENGINE_FREQ: dict[str, Frequency] = {
    "IPCA_MONTHLY": "M", "IPCA_12M": "M", "DIVIDA_BRUTA_PIB": "M", "PRIMARY_BALANCE": "M",
    "BOP_CURRENT": "M", "TERMS_OF_TRADE": "M", "IBC_BR": "M", "REER_BIS": "M", "REER_BCB": "M",
    "PPP_FACTOR": "A", "GDP_PER_CAPITA": "A", "CURRENT_ACCOUNT": "A", "TRADE_OPENNESS": "A",
}


def lag_days_for(name: str) -> int:
    """Publication lag (calendar days) for an engine CSV basename; 1 day if unlisted (market data)."""
    return ENGINE_LAG_DAYS.get(name, DEFAULT_LAG_DAYS)


def contract_for(name: str) -> SeriesContract:
    """Synthesize a minimal SeriesContract for a legacy CSV series, carrying its publication lag.
    Used by the CSV->store migration; real per-source contracts (catalog.py) supersede these as
    adapters take over."""
    return SeriesContract(
        series_id=name,
        source="CSV_BRIDGE",
        frequency=_ENGINE_FREQ.get(name, "D"),
        unit="native",
        publication_lag_days=lag_days_for(name),
        description=f"legacy engine CSV series '{name}' (publication lag {lag_days_for(name)}d)",
    )
