# Phase 7 — Autonomy spine: a persistent, honest paper loop (2026-06)

Phase 7 is "autonomy". The roadmap's full scope (Postgres, Temporal, LangGraph agents) is
institutional-wrap infrastructure; pulling it in now would be infra theater without payoff and would
violate the project's dependency-light, honesty-first discipline. The **high-value core** of Phase 7 is
the one thing that turns the project's single verified edge into a living system: the **paper loop for
`front/mom3`** — the bridge from "validated edge" to a system that OPERATES, PERSISTS state across
restarts, ACCUMULATES the reserved single-use holdout (forward out-of-time months), and FEEDS BACK
(drift / circuit breaker / promotion verdict), with a human approving promotions.

It is built as a new pure package `arc/autonomy/` (CI-native: pandas/numpy + `arc.research`/`arc.eval`
only) plus an engine-touching CLI and a Dagster schedule. Postgres/Temporal are deferred to Phase 8.

## How it was designed: adversarial-first

The paper loop has this project's signature failure mode baked in — look-ahead in the forward stream,
holdout peeking, ledger repainting. So before any code, a design workflow ran **3 independent architects
+ a dedicated governance/look-ahead adversary + a synthesizer**. The adversary read the actual source of
the composed primitives and caught real bugs in the candidate designs:

- `causal_position` uses an **expanding** (not rolling) z-score → any "recompute on reconcile / recompute
  to check idempotency" path is structurally leaky. Fix: positions are written ONCE; reconcile multiplies
  the **stored** position; idempotency is key-only.
- `sleeve_stats` deflates with the **Lo-2002 auto SE** (`sr_std=None`), and cannot accept a custom
  `sr_std` — so a forward DSR computed via `sleeve_stats` cannot reproduce the gate's deflation by
  claiming a custom dispersion. Fix: the verdict calls `gate.sharpe_stats` directly with the persisted
  basis; `sr_std=None` reproduces the *same* method the sleeve was screened with in-sample.
- `GovernanceLedger` and `HoldoutToken` are **in-memory only** → `n_trials`, `sr_std`, and single-use
  silently reset across restarts, re-opening a "spent" holdout as fresh, undeflated alpha (the 0.39→3.92
  trap, automated). Fix: consumption + deflation basis are **durable ledger facts**, not in-memory flags.

## Architecture: two parallel streams (the decisive idea)

The forward paper stream must be the **genuine, untouched** out-of-time performance of the *frozen*
strategy to be a valid holdout. So every reconciled month is recorded in **two** streams:

- **`frozen`** — the unbreakered frozen-strategy position and its realized return. This is the ONLY
  stream the promotion verdict scores. The circuit breaker never touches it. Bad months stay in it
  permanently (no left-tail truncation).
- **`live`** — the actually-operated position (the breaker may flatten it to 0 going forward). This is
  for real-money risk control and operator telemetry, NOT for the verdict.

`promotion_verdict` reads `frozen` only; `circuit_breaker` reads `live` only. This single separation is
what stops the breaker and the in-memory governance objects from quietly turning the single-use holdout
back into a re-peekable, under-deflated, left-tail-truncated backtest.

## Files

| File | Purpose |
|---|---|
| `arc/autonomy/spec.py` | The immutable `FROZEN_SPEC` (`front`, lookback 3, z_window 12, clip 2, 2bp) + `strategy_hash` (the binding key threaded through every record) + `canonical_json`. |
| `arc/autonomy/ledger.py` | Append-only JSONL store. Frozen dataclasses; `_append` is the sole writer (mode `a`, flush+fsync); `seq` + `record_sha` IN the payload; corrupt lines quarantined to `.corrupt`; `(month,hash)` duplicate-fatal on read; idempotent appends; `DataRevisionError` on a changed input for a recorded month. Durable governance records (booking, deflation basis, consumed, verdict). |
| `arc/autonomy/paper.py` | `tick` (record the decision for the month it earns; warm-up→None; `forward_start` gate excludes in-sample months; `LookAheadError`/`UnbookedTrialError`), `reconcile` (finality-gated; uses STORED positions, never recomputes; writes both streams), `forward_telemetry` (token-free, **no scores**). |
| `arc/autonomy/monitor.py` | `signal_psi`/`detect_drift` (non-binding), `circuit_breaker` (live-only, mutates nothing), `promotion_verdict` (the only scored path). |
| `arc/autonomy/governance.py` | `book_trial` (human pre-commitment: counts the trial + freezes the deflation basis with `forward_start`, `eval_at_n`, `dsr_min`), `issue_token`. |
| `arc/autonomy/source.py` | `monthly_return_provider` — the CI-tested publication-lag boundary (a month-M return is invisible until M+lag). The one place look-ahead can enter, made pure and tested. |
| `arc/autonomy/loop.py` | The deterministic Research→Signal→Risk→Portfolio skill pipeline + `run_loop` emitting a human-approval `Proposal` (never scores, never auto-promotes). Each skill is a seam where a Claude-driven agent plugs in later. |
| `scripts/paper_loop.py` | Engine-touching CLI (`--book` / `--catch-up` / `--verdict`); reads `ret_df["front"]`, wraps it with the publication-lag provider, drives the loop, persists `state/paper/`. |
| `orchestration/dagster/paper_schedule.py` | Monthly schedule (2nd of the month, 06:00 BRT) + asset wrapping `run_loop`; engine import guarded so `defs` loads in CI without the monolith. |

## The promotion verdict (the only scored path)

Fail-closed, one-shot, pre-committed, NaN-fatal, deterministic-on-read:

1. If already consumed → return the **recorded** verdict (deterministic read); if consumed but no verdict
   exists (prior crash) → raise `HoldoutConsumedError` (spent, never re-peekable).
2. Token must bind to the frozen hash; a persisted `DeflationBasis` is mandatory (`MissingDeflationBasisError`
   — never default to a weak bar).
3. Evaluate at **exactly** `eval_at_n` accrued forward months (`HoldoutNotReadyError` otherwise — no
   optional stopping).
4. Durably record consumption (fsync) **before** scoring.
5. Score the `frozen` stream with `gate.sharpe_stats(n_trials, sr_std)` from the basis.
6. **PASS iff** `dsr ≥ dsr_min` and `sr_annual > 0` (both non-NaN). The IC-vs-carry-neutral-bar criterion
   is intentionally **dropped**: a single-instrument sleeve has no forward carry panel, and comparing a
   raw forward IC to a carry-neutral bar would be systematically optimistic.

The circuit breaker may read `live`, set `halted`, flatten **future** `live` positions, and alert. It may
NOT touch `frozen`, delete/relabel any month, consume the token, or influence the verdict. (The verdict is
deliberately decoupled from the breaker — it judges the frozen edge; the breaker protects live capital.)

## The honesty fix found by running it

The first end-to-end run replayed **all 159 in-sample months** into the ledger as "forward holdout" — the
exact self-deception this project exists to prevent (the one-shot guard caught it: it refused the verdict,
`overshot 159 > 24`). Fix: a pre-committed **`forward_start`** (the research cutoff, frozen at book time)
in the deflation basis. Only months *after* it accrue to the holdout; in-sample history is still used to
*compute* positions (the expanding window is legitimate) but is never *recorded* as holdout.

After the fix, today's honest state: `forward_start = 2026-06-30`, **0 forward months accrued** (research
used data through ~2026-06, so no out-of-time data exists yet), the first forward proposal for 2026-07 is
OPERATE/short the 1Y (frozen_position −0.61), and the verdict refuses (`0 months; eval_at_n=24`). The
holdout accrues one genuine month at a time; the verdict fires once, at 24 months.

## Tests (24 CI-native, in `tests/test_autonomy.py`)

Golden forward-equivalence (the loop rebuilds `momentum_sleeve_returns` to 1e-9); decision keying /
look-ahead; no-recompute-on-reconcile (monkeypatch `causal_position` to raise); `forward_start` excludes
in-sample; idempotent re-tick; data-revision detection; duplicate-fatal read; corrupt-line quarantine;
checksum tamper detection; unbooked-trial refusal; telemetry exposes no scores; basis-required; verdict
reproduces the gate's deflation; one-shot / deterministic-on-read; consumed-without-verdict fail-closed;
pre-committed `eval_at_n`; NaN-fatal; token-binding; halt zeroes live-not-frozen; breaker cannot mutate;
breaker halts on drawdown; loop accumulates + proposes; loop is deterministic. **159 pytest green total.**

## Promotion protocol (unchanged, now operationalized)

1. **Paper**: `python scripts/paper_loop.py --book` (once) then `--catch-up` monthly (or the Dagster
   schedule) accrues genuinely out-of-time months — the reserved single-use holdout.
2. **Verdict**: at exactly 24 accrued months, `--verdict` fires the one-shot, human-token-gated
   `promotion_verdict`. PASS ⇒ the forward DSR(45) ≥ 0.50 and Sharpe > 0 confirm the edge out-of-time.
3. **Book combination**: only on PASS, allocate at the portfolio level, sized by its (low) standalone risk
   and diversification vs the carry/macro book.

## What this is NOT (deferred, honestly)

- No Postgres/Temporal/LangGraph (Phase 8 institutional wrap). Persistence is append-only JSONL mirroring
  the bitemporal store's discipline.
- No Claude-driven agents yet — `loop.py` is the deterministic skeleton with clean seams; swapping a
  deterministic skill for an agent is a list substitution, no rewiring.
- The verdict is human-gated and cannot be self-issued by any agent.
