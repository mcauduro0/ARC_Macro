"""CSV->bitemporal-store migration (Phase 3.2) — CI-native (pandas + arc only).

Proves the migration stamps knowledge_time from the publication lag and that the store's as_of()
hides a value until its release, while reproducing the full series at the latest as-of.
"""

from __future__ import annotations

import os

import pandas as pd

from arc.data.engine_catalog import contract_for, lag_days_for
from arc.data.migrate import build_store_from_csv_dir, read_engine_csv

_LATEST = pd.Timestamp("2999-12-31")


def _write_csv(path, dates, values, date_col="date", val_col="value"):
    pd.DataFrame({date_col: dates, val_col: values}).to_csv(path, index=False)


def test_read_engine_csv_detects_date_col_variants(tmp_path):
    p = tmp_path / "X.csv"
    _write_csv(p, ["2020-01-31", "2020-02-29"], [1.0, 2.0], date_col="observation_date")
    s = read_engine_csv(str(p))
    assert list(s.values) == [1.0, 2.0]
    assert s.index[0] == pd.Timestamp("2020-01-31")


def test_market_series_lag_is_one_day_and_visible_next_day(tmp_path):
    _write_csv(tmp_path / "USDBRL.csv", ["2020-06-15", "2020-06-16"], [5.0, 5.1])
    store = build_store_from_csv_dir(str(tmp_path), only=["USDBRL"])
    # event 2020-06-16, lag 1d -> knowledge 2020-06-17
    assert lag_days_for("USDBRL") == 1
    vis = store.as_of_series(pd.Timestamp("2020-06-16"), "USDBRL")
    assert vis.index.max() == pd.Timestamp("2020-06-15")  # the 16th not yet knowable on the 16th
    vis2 = store.as_of_series(pd.Timestamp("2020-06-17"), "USDBRL")
    assert vis2.index.max() == pd.Timestamp("2020-06-16")


def test_macro_series_hidden_until_publication_lag(tmp_path):
    # IPCA_MONTHLY lag = 10d: a print for ref month-end is not knowable until ~10 days later
    _write_csv(tmp_path / "IPCA_MONTHLY.csv", ["2020-05-31", "2020-06-30"], [0.3, 0.4])
    store = build_store_from_csv_dir(str(tmp_path), only=["IPCA_MONTHLY"])
    assert lag_days_for("IPCA_MONTHLY") == 10
    # On 2020-07-05, the June print (knowledge 2020-07-10) is NOT yet visible; May is.
    vis = store.as_of_series(pd.Timestamp("2020-07-05"), "IPCA_MONTHLY")
    assert vis.index.max() == pd.Timestamp("2020-05-31")
    # On 2020-07-10 it becomes visible.
    vis2 = store.as_of_series(pd.Timestamp("2020-07-10"), "IPCA_MONTHLY")
    assert vis2.index.max() == pd.Timestamp("2020-06-30")


def test_latest_asof_reproduces_full_series(tmp_path):
    dates = pd.date_range("2019-01-31", periods=12, freq="ME").strftime("%Y-%m-%d").tolist()
    vals = [float(i) for i in range(12)]
    _write_csv(tmp_path / "IBC_BR.csv", dates, vals)
    store = build_store_from_csv_dir(str(tmp_path), only=["IBC_BR"])
    full = read_engine_csv(str(tmp_path / "IBC_BR.csv"))
    asof = store.as_of_series(_LATEST, "IBC_BR")
    assert len(asof) == len(full)
    assert (asof.sort_index().values == full.sort_index().values).all()


def test_prefix_invariance_across_asof(tmp_path):
    dates = pd.date_range("2019-01-31", periods=24, freq="ME").strftime("%Y-%m-%d").tolist()
    _write_csv(tmp_path / "USDBRL.csv", dates, [float(i) for i in range(24)])
    store = build_store_from_csv_dir(str(tmp_path), only=["USDBRL"])
    t1, t2 = pd.Timestamp("2020-01-31"), pd.Timestamp("2020-12-31")
    a1 = store.as_of_series(t1, "USDBRL")
    a2 = store.as_of_series(t2, "USDBRL")
    common = a1.index.intersection(a2.index)
    assert len(common) > 6
    assert (a1.reindex(common).values == a2.reindex(common).values).all()  # past never repainted


def test_contract_carries_lag():
    c = contract_for("IBC_BR")
    assert c.publication_lag_days == 45
    assert c.series_id == "IBC_BR"
    assert c.frequency == "M"
