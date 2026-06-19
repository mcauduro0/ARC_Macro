"""Dagster asset graph for the ARC data platform (ARCHITECTURE_SOTA.md §2/§4.7).

Dagster is the canonical orchestrator for the DATA+MODEL asset graph (Temporal handles the
agent/HITL side). This wraps the pure, tested ``arc.data.ingest`` logic as software-defined
assets so ingestion gets lineage, schedules, backfills, and a freshness/quality view.

Optional dependency:  pip install "dagster>=1.7" "dagster-webserver>=1.7"
Run locally:          dagster dev -m orchestration.dagster.assets
"""

from __future__ import annotations

import pandas as pd
from dagster import Definitions, MetadataValue, asset  # type: ignore[import-not-found]

from arc.data.catalog import all_contracts
from arc.data.ingest import report_frame, run_ingestion


@asset(description="Append-only bitemporal ledger ingested from all catalog sources.")
def bitemporal_observations(context) -> pd.DataFrame:
    store, report = run_ingestion()
    rpt = report_frame(report)
    context.add_output_metadata({
        "n_series": len(rpt),
        "rows_appended": int(rpt["rows_appended"].sum()),
        "rows_quarantined": int(rpt["rows_quarantined"].sum()),
        "sources_failed": int((~rpt["ok"]).sum()),
        "report": MetadataValue.md(rpt.to_markdown(index=False)),
    })
    return store.frame()


@asset(description="Per-series ingestion health (freshness gaps, quarantine, errors).")
def ingestion_health(context) -> pd.DataFrame:
    _, report = run_ingestion()
    rpt = report_frame(report)
    stale = rpt[(rpt["freshness_gap_days"].fillna(1e9) > 7)]
    context.add_output_metadata({
        "stale_series": MetadataValue.md(stale.to_markdown(index=False) if len(stale) else "none"),
        "catalog_size": len(all_contracts()),
    })
    return rpt


defs = Definitions(assets=[bitemporal_observations, ingestion_health])
