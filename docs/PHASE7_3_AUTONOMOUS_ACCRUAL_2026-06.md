# Phase 7.3 — Always-on autonomous accrual: the monthly cycle (2026-06)

This is the operator runbook for the **always-on** step of the autonomy spine. Phase 7 booked the three
edges; Phase 7.2 made the loop **score** all of them with a one-shot, pre-committed verdict
([`PHASE7_2_SCORING_RUNBOOK_2026-06.md`](PHASE7_2_SCORING_RUNBOOK_2026-06.md)). Phase 7.3 makes the
accrual **autonomous**: a single deterministic monthly cycle that advances every booked edge's forward
holdout as real out-of-time months arrive — and **honestly accrues 0 today**.

It is a thin **orchestrator**. It does NOT re-init the engine and does NOT re-implement the loop. It
subprocesses the heavy steps and then reads the durable ledgers (pure, no engine) to log and summarize.

## What one monthly run does

`python scripts/monthly_accrual.py` runs, in order:

1. **Data refresh (best-effort).** Subprocess `python server/model/data_collector.py` (timeout 1200s)
   unless `--skip-refresh`. It refreshes the market-data CSVs the engine reads. A non-zero exit or
   exception is reported honestly (`route = "refresh FAILED: ..."`) and is **NEVER fatal** — accrual
   continues on the existing CSVs.
2. **Flows (best-effort).** Subprocess `python scripts/collect_flows.py` (timeout 600s) unless
   `--skip-flows`. It is already SGS-first / IPEADATA-confirmed-fallback (it never silently substitutes a
   different series). Honest failure, never fatal.
3. **Accrual.** Subprocess `python scripts/score_both_edges.py` (timeout 1800s). That harness **books
   idempotently**, **catches up** the deterministic `run_loop` over every knowable month for all three
   edges, and prints the NON-consuming readiness table. Its STATUS TABLE is captured and re-printed.
4. **Durable log.** Read each edge's ledger directly (PURE — no engine) and **append one JSON line** per
   run to `state/paper/accrual_log.jsonl` (schema below).
5. **Honest summary.** Print `<k>/3 edges accruing; 0 out-of-time months today; first verdict eligible
   when each reaches eval_at_n (~2028-06).`

The promotion **verdict is deliberately NOT run** by this cycle. It is a one-shot, human-gated,
token-bearing action (`scripts/paper_loop.py --strategy <name> --verdict`, or `score_both_edges.py
--attempt-verdict`). Automation accrues; a human scores.

Flags: `--skip-refresh`, `--skip-flows`, `--stamp ISO`.

## How failures are reported (honesty contract)

Each subprocess step returns a single honest **route** string captured into the durable log:

| route value | meaning |
|---|---|
| `OK rc=0` | step exited 0 |
| `SKIPPED` | step skipped via `--skip-refresh` / `--skip-flows` |
| `<step> FAILED: rc=<n>` | non-zero exit (tail of output logged to stderr) |
| `<step> FAILED: TimeoutExpired after <s>s` | exceeded the per-step timeout |
| `<step> FAILED: <ExcType>: <msg>` | the subprocess could not be launched |

A failure in refresh or flows never aborts the run — the cycle proceeds to accrue on whatever CSVs exist.
Only the pure ledger read at the end determines the accrued state, so accrual is robust to flaky external
APIs (the BCB SGS 502s, IPEADATA timeouts, etc.).

## The durable accrual log: `state/paper/accrual_log.jsonl`

One JSON object per line, one line per invocation (append-only; re-runs are distinguishable by `stamp`):

```json
{
  "stamp": "2026-06-30",
  "phase": "7.3",
  "refresh_route": "OK rc=0",
  "flows_route": "OK rc=0",
  "accrual_route": "OK rc=0",
  "edges": [
    {"name": "momentum_front", "hash": "288c80331e8b", "inst": "front",
     "n_frozen": 0, "eval_at_n": 24, "forward_start": "2026-06-30", "months_to_verdict": 24},
    {"name": "nowcast_long",   "hash": "c9d995d2df32", "inst": "long",
     "n_frozen": 0, "eval_at_n": 24, "forward_start": "2026-06-30", "months_to_verdict": 24},
    {"name": "fiscal_hard",    "hash": "c1ea44037f12", "inst": "hard",
     "n_frozen": 0, "eval_at_n": 24, "forward_start": "2026-06-30", "months_to_verdict": 24}
  ],
  "n_edges_accruing": 3,
  "n_out_of_time_months_today": 0
}
```

Field meanings:
- `stamp` — run stamp. Pass `--stamp ISO`; with no flag it defaults to the ledgers' latest known month
  (the max `forward_start` across edges), because `Date.now` is unavailable in deterministic contexts.
- `refresh_route` / `flows_route` / `accrual_route` — the per-step route strings above.
- `edges[]` — per edge: `name`, `hash` (12-char `strategy_hash`), `inst` (instrument), `n_frozen` (accrued
  out-of-time months = `frozen_frame().shape[0]`), `eval_at_n` (frozen in the basis = 24),
  `forward_start` (the frozen research cutoff), and `months_to_verdict = max(0, eval_at_n - n_frozen)`.
- `n_edges_accruing` — edges with a booked basis.
- `n_out_of_time_months_today` — the max accrued `n_frozen` (0 today).

## The honest today

`ret_df` ends **2026-06**; every edge's `forward_start` is **2026-06-30**. So **0 out-of-time months
exist**, every edge has `n_frozen = 0`, and any verdict correctly **REFUSES** with
`HoldoutNotReadyError 0<24`. This is the correct state — no forward months are fabricated. About
**24 months** must pass (~**2028-06**) before the first one-shot verdict is eligible.

## Watch item — `fiscal_hard` recency (baseline 2026-06; re-run as months accrue)

`fiscal_hard` was promoted as a *candidate* with a recency caveat. `scripts/reexamine_fiscal_hard.py`
quantifies it on a **carry-neutral** basis and is designed to be re-run unchanged as forward months grow
(the recent windows will then include genuinely new out-of-time data). Today's honest baseline
(2012-01..2026-04, n=172, report at `server/model/output/reexamine_fiscal_hard.json`):

| measure | value |
|---|---|
| full-sample carry-neutral IC | **+0.116** |
| **last-36m** cn-IC | **−0.170** (negative) |
| last-24 / last-48 / last-60 cn-IC | +0.126 / +0.053 / +0.262 |
| rolling-36m cn-IC (last 8 windows) | all **negative**, declining −0.05 → −0.19 |
| rolling-36m trend (OLS slope) | +0.015/yr → flat over the full series |
| **pre-committed flag `recency_ok`** | **False** (last-36m < +0.05 and negative) |

**Honest read:** the recency caveat is **UNRESOLVED — and is an orange flag**: the most recent 36 months
are *negative* on a carry-neutral basis (the strength sits in 2021–2023 and the last ~24, with a negative
~2023→2025 patch in between). This does **not** de-book the candidate — booking is a forward-paper
commitment, the deflation basis is immutable, and the genuinely out-of-time holdout (post-2026-06) is the
real adjudicator; a recent edge this weak will simply **fail the one-shot forward verdict** (DSR ≥ 0.50),
which is the system working as designed. It does mean: **watch `fiscal_hard` closely** and re-run
`reexamine_fiscal_hard.py` each time the accrual cycle adds months. (NB: the documented thirds
~[.16,.30,.08] were *raw* IC; the carry-neutral thirds differ — the binding recency measure is the
rolling-36m / last-36m above, not the coarse thirds.)

## Turn on always-on accrual on THIS Windows box (Task Scheduler)

Monthly on the **2nd at 06:00** (a couple of days into the month so the prior month is finalized/publishable):

```
schtasks /create /tn "ARC monthly accrual" /tr "c:/Users/mcaud/OneDrive/Documentos/Anti_Claude_test/ARC_Macro/scripts/run_monthly_accrual.bat" /sc monthly /d 2 /st 06:00
```

The wrapper `scripts/run_monthly_accrual.bat` cd's to the repo root, runs `python
scripts/monthly_accrual.py`, and appends stdout+stderr to `logs/monthly_accrual.log` (creating `logs/` if
missing). To pass flags, append them after the task command, or edit the `.bat` (it forwards `%*`).

Inspect / remove the task:

```
schtasks /query /tn "ARC monthly accrual"
schtasks /run   /tn "ARC monthly accrual"     REM run once now (smoke test)
schtasks /delete /tn "ARC monthly accrual" /f
```

## In-repo alternative: the Dagster monthly schedule

`orchestration/dagster/paper_schedule.py` already defines a per-edge monthly schedule
(`cron_schedule="0 6 2 * *"`, `execution_timezone="America/Sao_Paulo"` — i.e. 06:00 on the 2nd). That is
the canonical, lineage-tracked orchestrator for the same accrual; Task Scheduler + the `.bat` is the
zero-dependency local equivalent for this box. Use one or the other, not both, to avoid double-ticking
(the ledgers are idempotent on re-tick, so a double run is safe — it accrues no extra months — but it
wastes a refresh).

Run Dagster locally: `dagster dev -m orchestration.dagster.paper_schedule`.
