"""Route-decision tests for scripts/collect_flows.py (pure, NO network).

``route_flow`` imports the two adapter calls (``build_monthly_flow``, ``fetch_flow_ipeadata``)
from ``arc.data.adapters.bcb_flows`` INSIDE the function, so we monkeypatch them on that
module to fake SGS up / down / both-down. CI never touches the wire. Mirrors the synthetic-
fixture style of tests/test_bcb_flows*.py.

Contract under test:
  * SGS up    -> route == "SGS", IPEADATA NOT called, the SGS series adopted.
  * SGS down, IPEADATA confirms -> route == "IPEADATA", the IPEADATA series adopted.
  * BOTH down -> route == "FAILED", series is None, honest reason recorded (no fabrication).
"""

from __future__ import annotations

import importlib

import pandas as pd
import pytest

from arc.data.adapters import bcb_flows

collect_flows = importlib.import_module("scripts.collect_flows")
route_flow = collect_flows.route_flow

# Synthetic confirmed-match series the fakes return (month-end indexed, like the real path).
_SGS_SERIES = pd.Series(
    [1234.5, -678.9, 200.0],
    index=pd.to_datetime(["2010-01-31", "2010-02-28", "2010-03-31"]),
    name="IDP_FLOW",
)
_IPEA_SERIES = pd.Series(
    [111.0, 222.0],
    index=pd.to_datetime(["2010-01-31", "2010-02-28"]),
    name="IDP_FLOW",
)
_IPEA_PROV = {
    "route": "IPEADATA",
    "sercodigo": "BPAG12_IDP12",
    "fonte": "Bacen/BP (BPM6)",
    "periodicidade": "Mensal",
    "unidade": "US$ milhoes",
    "sgs_equivalent": "22885",
    "verified": True,
}


def _fake_sgs_up(name, **kwargs):
    """SGS healthy: build_monthly_flow returns a parsed series."""
    return _SGS_SERIES


def _fake_sgs_down(name, **kwargs):
    """SGS down: build_monthly_flow raises (e.g. the observed 502 on api.bcb.gov.br)."""
    raise RuntimeError("502 Server Error: Bad Gateway for url api.bcb.gov.br")


def _fake_ipea_ok(name, **kwargs):
    """IPEADATA confirms the BPM6 match -> (series, provenance)."""
    return _IPEA_SERIES, dict(_IPEA_PROV)


def _fake_ipea_down(name, **kwargs):
    """IPEADATA also unavailable / unconfirmable -> raises (never substitutes)."""
    raise ValueError("IDP_FLOW: could not confirm an IPEADATA BPM6 match; not substituting")


def test_route_sgs_up_uses_canonical_and_skips_ipeadata(monkeypatch):
    """SGS up -> route == 'SGS', and fetch_flow_ipeadata is NEVER called."""
    ipea_calls = {"n": 0}

    def _spy_ipea(name, **kwargs):
        ipea_calls["n"] += 1
        return _IPEA_SERIES, dict(_IPEA_PROV)

    monkeypatch.setattr(bcb_flows, "build_monthly_flow", _fake_sgs_up)
    monkeypatch.setattr(bcb_flows, "fetch_flow_ipeadata", _spy_ipea)

    series, route, provenance = route_flow("IDP_FLOW")

    assert route == "SGS"
    assert ipea_calls["n"] == 0  # canonical source short-circuits the fallback
    assert series is not None and series.equals(_SGS_SERIES)
    assert "SGS" in provenance and "primary" in provenance


def test_route_sgs_down_falls_back_to_confirmed_ipeadata(monkeypatch):
    """SGS down but IPEADATA confirms -> route == 'IPEADATA', the IPEADATA series adopted."""
    monkeypatch.setattr(bcb_flows, "build_monthly_flow", _fake_sgs_down)
    monkeypatch.setattr(bcb_flows, "fetch_flow_ipeadata", _fake_ipea_ok)

    series, route, provenance = route_flow("IDP_FLOW")

    assert route == "IPEADATA"
    assert series is not None and series.equals(_IPEA_SERIES)
    assert "IPEADATA BPAG12_IDP12" in provenance
    assert "SGS down" in provenance  # the down reason is recorded for observability
    assert "==SGS 22885" in provenance


def test_route_both_down_fails_without_fabrication(monkeypatch):
    """BOTH routes down -> route == 'FAILED', NO series, honest reason captured."""
    monkeypatch.setattr(bcb_flows, "build_monthly_flow", _fake_sgs_down)
    monkeypatch.setattr(bcb_flows, "fetch_flow_ipeadata", _fake_ipea_down)

    series, route, provenance = route_flow("IDP_FLOW")

    assert route == "FAILED"
    assert series is None  # nothing fabricated, nothing persisted by the caller
    assert "SGS [" in provenance  # SGS failure surfaced...
    assert "IPEADATA [" in provenance  # ...and the IPEADATA failure too
    assert "could not confirm" in provenance


def test_route_forced_sgs_does_not_fall_back(monkeypatch):
    """--source sgs: SGS down -> FAILED, and IPEADATA is NEVER consulted."""
    ipea_calls = {"n": 0}

    def _spy_ipea(name, **kwargs):
        ipea_calls["n"] += 1
        return _IPEA_SERIES, dict(_IPEA_PROV)

    monkeypatch.setattr(bcb_flows, "build_monthly_flow", _fake_sgs_down)
    monkeypatch.setattr(bcb_flows, "fetch_flow_ipeadata", _spy_ipea)

    series, route, provenance = route_flow("IDP_FLOW", source="sgs")

    assert route == "FAILED"
    assert series is None
    assert ipea_calls["n"] == 0  # forced-canonical never touches the fallback
    assert "SGS forced but down" in provenance


def test_route_forced_ipeadata_skips_sgs(monkeypatch):
    """--source ipeadata: SGS is NEVER attempted; IPEADATA route taken directly."""
    sgs_calls = {"n": 0}

    def _spy_sgs(name, **kwargs):
        sgs_calls["n"] += 1
        return _SGS_SERIES

    monkeypatch.setattr(bcb_flows, "build_monthly_flow", _spy_sgs)
    monkeypatch.setattr(bcb_flows, "fetch_flow_ipeadata", _fake_ipea_ok)

    series, route, provenance = route_flow("IDP_FLOW", source="ipeadata")

    assert route == "IPEADATA"
    assert sgs_calls["n"] == 0  # canonical route skipped when explicitly forced to fallback
    assert series is not None and series.equals(_IPEA_SERIES)
    assert "SGS down" not in provenance  # no SGS attempt -> no down-note


def test_route_unknown_source_raises():
    with pytest.raises(ValueError, match="unknown source"):
        route_flow("IDP_FLOW", source="nope")
