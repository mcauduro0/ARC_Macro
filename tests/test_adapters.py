"""Adapter parsing + publication-lag tests (pure, no network)."""

from __future__ import annotations

import pandas as pd

from arc.data.adapters import BcbSgsAdapter, FredAdapter, observations_from_csv
from arc.data.catalog import get_contract


def test_bcb_sgs_parse_handles_br_dates_and_decimals():
    raw = [{"data": "31/05/2024", "valor": "0.46"}, {"data": "28/06/2024", "valor": "0,38"}]
    s = BcbSgsAdapter().parse(raw)
    assert s.loc["2024-05-31"] == 0.46
    assert s.loc["2024-06-28"] == 0.38  # comma decimal handled
    assert list(s.index) == sorted(s.index)


def test_bcb_sgs_parse_empty():
    assert BcbSgsAdapter().parse([]).empty


def test_fred_parse_drops_missing_marker():
    raw = {"observations": [{"date": "2024-05-31", "value": "4.5"}, {"date": "2024-06-03", "value": "."}]}
    s = FredAdapter(api_key="x").parse(raw)
    assert len(s) == 1 and s.iloc[0] == 4.5


def test_fetch_applies_publication_lag(monkeypatch):
    """The adapter must stamp knowledge_time = event_time + contract lag (the leakage fix)."""
    a = BcbSgsAdapter()
    monkeypatch.setattr(a, "fetch_raw", lambda contract, since=None: [{"data": "31/05/2024", "valor": "0.46"}])
    obs = a.fetch(get_contract("IPCA_MOM"))  # lag = 10 days
    assert len(obs) == 1
    o = obs[0]
    assert pd.Timestamp(o.event_time) == pd.Timestamp("2024-05-31")
    assert pd.Timestamp(o.knowledge_time) == pd.Timestamp("2024-06-10")
    assert o.source == "BCB_SGS" and o.value == 0.46


def test_csv_bridge_applies_lag(tmp_path):
    p = tmp_path / "selic.csv"
    pd.DataFrame({"date": ["2024-01-31", "2024-02-29"], "value": [11.0, 11.25]}).to_csv(p, index=False)
    obs = observations_from_csv(str(p), get_contract("SELIC_TARGET"))  # lag = 1 day
    assert len(obs) == 2
    assert pd.Timestamp(obs[0].knowledge_time) == pd.Timestamp("2024-02-01")
    assert obs[1].value == 11.25
