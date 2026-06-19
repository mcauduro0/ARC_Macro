"""Bitemporal store + as_of() correctness — Phase 1 canaries.

These prove the platform fixes the audit's #1 macro leakage (no vintage / publication lag)
and the last-write-wins defect (revisions destroying history).
"""

from __future__ import annotations

import pandas as pd

from arc.contracts import SeriesContract
from arc.data import BitemporalStore, Observation, compute_knowledge_time
from arc.data.feature_view import pit_zscore
from arc.data.observation import observations_from_series


def ts(s: str) -> pd.Timestamp:
    return pd.Timestamp(s)


def test_compute_knowledge_time_applies_lag():
    kt = compute_knowledge_time(ts("2024-05-31").to_pydatetime(), 10)
    assert pd.Timestamp(kt) == ts("2024-06-10")
    # an explicit (later) publish timestamp wins over the floor
    kt2 = compute_knowledge_time(ts("2024-05-31").to_pydatetime(), 10, publish_ts=ts("2024-06-12").to_pydatetime())
    assert pd.Timestamp(kt2) == ts("2024-06-12")


def test_publication_lag_hides_unreleased_value():
    """IPCA for May is NOT knowable on June 1 (released ~June 10). This is the leakage the
    legacy event-time-only store silently committed."""
    store = BitemporalStore()
    store.append([Observation(
        series_id="IPCA", event_time=ts("2024-05-31"), knowledge_time=ts("2024-06-10"),
        value=0.46, source="BCB_SGS",
    )])
    assert store.as_of(ts("2024-06-01")).empty           # not yet published
    wide = store.as_of(ts("2024-06-15"))
    assert wide.loc[ts("2024-05-31"), "IPCA"] == 0.46     # now visible


def test_revision_creates_new_vintage_and_as_of_respects_it():
    """A revised value is a NEW row (later knowledge_time). as_of before the revision must
    return the original print; after, the revised one. History is preserved."""
    store = BitemporalStore()
    store.append([
        Observation(series_id="GDP", event_time=ts("2024-03-31"), knowledge_time=ts("2024-05-01"),
                    value=1.0, source="BCB", vintage_id="v1"),
        Observation(series_id="GDP", event_time=ts("2024-03-31"), knowledge_time=ts("2024-08-01"),
                    value=1.3, source="BCB", vintage_id="v2"),  # revision
    ])
    assert store.as_of(ts("2024-06-01")).loc[ts("2024-03-31"), "GDP"] == 1.0   # first print
    assert store.as_of(ts("2024-09-01")).loc[ts("2024-03-31"), "GDP"] == 1.3   # revised
    # append-only: both vintages still in the ledger
    assert len(store.frame()) == 2


def test_as_of_picks_latest_knowledge_below_cutoff():
    store = BitemporalStore()
    store.append([
        Observation(series_id="X", event_time=ts("2024-01-31"), knowledge_time=ts("2024-02-10"), value=10.0, source="s"),
        Observation(series_id="X", event_time=ts("2024-01-31"), knowledge_time=ts("2024-02-20"), value=11.0, source="s"),
        Observation(series_id="X", event_time=ts("2024-01-31"), knowledge_time=ts("2024-03-05"), value=12.0, source="s"),
    ])
    assert store.as_of(ts("2024-02-25")).loc[ts("2024-01-31"), "X"] == 11.0


def test_freshness_gap():
    store = BitemporalStore()
    store.append([Observation(series_id="X", event_time=ts("2024-01-31"),
                              knowledge_time=ts("2024-02-10"), value=1.0, source="s")])
    gap = store.freshness_gap("X", ts("2024-02-20"))
    assert gap == pd.Timedelta(days=10)
    assert store.freshness_gap("MISSING", ts("2024-02-20")) is None


def test_observations_from_series_bridge():
    s = pd.Series([1.0, 2.0, 3.0], index=pd.to_datetime(["2024-01-31", "2024-02-29", "2024-03-31"]))
    c = SeriesContract(series_id="SELIC", source="BCB_SGS", frequency="M", unit="pct", publication_lag_days=1)
    obs = observations_from_series(s, c)
    assert len(obs) == 3
    assert pd.Timestamp(obs[0].knowledge_time) == ts("2024-02-01")  # lag applied


def test_pit_feature_invariant_to_future_data():
    """THE Phase-1 leakage canary at the feature level: appending observations with
    knowledge_time AFTER asof must not change the feature value computed as_of."""
    idx = pd.date_range("2015-01-31", periods=80, freq="ME")
    base = pd.Series(range(80), index=idx, dtype="float64")
    c = SeriesContract(series_id="R", source="s", frequency="M", unit="x", publication_lag_days=0)
    store = BitemporalStore()
    store.append(observations_from_series(base, c))

    asof = idx[60]
    before = pit_zscore(store, asof, "R", window=36).dropna()

    # add FUTURE data (knowledge_time > asof) + a wild future revision
    future = pd.Series([999.0] * 19, index=idx[61:])
    store.append(observations_from_series(future, c))
    after = pit_zscore(store, asof, "R", window=36).dropna()

    # identical: the future cannot reach back through as_of() nor the causal transform
    assert before.index.equals(after.index)
    assert (before.to_numpy() == after.to_numpy()).all()
