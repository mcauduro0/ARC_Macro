"""Series catalog — the data-contract registry (publication lag, source code, validity).

Seed of the catalog table in ARCHITECTURE_SOTA.md §4.1. Publication lags are in CALENDAR
days and reflect real Brazil/US release calendars — this is what makes ``as_of(t)`` refuse
to show a macro print before it was published (the #1 macro leakage fix). Lags here are
conservative defaults; the bitemporal store records the TRUE knowledge_time when a source
provides a publish timestamp, which always wins over this floor.
"""

from __future__ import annotations

from arc.contracts import SeriesContract

# series_id -> contract. Lags: market/price series ~1d (next-day confirmation); IPCA ~10d
# (released ~day 10 for prior month); Focus ~3d; debt/PIB ~30d; US CPI ~14d.
_CATALOG: dict[str, SeriesContract] = {
    s.series_id: s for s in [
        # --- BCB SGS (https://api.bcb.gov.br/dados/serie/bcdata.sgs.{code}/dados) ---
        SeriesContract(series_id="SELIC_TARGET", source="BCB_SGS", source_code="432", frequency="D",
                       unit="pct_aa", publication_lag_days=1, valid_min=0, valid_max=100,
                       license="BCB open data", description="Selic meta (SGS 432)"),
        SeriesContract(series_id="CDI", source="BCB_SGS", source_code="12", frequency="D",
                       unit="pct_day", publication_lag_days=1, valid_min=0, valid_max=5,
                       license="BCB open data", description="CDI/DI overnight (SGS 12)"),
        SeriesContract(series_id="USDBRL_PTAX", source="BCB_SGS", source_code="1", frequency="D",
                       unit="BRL", publication_lag_days=1, valid_min=0.5, valid_max=15,
                       license="BCB open data", description="USD/BRL PTAX venda (SGS 1)"),
        SeriesContract(series_id="IPCA_MOM", source="BCB_SGS", source_code="433", frequency="M",
                       unit="pct", publication_lag_days=10, valid_min=-2, valid_max=10,
                       allowed_revision_abs=0.5, license="BCB open data", description="IPCA m/m (SGS 433)"),
        SeriesContract(series_id="DIVIDA_BRUTA_PIB", source="BCB_SGS", source_code="13762", frequency="M",
                       unit="pct_gdp", publication_lag_days=30, valid_min=0, valid_max=200,
                       allowed_revision_abs=2.0, license="BCB open data", description="Gross debt/GDP (SGS 13762)"),
        # --- BCB Focus (Olinda Expectativas) ---
        SeriesContract(series_id="FOCUS_IPCA_12M", source="BCB_FOCUS", source_code="IPCA", frequency="D",
                       unit="pct", publication_lag_days=1, valid_min=0, valid_max=30,
                       license="BCB open data", description="Focus 12m-ahead IPCA expectation (median)"),
        # --- FRED (https://api.stlouisfed.org/fred) ---
        SeriesContract(series_id="UST10Y", source="FRED", source_code="DGS10", frequency="D",
                       unit="pct", publication_lag_days=1, valid_min=-2, valid_max=25,
                       license="FRED terms", description="US 10y Treasury (DGS10)"),
        SeriesContract(series_id="UST2Y", source="FRED", source_code="DGS2", frequency="D",
                       unit="pct", publication_lag_days=1, valid_min=-2, valid_max=25,
                       license="FRED terms", description="US 2y Treasury (DGS2)"),
        SeriesContract(series_id="US_CPI", source="FRED", source_code="CPIAUCSL", frequency="M",
                       unit="index", publication_lag_days=14, valid_min=0,
                       license="FRED terms", description="US CPI (CPIAUCSL)"),
    ]
}


def get_contract(series_id: str) -> SeriesContract:
    if series_id not in _CATALOG:
        raise KeyError(f"no contract for series '{series_id}' (have: {sorted(_CATALOG)})")
    return _CATALOG[series_id]


def all_contracts() -> list[SeriesContract]:
    return list(_CATALOG.values())


def by_source(source: str) -> list[SeriesContract]:
    return [c for c in _CATALOG.values() if c.source == source]
