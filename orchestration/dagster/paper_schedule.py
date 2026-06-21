"""Dagster wrapper for the Phase 7 paper loop — a monthly schedule per booked strategy.

Dagster is the canonical orchestrator for scheduled, lineage-tracked runs. This wraps the deterministic
``arc.autonomy.run_loop`` so EACH booked edge in ``arc.autonomy.spec.SPECS`` (momentum_front, nowcast_long,
fiscal_hard) gets its own asset and its own monthly schedule; each builds its signal through the single
shared ``arc.autonomy.build_signal`` (so a scheduled run can never trade a different strategy than the
booked one). The engine import is guarded: it lives inside the run body
so ``defs`` still loads with the assets present but un-run (e.g. CI), and ``dagster`` definition-loading
never needs the heavy monolith / its deps (xgboost, hmmlearn, ...).

The promotion verdict is deliberately NOT scheduled — it is a one-shot, human-gated, token-bearing
action (run ``scripts/paper_loop.py --strategy <name> --verdict`` by hand). Automation accrues each
strategy's forward holdout; a human scores it.

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

from arc.autonomy.spec import SPECS

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
STATE_ROOT = os.path.join(ROOT, "state", "paper")


def _run_paper_loop(name: str, spec: dict) -> dict:
    """Engine-touching body, imported lazily so definition-loading never needs the monolith.

    Reads the spec instrument's PIT monthly returns, builds the nowcast signal when required, then runs
    the deterministic catch-up loop month-by-month against a per-strategy append-only ledger."""
    import sys

    import pandas as pd

    sys.path.insert(0, os.path.join(ROOT, "server", "model"))
    sys.path.insert(0, ROOT)
    import macro_risk_os_v2 as eng

    from arc.autonomy import PaperLedger, build_signal, run_loop
    from arc.autonomy.source import knowledge_time, monthly_return_provider

    e = eng.ProductionEngine(eng.DEFAULT_CONFIG)
    e.initialize()

    inst = spec["instrument"]
    if inst not in e.data_layer.ret_df.columns:
        raise RuntimeError(f"[paper] '{inst}' not in ret_df — cannot run {name}")
    rets = e.data_layer.ret_df[inst].dropna()
    provider = monthly_return_provider(rets, pub_lag_days=1)

    signal = build_signal(spec, e.data_layer.monthly)
    signal_provider = None
    if signal is not None:
        signal = pd.Series(signal).dropna()
        signal_provider = lambda asof: signal[signal.index <= pd.Timestamp(asof)]  # noqa: E731

    ledger = PaperLedger(os.path.join(STATE_ROOT, name))
    asof = knowledge_time(rets.index[-1] + pd.offsets.MonthEnd(0), 1)
    months = [m for m in rets.index if knowledge_time(m, 1) <= asof]
    out = None
    for m in months:
        out = run_loop(knowledge_time(m, 1), provider, ledger, spec=spec,
                       signal_provider=signal_provider, run_id=f"dagster-{name}")
    return out["proposal"] if out else {}


def _make_strategy_defs(name: str, spec: dict):
    """Build the (asset, job, schedule) triple for one booked strategy. Each strategy is independent:
    its own asset, its own monthly RunRequest, its own state dir (``state/paper/<name>``)."""
    kind = spec.get("kind", "?")
    inst = spec.get("instrument", "?")

    @asset(
        name=f"paper_loop_tick_{name}",
        description=(f"{name} ({kind} on '{inst}') paper-loop tick: accrue the forward holdout + emit a "
                     "proposal (no scoring)."),
    )
    def _tick(context, _name=name, _spec=spec):
        proposal = _run_paper_loop(_name, _spec)
        context.add_output_metadata({"strategy": _name,
                                     "action": proposal.get("action", "n/a"),
                                     "n_forward_months": proposal.get("n_forward_months", 0)})
        return proposal

    job = define_asset_job(f"paper_loop_job_{name}", selection=[_tick])

    @schedule(name=f"monthly_paper_schedule_{name}", cron_schedule="0 6 2 * *", job=job,
              execution_timezone="America/Sao_Paulo")
    def _sched(context: ScheduleEvaluationContext):
        """Fire on the 2nd of each month (06:00 BRT) — after month-end returns become knowable."""
        return RunRequest(run_key=context.scheduled_execution_time.strftime("%Y-%m"))

    return _tick, job, _sched


_assets = []
_jobs = []
_schedules = []
for _name, _spec in SPECS.items():
    _a, _j, _s = _make_strategy_defs(_name, _spec)
    _assets.append(_a)
    _jobs.append(_j)
    _schedules.append(_s)


defs = Definitions(assets=_assets, jobs=_jobs, schedules=_schedules)
