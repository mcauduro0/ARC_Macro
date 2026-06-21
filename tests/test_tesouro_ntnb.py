"""Tesouro NTN-B adapter tests (pure, no network).

Feeds a small SYNTHETIC CSV string shaped exactly like the real Tesouro Transparente
PrecoTaxaTesouroDireto.csv (";" sep, "," decimal, dd/MM/yyyy dates) to the pure ``parse``
method and asserts the constant-maturity ~5y/~10y real yields and month-end behaviour.
"""

from __future__ import annotations

import pandas as pd

from arc.data.adapters.tesouro_ntnb import TENORS_YEARS, TesouroNtnbAdapter

# Header verbatim from the live endpoint. Two quote (base) dates in the same month so we
# can check month-end picks the LAST quote. On each base date we provide NTN-B (IPCA+)
# bonds maturing ~5y and ~10y out, plus a non-IPCA bond that MUST be ignored.
HEADER = (
    "Tipo Titulo;Data Vencimento;Data Base;Taxa Compra Manha;Taxa Venda Manha;"
    "PU Compra Manha;PU Venda Manha;PU Base Manha"
)
# base 15/01/2020: 5y bond (15/01/2025) yld 3,00 ; 10y bond (15/01/2030) yld 4,00
# base 31/01/2020: 5y bond yld 3,50 ; 10y bond yld 4,50  -> month-end should take these
# plus an IGPM bond (must be excluded) and a coupon NTN-B exactly at 5y on 15/01.
FIXTURE = "\n".join(
    [
        HEADER,
        "Tesouro IPCA+;15/01/2025;15/01/2020;2,90;3,00;1000,00;1000,00;1000,00",
        "Tesouro IPCA+;15/01/2030;15/01/2020;3,90;4,00;900,00;900,00;900,00",
        "Tesouro IGPM+ com Juros Semestrais;15/01/2030;15/01/2020;9,90;9,99;1,0;1,0;1,0",
        "Tesouro IPCA+ com Juros Semestrais;15/01/2025;31/01/2020;3,40;3,50;1,0;1,0;1,0",
        "Tesouro IPCA+ com Juros Semestrais;15/01/2030;31/01/2020;4,40;4,50;1,0;1,0;1,0",
        "Tesouro Prefixado;01/01/2025;31/01/2020;7,00;7,10;1,0;1,0;1,0",
    ]
)


def _adapter() -> TesouroNtnbAdapter:
    return TesouroNtnbAdapter()


def test_parse_returns_tenor_columns_and_month_end_index():
    out = _adapter().parse(FIXTURE)
    assert list(out.columns) == sorted(TENORS_YEARS)  # NTNB_REAL_10Y, NTNB_REAL_5Y
    # one month -> one month-end row (Jan 2020), index is month-end.
    assert len(out) == 1
    assert out.index[0] == pd.Timestamp("2020-01-31")


def test_month_end_takes_last_quote_of_month():
    out = _adapter().parse(FIXTURE)
    row = out.loc["2020-01-31"]
    # last quote in Jan is the 31/01 base date; 5y bond is ~4.96y (interp), 10y ~9.96y.
    assert abs(row["NTNB_REAL_5Y"] - 3.50) < 0.05
    assert abs(row["NTNB_REAL_10Y"] - 4.50) < 0.05


def test_daily_constant_maturity_uses_bonds_quoted_that_day():
    cm = _adapter().constant_maturity_daily(FIXTURE)
    # 15/01/2020 quote: bonds maturing 15/01/2025 (~5.0y) and 15/01/2030 (~10.0y).
    r = cm.loc["2020-01-15"]
    assert abs(r["NTNB_REAL_5Y"] - 3.00) < 0.02
    assert abs(r["NTNB_REAL_10Y"] - 4.00) < 0.02  # nearest (~10y) within tol -> flat


def test_linear_interpolation_between_brackets():
    # bonds at ~2.5y (2,00%) and ~7.5y (4,00%); target 5y -> midpoint 3,00%.
    csv = "\n".join(
        [
            HEADER,
            "Tesouro IPCA+;01/07/2022;01/01/2020;1,90;2,00;1,0;1,0;1,0",  # ~2.5y
            "Tesouro IPCA+;01/07/2027;01/01/2020;3,90;4,00;1,0;1,0;1,0",  # ~7.5y
        ]
    )
    cm = _adapter().constant_maturity_daily(csv)
    r = cm.loc["2020-01-01"]
    assert abs(r["NTNB_REAL_5Y"] - 3.00) < 0.02  # interpolated midpoint
    # 10y target: nearest bond (~7.5y) is ~2.5y away, beyond extrap tol -> NaN (no fab).
    assert pd.isna(r["NTNB_REAL_10Y"])


def test_excludes_non_ntnb_bond_types():
    cm = _adapter().constant_maturity_daily(FIXTURE)
    # the IGPM 9,99 and Prefixado 7,10 rows must never leak into the real-yield curve.
    assert (cm["NTNB_REAL_10Y"].dropna() < 9.0).all()
    assert (cm["NTNB_REAL_5Y"].dropna() < 7.0).all()


def test_far_tenor_returns_nan_not_fabricated():
    # only a 2y bond available; 10y is > extrap tol away -> NaN, never invented.
    csv = "\n".join(
        [
            HEADER,
            "Tesouro IPCA+;01/01/2022;01/01/2020;1,90;2,00;1,0;1,0;1,0",
        ]
    )
    cm = _adapter().constant_maturity_daily(csv)
    r = cm.loc["2020-01-01"]
    assert pd.isna(r["NTNB_REAL_10Y"])  # 8y gap, beyond tolerance


def test_parse_empty_and_no_ntnb_rows():
    a = _adapter()
    assert a.parse("").empty or list(a.parse("").columns) == sorted(TENORS_YEARS)
    only_header = HEADER + "\nTesouro Selic;01/03/2025;01/01/2020;0,01;0,02;1,0;1,0;1,0"
    out = a.parse(only_header)
    assert out.empty


def test_fetch_emits_observations_with_publication_lag(monkeypatch):
    """fetch() selects the contract's tenor column and stamps knowledge_time via lag."""
    from arc.contracts import SeriesContract

    a = _adapter()
    monkeypatch.setattr(a, "fetch_raw", lambda contract, since=None: FIXTURE)
    contract = SeriesContract(
        series_id="NTNB_REAL_5Y", source="TESOURO_TD", source_code="Tesouro IPCA+",
        frequency="M", unit="pct", publication_lag_days=1, valid_min=-5, valid_max=20,
        license="Tesouro Transparente open data",
    )
    obs = a.fetch(contract)
    assert len(obs) == 1
    o = obs[0]
    assert o.series_id == "NTNB_REAL_5Y" and abs(o.value - 3.50) < 0.05 and o.source == "TESOURO_TD"
    assert pd.Timestamp(o.event_time) == pd.Timestamp("2020-01-31")
    assert pd.Timestamp(o.knowledge_time) == pd.Timestamp("2020-02-01")  # +1 day lag


def test_fetch_rejects_unknown_tenor(monkeypatch):
    from arc.contracts import SeriesContract

    a = _adapter()
    monkeypatch.setattr(a, "fetch_raw", lambda contract, since=None: FIXTURE)
    bad = SeriesContract(
        series_id="NTNB_REAL_30Y", source="TESOURO_TD", frequency="M", unit="pct",
        publication_lag_days=1,
    )
    try:
        a.fetch(bad)
        assert False, "expected ValueError for unknown tenor"
    except ValueError as e:
        assert "NTNB_REAL_30Y" in str(e)
