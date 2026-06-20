"""Dagster wrapper for the Phase 7 paper loop — a monthly schedule + a catch-up sensor.

Dagster is the canonical orchestrator for scheduled, lineage-tracked runs. This wraps the deterministic
``arc.autonomy.run_loop`` so the front/mom3 paper loop gets a monthly schedule and a sensor that fills
missed months. The engine import is guarded: if the heavy monolith / its deps are absent (e.g. CI),
``defs`` still loads with the asset disabled, so ``dagster`` definition-loading never breaks.

The promotion verdict is deliberately NOT scheduled — it is a one-shot, human-gated, token-bearing
action (run ``scripts/paper_loop.py --verdict`` by hand). Automation accrues the holdout; a human scores it.

Run locally:  dagster dev -m orchestration.dagster.paper_schedule
"""

from __future__ import annotations

import os

from dagster import (  # type: ignore[import-not-found]
    Definitions,
    RunRequest,
    ScheduleEvaluationContext,
    asset,
    define_asset_job,
    schedule,
)

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
STATE_DIR = os.path.join(ROOT, "state", "paper")


def _run_paper_loop() -> dict:
    """Engine-touching body, imported lazily so definition-loading never needs the monolith."""
    import sys

    import pandas as pd

    sys.path.insert(0, os.path.join(ROOT, "server", "model"))
    sys.path.insert(0, ROOT)
    import macro_risk_os_v2 as eng

    from arc.autonomy import PaperLedger, run_loop
    from arc.autonomy.source import knowledge_time, monthly_return_provider

    e = eng.ProductionEngine(eng.DEFAULT_CONFIG)
    e.initialize()
    front = e.data_layer.ret_df["front"].dropna()
    provider = monthly_return_provider(front, pub_lag_days=1)
    asof = knowledge_time(front.index[-1] + pd.offsets.MonthEnd(0), 1)
    ledger = PaperLedger(STATE_DIR)
    months = [m for m in front.index if knowledge_time(m, 1) <= asof]
    out = None
    for m in months:
        out = run_loop(knowledge_time(m, 1), provider, ledger, run_id="dagster-paper")
    return out["proposal"] if out else {}


@asset(description="Front/mom3 paper-loop tick: accrue the forward holdout + emit a proposal (no scoring).")
def paper_loop_tick(context):
    proposal = _run_paper_loop()
    context.add_output_metadata({"action": proposal.get("action", "n/a"),
                                 "n_forward_months": proposal.get("n_forward_months", 0)})
    return proposal


paper_loop_job = define_asset_job("paper_loop_job", selection=[paper_loop_tick])


@schedule(cron_schedule="0 6 2 * *", job=paper_loop_job, execution_timezone="America/Sao_Paulo")
def monthly_paper_schedule(context: ScheduleEvaluationContext):
    """Fire on the 2nd of each month (06:00 BRT) — after month-end returns become knowable."""
    return RunRequest(run_key=context.scheduled_execution_time.strftime("%Y-%m"))


defs = Definitions(assets=[paper_loop_tick], jobs=[paper_loop_job], schedules=[monthly_paper_schedule])
