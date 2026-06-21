"""CFTC COT adapter parsing tests (pure, no network).

Fixtures mimic the Socrata "Legacy - Futures Only" JSON rows for the CME Brazilian Real
contract (cftc_contract_market_code 102741). We assert NET = non-commercial long - short
and that the Tuesday report dates are preserved and sorted.
"""

from __future__ import annotations

import pandas as pd

from arc.contracts import SeriesContract
from arc.data.adapters.cftc_cot import (
    BRL_CONTRACT_CODE,
    COL_DATE,
    COL_LONG,
    COL_SHORT,
    CftcCotAdapter,
)


def _row(date: str, long: str, short: str) -> dict:
    """One Socrata row (string-valued, as the API returns), ISO-8601 timestamp date."""
    return {
        COL_DATE: f"{date}T00:00:00.000",
        COL_LONG: long,
        COL_SHORT: short,
    }


def test_parse_net_is_long_minus_short_and_dates():
    # Deliberately out-of-order to confirm the parser sorts by date.
    raw = [
        _row("2022-09-13", "42192", "9239"),   # net = 32953
        _row("2022-09-06", "40000", "50000"),  # net = -10000 (net short)
        _row("2022-09-20", "30000", "30000"),  # net = 0
    ]
    s = CftcCotAdapter().parse(raw)
    assert list(s.index) == sorted(s.index)            # sorted ascending
    assert s.loc["2022-09-13"] == 42192 - 9239 == 32953
    assert s.loc["2022-09-06"] == -10000               # net can be negative
    assert s.loc["2022-09-20"] == 0
    assert len(s) == 3


def test_parse_empty_and_missing_columns():
    assert CftcCotAdapter().parse([]).empty
    # Payload present but lacking the position columns -> empty (defensive, no KeyError).
    assert CftcCotAdapter().parse([{COL_DATE: "2022-09-13T00:00:00.000"}]).empty


def test_parse_drops_rows_with_unparseable_legs():
    raw = [
        _row("2022-09-13", "42192", "9239"),  # valid -> 32953
        _row("2022-09-20", "", ""),           # both legs blank -> NaN -> dropped
    ]
    s = CftcCotAdapter().parse(raw)
    assert len(s) == 1
    assert s.iloc[0] == 32953


def test_fetch_applies_publication_lag(monkeypatch):
    """fetch() must stamp knowledge_time = event_time + contract lag (no early-release leak).

    Tuesday 2022-09-13 snapshot + 3-day lag -> Friday 2022-09-16 knowledge_time."""
    contract = SeriesContract(
        series_id="CFTC_BRL_NET_SPEC", source="CFTC_COT", source_code=BRL_CONTRACT_CODE,
        frequency="W", unit="contracts", publication_lag_days=3,
        description="CFTC BRL non-commercial net (legacy futures-only)",
    )
    a = CftcCotAdapter()
    monkeypatch.setattr(
        a, "fetch_raw",
        lambda c, since=None: [_row("2022-09-13", "42192", "9239")],
    )
    obs = a.fetch(contract)
    assert len(obs) == 1
    o = obs[0]
    assert pd.Timestamp(o.event_time) == pd.Timestamp("2022-09-13")
    assert pd.Timestamp(o.knowledge_time) == pd.Timestamp("2022-09-16")
    assert o.source == "CFTC_COT"
    assert o.value == 32953.0
    assert o.series_id == "CFTC_BRL_NET_SPEC"
