"""IPEADATA fallback parse/provenance tests for the BCB external-flow adapter (pure, no network).

Uses SYNTHETIC odata4-shaped fixtures (same shape the real IPEADATA endpoints return:
Metadados -> one entity with SERCODIGO/SERNOME/FNTSIGLA/FNTNOME/PERNOME/UNINOME/MULNOME;
ValoresSerie -> {'value': [{'VALDATA': ISO8601, 'VALVALOR': float}, ...]}) so CI never
touches the wire. Asserts (a) a confirmed BCB BPM6 match builds a month-end series with
provenance, and (b) a wrong-source / wrong-name series is REJECTED (raises) rather than
silently substituted.
"""

from __future__ import annotations

import pandas as pd
import pytest

from arc.data.adapters import bcb_flows
from arc.data.adapters.bcb_flows import (
    _parse_ipeadata_values,
    _verify_ipeadata_metadata,
    fetch_flow_ipeadata,
)

# --- Fixtures: real-shaped IPEADATA payloads (captured from the odata4 endpoints) -------

# Confirmed BCB BPM6 IDP metadata (Bacen source, "investimento direto pais - saldo").
_META_IDP_OK = {
    "SERCODIGO": "BPAG12_IDP12",
    "SERNOME": "Balanco de pagamentos - investimento direto pais - saldo",
    "FNTSIGLA": "Bacen/BP (BPM6)",
    "FNTNOME": "Banco Central do Brasil, Balanco de Pagamentos (BPM6) (BCB / BP (BPM6))",
    "FNTURL": "http://www.bcb.gov.br",
    "PERNOME": "Mensal",
    "UNINOME": "US$",
    "MULNOME": "milhoes",
    "SERSTATUS": "A",
}

# Confirmed BCB BPM6 portfolio-liabilities metadata ("investimento carteira - passivos - saldo").
_META_PORTFOLIO_OK = {
    "SERCODIGO": "BPAG12_ICP12",
    "SERNOME": "Balanco de pagamentos - investimento carteira - passivos - saldo",
    "FNTSIGLA": "Bacen/BP (BPM6)",
    "FNTNOME": "Banco Central do Brasil, Balanco de Pagamentos (BPM6) (BCB / BP (BPM6))",
    "FNTURL": "http://www.bcb.gov.br",
    "PERNOME": "Mensal",
    "UNINOME": "US$",
    "MULNOME": "milhoes",
    "SERSTATUS": "I",
}

# Wrong SOURCE: same-looking name but the FONTE is NOT Bacen/BCB -> must be rejected.
_META_WRONG_SOURCE = {
    **_META_IDP_OK,
    "FNTSIGLA": "IBGE",
    "FNTNOME": "Instituto Brasileiro de Geografia e Estatistica",
    "FNTURL": "http://www.ibge.gov.br",
}

# Wrong NAME/concept: Bacen source but it is the *exterior* (assets) series, not IDP-into-Brazil.
_META_WRONG_NAME = {
    **_META_IDP_OK,
    "SERCODIGO": "BPAG12_IDE12",
    "SERNOME": "Balanco de pagamentos - investimento direto exterior - saldo",
}

# Values payload: dated on the 1st of the month (like SGS), with a comma/neg exercised via float.
_VALS = {
    "value": [
        {"SERCODIGO": "BPAG12_IDP12", "VALDATA": "2010-01-01T00:00:00-02:00", "VALVALOR": 1234.5},
        {"SERCODIGO": "BPAG12_IDP12", "VALDATA": "2010-02-01T00:00:00-02:00", "VALVALOR": -678.9},
        {"SERCODIGO": "BPAG12_IDP12", "VALDATA": "2010-03-01T00:00:00-03:00", "VALVALOR": 200.0},
    ]
}


def test_parse_ipeadata_values_produces_month_end_series():
    s = _parse_ipeadata_values(_VALS["value"])
    assert list(s.index) == [
        pd.Timestamp("2010-01-31"),
        pd.Timestamp("2010-02-28"),
        pd.Timestamp("2010-03-31"),
    ]
    assert s.loc["2010-01-31"] == 1234.5
    assert s.loc["2010-02-28"] == -678.9  # negative net flow preserved
    assert s.loc["2010-03-31"] == 200.0
    assert list(s.index) == sorted(s.index)


def test_parse_ipeadata_values_empty():
    assert _parse_ipeadata_values([]).empty


def test_verify_metadata_accepts_confirmed_bcb_bpm6_idp():
    prov = _verify_ipeadata_metadata("IDP_FLOW", _META_IDP_OK)
    assert prov["verified"] is True
    assert prov["route"] == "IPEADATA"
    assert prov["sercodigo"] == "BPAG12_IDP12"
    assert prov["fonte"] == "Bacen/BP (BPM6)"
    assert prov["periodicidade"] == "Mensal"
    assert prov["unidade"] == "US$ milhoes"  # UNINOME + MULNOME joined
    assert prov["sgs_equivalent"] == "22885"


def test_verify_metadata_accepts_confirmed_portfolio_liabilities():
    prov = _verify_ipeadata_metadata("PORTFOLIO_FLOW", _META_PORTFOLIO_OK)
    assert prov["sercodigo"] == "BPAG12_ICP12"
    assert prov["sgs_equivalent"] == "22924"
    assert prov["verified"] is True


def test_verify_metadata_rejects_wrong_source():
    # Right-looking name, but FONTE is IBGE not Bacen -> never substitute.
    with pytest.raises(ValueError, match="source not confirmed"):
        _verify_ipeadata_metadata("IDP_FLOW", _META_WRONG_SOURCE)


def test_verify_metadata_rejects_wrong_name_concept():
    # Bacen source, but it is the *exterior* (assets-abroad) series, not IDP-into-Brazil.
    with pytest.raises(ValueError):
        _verify_ipeadata_metadata("IDP_FLOW", _META_WRONG_NAME)


def test_verify_metadata_rejects_portfolio_assets_for_liabilities_request():
    # Asking for PORTFOLIO_FLOW (passivos) but handed the *ativos* mirror -> reject.
    meta_assets = {
        **_META_PORTFOLIO_OK,
        "SERCODIGO": "BPAG_ICA",
        "SERNOME": "Balanco de pagamentos - investimento carteira - ativos - saldo",
    }
    with pytest.raises(ValueError):
        _verify_ipeadata_metadata("PORTFOLIO_FLOW", meta_assets)


def test_fetch_flow_ipeadata_unknown_name_raises():
    with pytest.raises(KeyError):
        fetch_flow_ipeadata("NOT_A_FLOW")


def test_fetch_flow_ipeadata_happy_path_mocks_network(monkeypatch):
    """End-to-end fallback with the wire stubbed: confirms match -> month-end series + provenance."""

    def fake_get(url, *, timeout):
        if "Metadados" in url:
            return {"value": [_META_IDP_OK]}  # odata collection shape
        if "ValoresSerie" in url:
            return _VALS
        raise AssertionError(f"unexpected URL {url}")

    monkeypatch.setattr(bcb_flows, "_ipeadata_get", fake_get)
    s, prov = fetch_flow_ipeadata("IDP_FLOW")
    assert s.name == "IDP_FLOW"
    assert s.loc["2010-02-28"] == -678.9
    assert list(s.index) == sorted(s.index)
    assert prov["route"] == "IPEADATA"
    assert prov["sercodigo"] == "BPAG12_IDP12"
    assert prov["n"] == 3
    assert prov["range"] == "2010-01-31..2010-03-31"


def test_fetch_flow_ipeadata_rejects_when_source_unconfirmed(monkeypatch):
    """If metadata is a wrong-source series, the whole fetch must RAISE (no substitution)."""

    def fake_get(url, *, timeout):
        if "Metadados" in url:
            return {"value": [_META_WRONG_SOURCE]}
        if "ValoresSerie" in url:
            return _VALS
        raise AssertionError(f"unexpected URL {url}")

    monkeypatch.setattr(bcb_flows, "_ipeadata_get", fake_get)
    with pytest.raises(ValueError):
        fetch_flow_ipeadata("IDP_FLOW")


def test_fetch_flow_ipeadata_rejects_confirmed_but_empty_values(monkeypatch):
    """A confirmed match with an EMPTY value series is a failure, not a silent empty adopt."""

    def fake_get(url, *, timeout):
        if "Metadados" in url:
            return {"value": [_META_IDP_OK]}
        if "ValoresSerie" in url:
            return {"value": []}
        raise AssertionError(f"unexpected URL {url}")

    monkeypatch.setattr(bcb_flows, "_ipeadata_get", fake_get)
    with pytest.raises(ValueError, match="could not confirm an IPEADATA BPM6 match"):
        fetch_flow_ipeadata("IDP_FLOW")
