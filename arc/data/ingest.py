"""Ingestion runner — orchestrates adapters -> contract validation -> bitemporal store.

This is the pure, testable core of what an orchestrator (Dagster) would schedule. It:
  1. picks the right adapter per series source,
  2. fetches + parses to Observations (publication lag already applied),
  3. validates each value against its SeriesContract (out-of-range rows are QUARANTINED,
     never silently stored — replacing the legacy silent stale-cache fallback),
  4. appends valid rows append-only and reports rows/violations/freshness per series.

Network lives only inside the adapters' ``fetch_raw``; this module is deterministic given
an adapter, so it is unit-tested with stub adapters.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Iterable, Optional

import pandas as pd

from arc.contracts import SeriesContract
from arc.data.adapters import Adapter, BcbFocusAdapter, BcbSgsAdapter, FredAdapter
from arc.data.catalog import all_contracts, get_contract
from arc.data.observation import Observation
from arc.data.store import BitemporalStore

# source -> adapter factory. Extend here as new sources are added.
ADAPTER_REGISTRY: dict[str, Callable[[], Adapter]] = {
    "BCB_SGS": BcbSgsAdapter,
    "BCB_FOCUS": BcbFocusAdapter,
    "FRED": FredAdapter,
}


@dataclass
class SeriesIngestResult:
    series_id: str
    source: str
    rows_appended: int = 0
    rows_quarantined: int = 0
    error: Optional[str] = None
    freshness_gap_days: Optional[float] = None
    violations: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.error is None


def adapter_for(source: str, registry: dict[str, Callable[[], Adapter]] = ADAPTER_REGISTRY) -> Adapter:
    if source not in registry:
        raise KeyError(f"no adapter registered for source '{source}'")
    return registry[source]()


def ingest_series(
    contract: SeriesContract,
    store: BitemporalStore,
    *,
    adapter: Optional[Adapter] = None,
    since: Optional[datetime] = None,
    ingest_run_id: Optional[str] = None,
    asof: Optional[datetime] = None,
    registry: dict[str, Callable[[], Adapter]] = ADAPTER_REGISTRY,
) -> SeriesIngestResult:
    res = SeriesIngestResult(series_id=contract.series_id, source=contract.source)
    try:
        ad = adapter or adapter_for(contract.source, registry)
        obs: list[Observation] = ad.fetch(contract, since, ingest_run_id=ingest_run_id)
    except Exception as e:  # network/parse failure -> reported, NOT silently substituted
        res.error = f"{type(e).__name__}: {e}"
        return res
    valid: list[Observation] = []
    for o in obs:
        viol = contract.validate_value(o.value)
        if viol:
            res.rows_quarantined += 1
            res.violations.extend(viol[:1])
        else:
            valid.append(o)
    res.rows_appended = store.append(valid)
    gap = store.freshness_gap(contract.series_id, asof or datetime.now(timezone.utc).replace(tzinfo=None))
    res.freshness_gap_days = None if gap is None else round(gap.total_seconds() / 86400, 2)
    return res


def run_ingestion(
    series_ids: Optional[Iterable[str]] = None,
    store: Optional[BitemporalStore] = None,
    *,
    since: Optional[datetime] = None,
    asof: Optional[datetime] = None,
    registry: dict[str, Callable[[], Adapter]] = ADAPTER_REGISTRY,
    save_path: Optional[str] = None,
) -> tuple[BitemporalStore, list[SeriesIngestResult]]:
    """Ingest a set of series (default: the whole catalog) into a store. Returns
    (store, per-series report). Persists to Parquet/CSV if ``save_path`` is given."""
    store = store or BitemporalStore()
    contracts = [get_contract(s) for s in series_ids] if series_ids else all_contracts()
    run_id = str(uuid.uuid4())
    report = [
        ingest_series(c, store, since=since, ingest_run_id=run_id, asof=asof, registry=registry)
        for c in contracts
    ]
    if save_path:
        store.save(save_path)
    return store, report


def report_frame(report: list[SeriesIngestResult]) -> pd.DataFrame:
    return pd.DataFrame([
        {
            "series_id": r.series_id, "source": r.source, "rows_appended": r.rows_appended,
            "rows_quarantined": r.rows_quarantined, "freshness_gap_days": r.freshness_gap_days,
            "ok": r.ok, "error": r.error,
        }
        for r in report
    ])
