"""Tesouro Transparente NTN-B (inflation-linked, IPCA+) real-yield HISTORY adapter.

Why: the legacy NTNB/breakeven CSVs hold a single 2024 snapshot, which blocks the
real-curve edge. This adapter pulls the FULL daily history of Tesouro Direto offered
rates and derives constant-maturity ~5y and ~10y NTN-B REAL yields (the buyer's "Taxa
Venda Manha", i.e. the rate at which the investor buys the bond). Breakevens are then
nominal_yield - real_yield downstream (not computed here; this adapter stays single-source
and pure, mirroring the no-merge rule in arc/data/adapters/__init__.py).

Endpoint (public, no key, updated daily, history since Dec-2004):
    https://www.tesourotransparente.gov.br/ckan/dataset/
      df56aa42-484a-4a59-8184-7676580c81e3/resource/
      796d2059-14e9-44e3-80c9-2d9e30b405c1/download/PrecoTaxaTesouroDireto.csv

Response (text/csv, ~50-80 MB full history):
    Tipo Titulo;Data Vencimento;Data Base;Taxa Compra Manha;Taxa Venda Manha;PU Compra Manha;PU Venda Manha;PU Base Manha
    Tesouro IPCA+ com Juros Semestrais;15/08/2050;26/10/2007;6,81;6,89;...
  - delimiter ';', decimal ',', dates dd/MM/yyyy
  - "Data Base" = quote date (event_time), "Data Vencimento" = bond maturity.
  - NTN-B "Tipo Titulo" values: "Tesouro IPCA+" and "Tesouro IPCA+ com Juros Semestrais".
  - "Taxa Venda Manha" is the annual REAL yield (% a.a., IPCA+), the figure we expose.

Constant-maturity construction (per quote date):
  For each base date, among IPCA+ bonds, find the maturity bracketing the target tenor
  (5y / 10y from that base date) and LINEARLY INTERPOLATE the real yield in
  time-to-maturity. If the tenor is outside the available maturity range we take the
  nearest bond (flat extrapolation) only when within ``extrap_tol_years``; otherwise NaN.
  This is point-in-time clean: each quote uses only bonds quoted ON that same date.

The pure ``parse(raw)`` does all of the above; ``fetch_raw`` is the only network call.
"""

from __future__ import annotations

import io
from datetime import datetime
from typing import Any, Optional

import pandas as pd

from arc.contracts import SeriesContract
from arc.data.adapters.base import Adapter

CSV_URL = (
    "https://www.tesourotransparente.gov.br/ckan/dataset/"
    "df56aa42-484a-4a59-8184-7676580c81e3/resource/"
    "796d2059-14e9-44e3-80c9-2d9e30b405c1/download/PrecoTaxaTesouroDireto.csv"
)

# NTN-B (IPCA-linked) instrument labels in the "Tipo Titulo" column.
_NTNB_TYPES = ("Tesouro IPCA+", "Tesouro IPCA+ com Juros Semestrais")

# series_id -> target constant maturity in years.
TENORS_YEARS: dict[str, float] = {"NTNB_REAL_5Y": 5.0, "NTNB_REAL_10Y": 10.0}

_DAYS_PER_YEAR = 365.25


class TesouroNtnbAdapter(Adapter):
    """Tesouro Direto NTN-B real-yield history -> constant-maturity month-end series.

    ``parse`` returns a *wide* DataFrame keyed by ``TENORS_YEARS`` (one column per tenor)
    indexed by month-end event_time. ``fetch(contract, ...)`` selects the single column
    matching ``contract.series_id`` and emits bitemporal Observations (lag applied by the
    base class), so each catalog series is fetched independently.
    """

    source = "TESOURO_TD"

    def __init__(self, timeout: float = 60.0, extrap_tol_years: float = 1.5) -> None:
        self.timeout = timeout
        # max distance (in years) between target tenor and nearest available maturity
        # for which we accept flat extrapolation; beyond this -> NaN (no fabrication).
        self.extrap_tol_years = extrap_tol_years

    # --- network (lazy) ---
    def fetch_raw(self, contract: SeriesContract, since: Optional[datetime] = None) -> Any:
        import requests  # lazy: keeps module import light for tests/CI

        r = requests.get(CSV_URL, timeout=self.timeout)
        r.raise_for_status()
        r.encoding = r.encoding or "latin-1"
        return r.text

    # --- pure parse ---
    def parse(self, raw: Any) -> pd.DataFrame:
        """CSV text -> wide month-end DataFrame of constant-maturity NTN-B real yields.

        Columns == sorted(TENORS_YEARS); index == month-end Timestamps.
        Pure: no network, deterministic, NaN where a tenor is not derivable.
        """
        cm = self.constant_maturity_daily(raw)
        if cm.empty:
            return pd.DataFrame(columns=sorted(TENORS_YEARS))
        # month-end: last available quote in each calendar month per column.
        monthly = cm.resample("ME").last()
        return monthly.dropna(how="all").sort_index()

    # --- helpers (pure) ---
    def constant_maturity_daily(self, raw: Any) -> pd.DataFrame:
        """All quote dates -> daily constant-maturity real yields (wide). Pure."""
        df = self._read(raw)
        if df.empty:
            return pd.DataFrame(columns=sorted(TENORS_YEARS))
        cols = {}
        for sid, tenor in sorted(TENORS_YEARS.items()):
            cols[sid] = df.groupby("base").apply(
                lambda g, t=tenor: self._interp_one(g, t), include_groups=False
            )
        out = pd.DataFrame(cols)
        out.index = pd.to_datetime(out.index)
        return out.sort_index()

    def _read(self, raw: Any) -> pd.DataFrame:
        """CSV text/bytes -> tidy long frame [base, maturity, ttm_years, real_yield]."""
        empty = pd.DataFrame(columns=["base", "maturity", "ttm_years", "real_yield"])
        if raw is None:
            return empty
        if isinstance(raw, bytes):
            raw = raw.decode("latin-1")
        if not str(raw).strip():
            return empty
        df = pd.read_csv(
            io.StringIO(raw),
            sep=";",
            dtype=str,
            usecols=["Tipo Titulo", "Data Vencimento", "Data Base", "Taxa Venda Manha"],
        )
        df = df[df["Tipo Titulo"].isin(_NTNB_TYPES)].copy()
        if df.empty:
            return pd.DataFrame(columns=["base", "maturity", "ttm_years", "real_yield"])
        base = pd.to_datetime(df["Data Base"], format="%d/%m/%Y", errors="coerce")
        mat = pd.to_datetime(df["Data Vencimento"], format="%d/%m/%Y", errors="coerce")
        yld = pd.to_numeric(
            df["Taxa Venda Manha"].str.replace(",", ".", regex=False), errors="coerce"
        )
        out = pd.DataFrame(
            {
                "base": base,
                "maturity": mat,
                "ttm_years": (mat - base).dt.days / _DAYS_PER_YEAR,
                "real_yield": yld,
            }
        ).dropna(subset=["base", "maturity", "real_yield"])
        # only forward-looking maturities (drop matured / same-day rows).
        return out[out["ttm_years"] > 0.0].reset_index(drop=True)

    def _interp_one(self, group: pd.DataFrame, target: float) -> float:
        """Linear-in-maturity interpolation of real yield at ``target`` years for one
        quote date. Bracketing maturities -> interpolate; else nearest within tol -> flat;
        else NaN. Pure, deterministic."""
        g = group.dropna(subset=["ttm_years", "real_yield"]).sort_values("ttm_years")
        if g.empty:
            return float("nan")
        ttm = g["ttm_years"].to_numpy()
        y = g["real_yield"].to_numpy()
        # exact / bracketed
        below = ttm <= target
        above = ttm >= target
        if below.any() and above.any():
            lo_i = int(below.nonzero()[0][-1])
            hi_i = int(above.nonzero()[0][0])
            if lo_i == hi_i:
                return float(y[lo_i])
            t0, t1 = ttm[lo_i], ttm[hi_i]
            y0, y1 = y[lo_i], y[hi_i]
            w = (target - t0) / (t1 - t0)
            return float(y0 + w * (y1 - y0))
        # extrapolation: nearest endpoint if within tolerance, else NaN.
        nearest_i = int((abs(ttm - target)).argmin())
        if abs(ttm[nearest_i] - target) <= self.extrap_tol_years:
            return float(y[nearest_i])
        return float("nan")

    # --- bitemporal emit: one catalog series at a time ---
    def fetch(self, contract: SeriesContract, since: Optional[datetime] = None, *,
              ingest_run_id: Optional[str] = None, publish_ts: Optional[datetime] = None):
        raw = self.fetch_raw(contract, since)
        wide = self.parse(raw)
        if contract.series_id not in wide.columns:
            raise ValueError(
                f"{contract.series_id}: not a Tesouro NTN-B tenor "
                f"(have {sorted(wide.columns)})"
            )
        s = wide[contract.series_id].dropna()
        if since is not None:
            s = s[s.index >= pd.Timestamp(since)]
        from arc.data.observation import observations_from_series

        return observations_from_series(
            s, contract, source=self.source, ingest_run_id=ingest_run_id, publish_ts=publish_ts
        )
