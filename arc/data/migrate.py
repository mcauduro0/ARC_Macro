"""Migrate the legacy engine's event-time CSVs into a bitemporal store (Phase 3.2).

The monolith reads one CSV per series via ``load_series(name)`` (``{name}.csv`` in the data dir). This
builds a :class:`BitemporalStore` keyed by the same basenames, stamping each value's knowledge_time
from its publication lag (``engine_catalog``). The CSVs are single-vintage (each run overwrites them),
so the store holds one best-known vintage per series — enough to make ``as_of(t)`` publication-correct;
true per-vintage history arrives when the real adapters take over.

The CSV parser here mirrors ``macro_risk_os_v2.load_series`` exactly (same date-column detection, same
"first non-date column is the value") so that ``store.as_of_series(latest, name)`` reproduces what
``load_series(name)`` would have read — the property that makes the engine swap behavior-preserving.
"""

from __future__ import annotations

import os
from typing import Iterable, Optional

import pandas as pd

from arc.data.engine_catalog import contract_for
from arc.data.observation import observations_from_series
from arc.data.store import BitemporalStore

_DATE_COLS = ["Date", "date", "observation_date", "data", "Unnamed: 0"]


def read_engine_csv(path: str) -> pd.Series:
    """Parse a legacy engine CSV into a date-indexed float Series — identical logic to
    ``macro_risk_os_v2.load_series`` so the store reproduces the engine's reads."""
    if not os.path.exists(path):
        return pd.Series(dtype="float64")
    df = pd.read_csv(path)
    date_col = next((c for c in _DATE_COLS if c in df.columns), None)
    if date_col is None:
        return pd.Series(dtype="float64")
    val_cols = [c for c in df.columns if c != date_col]
    if not val_cols:
        return pd.Series(dtype="float64")
    idx = pd.to_datetime(df[date_col], errors="coerce")
    s = pd.Series(pd.to_numeric(df[val_cols[0]], errors="coerce").values, index=idx)
    s = s[s.index.notna()].dropna().sort_index()
    s.index.name = "date"
    return s


def build_store_from_csv_dir(
    data_dir: str,
    *,
    only: Optional[Iterable[str]] = None,
) -> BitemporalStore:
    """Build a BitemporalStore from every ``*.csv`` in ``data_dir`` (basename = series_id), applying
    each series' publication lag. ``only`` restricts to a subset of basenames (faster tests)."""
    store = BitemporalStore()
    want = set(only) if only is not None else None
    for fn in sorted(os.listdir(data_dir)):
        if not fn.endswith(".csv"):
            continue
        name = fn[:-4]
        if want is not None and name not in want:
            continue
        s = read_engine_csv(os.path.join(data_dir, fn))
        if len(s) == 0:
            continue
        contract = contract_for(name)
        store.append(observations_from_series(s, contract, source=contract.source))
    return store
