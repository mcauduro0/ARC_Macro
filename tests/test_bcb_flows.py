"""BCB external-flow catalog + month-end normalizer tests (pure, no network).

Uses a SYNTHETIC SGS JSON fixture (same shape the real endpoint returns:
[{"data": "dd/MM/yyyy", "valor": "..."}]) so CI never touches the wire.
"""

from __future__ import annotations

import pandas as pd
import pytest

from arc.data.adapters.bcb_flows import (
    FLOW_SERIES,
    FX_FLOW_NOTE,
    build_monthly_flow,
    flow_contracts,
    parse_flow,
    to_month_end,
)

# Synthetic SGS payload: BCB dates BPM6 monthly obs on the 1st of the reference month.
# Includes a comma decimal and a negative value (net outflow) to exercise parsing.
_RAW = [
    {"data": "01/01/2010", "valor": "1234.5"},
    {"data": "01/02/2010", "valor": "-678,9"},  # comma decimal + negative net flow
    {"data": "01/03/2010", "valor": "200.0"},
]


def test_flow_series_catalog_codes_and_units():
    by_name = {r["name"]: r for r in FLOW_SERIES}
    assert by_name["IDP_FLOW"]["sgs_code"] == "22885"
    assert by_name["PORTFOLIO_FLOW"]["sgs_code"] == "22924"
    for row in FLOW_SERIES:
        assert row["unit"] == "usd_mn"
        assert row["lag_days"] == 30


def test_flow_contracts_are_valid_bcb_sgs_monthly():
    contracts = {c.series_id: c for c in flow_contracts()}
    assert set(contracts) == {"IDP_FLOW", "PORTFOLIO_FLOW"}
    for c in contracts.values():
        assert c.source == "BCB_SGS"
        assert c.frequency == "M"
        assert c.publication_lag_days == 30
        assert c.valid_min < 0 < c.valid_max  # net flows can be negative
    assert contracts["IDP_FLOW"].source_code == "22885"
    assert contracts["PORTFOLIO_FLOW"].source_code == "22924"


def test_parse_flow_produces_month_end_series():
    s = parse_flow(_RAW)
    # month-end stamps (Jan/Feb/Mar 2010), values preserved incl. comma + negative
    assert list(s.index) == [
        pd.Timestamp("2010-01-31"),
        pd.Timestamp("2010-02-28"),
        pd.Timestamp("2010-03-31"),
    ]
    assert s.loc["2010-01-31"] == 1234.5
    assert s.loc["2010-02-28"] == -678.9  # comma decimal parsed, sign kept
    assert s.loc["2010-03-31"] == 200.0
    assert list(s.index) == sorted(s.index)


def test_to_month_end_collapses_duplicate_months_keeping_last():
    raw = pd.Series(
        [10.0, 11.0, 20.0],
        index=pd.to_datetime(["2010-01-01", "2010-01-15", "2010-02-01"]),
    )
    s = to_month_end(raw)
    assert s.loc["2010-01-31"] == 11.0  # last value within the month wins
    assert s.loc["2010-02-28"] == 20.0
    assert len(s) == 2


def test_parse_flow_empty():
    assert parse_flow([]).empty
    assert to_month_end(pd.Series(dtype="float64")).empty


def test_build_monthly_flow_delegates_fetch_and_normalizes(monkeypatch):
    """build_monthly_flow must NOT hit the network in CI: stub fetch_raw on the adapter."""
    from arc.data.adapters.bcb_sgs import BcbSgsAdapter

    captured = {}

    def fake_fetch_raw(self, contract, since=None):
        captured["source_code"] = contract.source_code
        captured["series_id"] = contract.series_id
        return _RAW

    monkeypatch.setattr(BcbSgsAdapter, "fetch_raw", fake_fetch_raw)
    s = build_monthly_flow("IDP_FLOW")
    assert captured["source_code"] == "22885"  # delegated with the right SGS code
    assert captured["series_id"] == "IDP_FLOW"
    assert s.loc["2010-02-28"] == -678.9
    assert list(s.index) == sorted(s.index)


def test_build_monthly_flow_unknown_name_raises():
    with pytest.raises(KeyError):
        build_monthly_flow("NOT_A_SERIES")


def test_fx_flow_documented_as_unavailable():
    # FX flow is intentionally excluded from the SGS-delegating catalog.
    assert "fluxo cambial" in FX_FLOW_NOTE.lower()
    assert all(r["name"] != "FX_FLOW" for r in FLOW_SERIES)
