# Phase 8 — institutional wrap (Postgres / Temporal / Claude agents): deferral + concrete plan

**Status: DEFERRED — by design, not omission.** Phase 8 is the institutional persistence/orchestration/agent
wrap. Unlike Phases 5–6 (pure, self-contained, CI-testable infrastructure), Phase 8 depends on **external
services that are not provisioned in this environment** (a Postgres server, a Temporal server) and on **live
agent wiring** (Claude API calls replacing the deterministic skill stubs). Half-building it now — a Postgres
backend that can't be run, a Temporal worker with no server, agent stubs that don't call a model — would be
low-quality scaffolding that the honesty law (and good engineering) says to avoid. This doc records *why* it's
deferred and the *concrete* path so it can be executed as a focused effort when the services exist.

## Why the current spine makes this a clean, deferrable swap (not a rewrite)

The Phase 7 autonomy spine was built with the seams Phase 8 needs:
- **Persistence** is already an append-only, checksummed, idempotent ledger (`arc/autonomy/ledger.py`) behind a
  narrow interface (`append_*`, `frozen_frame`, `basis_for`, `consumed_hashes`, …). Swapping JSONL → Postgres is
  a backend change behind that same interface, not a logic change.
- **Orchestration** is the deterministic `run_loop` (`arc/autonomy/loop.py`) with explicit `Skill` seams
  (Research → Signal → Risk → Portfolio). It already runs monthly via Task Scheduler / Dagster. Temporal wraps
  the *same* loop as durable, retryable activities.
- **Agents**: `loop.py` skills are deterministic stubs with clean inputs/outputs — the exact points a
  Claude-driven agent plugs in, with the gate/verdict as the unchanged guardrail.

## Concrete plan (each independently shippable, in order)

1. **Postgres-backed ledger (no behavior change).** Define a `LedgerBackend` protocol (the methods
   `PaperLedger` already exposes); keep the JSONL backend as default; add a `PostgresLedgerBackend`
   (SQLAlchemy; append-only tables with the same `seq + record_sha` integrity + `(month, hash)` uniqueness).
   Port the existing 30+ ledger invariant tests to run against BOTH backends (same assertions, parametrized).
   Gate behind `ARC_LEDGER_BACKEND=postgres`; requires a running Postgres (docker-compose for local).
2. **Bitemporal store on Postgres.** Move `arc/data` `as_of()` store from DuckDB/in-memory to Postgres with the
   same vintage/knowledge-time schema; the as-of-invariance gate is the acceptance test.
3. **Temporal durable workflows.** Wrap `run_loop` (and the monthly accrual cycle) as a Temporal workflow with
   each skill an activity (retries, timeouts, heartbeats); the one-shot promotion verdict stays a manual,
   human-gated, token-bearing signal — never auto-scheduled. Requires a Temporal server.
4. **Claude-driven agents at the skill seams.** Replace the deterministic Research/Signal stubs with
   Claude-driven agents that PROPOSE (new hypotheses, data sources, sleeve ideas) but can only promote through
   the existing gate + single-use forward holdout — the agents never self-issue the holdout token. Start
   read-only (propose-only), human-approve, then widen autonomy.
5. **Model/experiment registry (MLflow).** Track gate runs, deflation bases, verdicts, and the forward-paper
   accruals as first-class experiment records.

## Prerequisites before starting

- A provisioned **Postgres** (local docker-compose acceptable) and **Temporal** server.
- A decision on **agent autonomy bounds** (propose-only vs auto-book) — defaults to propose-only + human sign-off,
  consistent with the existing human-gated promotion.
- The current invariant test suite is the acceptance net: every Phase 8 swap must keep it green (and add a
  dual-backend parametrization for persistence).

## Honest note

Nothing in Phase 8 changes the edge story: it is plumbing and autonomy ergonomics. The three booked sleeves
still earn promotion only through the forward holdout (~2028-06). Phase 8 makes the system institutional; it
does not, and must not, manufacture alpha. Deferring it keeps this batch's quality high; the plan above makes
resuming it a focused, low-ambiguity effort.
