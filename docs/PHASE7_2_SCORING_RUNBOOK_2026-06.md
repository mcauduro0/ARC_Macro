# Phase 7.2 — Scoring runbook: three edges, one-shot verdict, honestly blocked today (2026-06)

This is the operator runbook for the multi-strategy scoring step of the autonomy spine (Phase 7). Phase 7
booked the paper loop for the project's gated candidates; Phase 7.2 makes the loop **score ALL** of them and
promote only on a clean, pre-committed, one-shot verdict. It assumes the architecture in
[`PHASE7_AUTONOMY_SPINE_2026-06.md`](PHASE7_AUTONOMY_SPINE_2026-06.md) (two parallel streams, durable
governance, the verdict as the only scored path).

## The three booked edges

All live in `arc.autonomy.spec.SPECS`; each is a **distinct booked trial** with its own hash, its own
deflation basis, and its own single-use forward holdout. They are scored independently — one passing has
no bearing on the others.

| registry name | spec | instrument | kind | signal | n_trials | hash (12) |
|---|---|---|---|---|---|---|
| `momentum_front` | `FROZEN_SPEC` | `front` (1Y DI receiver) | momentum | price 3-month momentum (loop computes from returns) | **45** | `288c80331e8b` |
| `nowcast_long` | `NOWCAST_SPEC` | `long` (10Y DI receiver) | nowcast | `neg_nowcast_mom3` (negated 3-month change of the PIT activity factor) | **55** | `c9d995d2df32` |
| `fiscal_hard` | `HARD_PB_SPEC` | `hard` (sovereign spread receiver) | fiscal_momentum | `pb_mom6` (6-month change of the primary balance, oriented positive) | **69** | `c1ea44037f12` |

`n_trials` is the real cumulative multiple-testing count each edge was deflated against in-sample
(momentum 45, nowcast 55 over rounds 1+2; fiscal pb_momentum 69, the cumulative through round 3 — the
hard-spread search that surfaced it). The forward verdict reproduces the *identical* deflation
(`gate.sharpe_stats(n_trials, sr_std=None)` — the Lo-2002 auto SE, the same method the sleeve was screened
with in-sample), so the out-of-time bar is never quietly weakened.

> **`fiscal_hard` is a CANDIDATE, not a claimed edge.** It cleared the gate on a re-test (see
> [`PHASE4_5_PB_RETEST_POSITIONING_2026-06.md`](PHASE4_5_PB_RETEST_POSITIONING_2026-06.md)) with H2 +0.198,
> orthogonality to both other edges, and — the v1-open question now resolved — conclusive survival of a
> long global-risk control (IC 0.116 → 0.115 after neutralizing VIX+NFCI+US-term+Δcds, n=172). Two residual
> caveats keep it under forward paper rather than promoted: the edge lives in short-to-mid fiscal windows
> (diff 9/12 collapse), and its strength concentrates in the 2015–2020 fiscal-crisis era (thin recently).
> Booking it commits it to an honest out-of-time test, which is the disciplined way to adjudicate that doubt.

Each edge persists to its own append-only ledger under `state/paper/<key>`, where `<key>` follows
`scripts/paper_loop.py`'s convention: **`state/paper/momentum`**, **`state/paper/nowcast`**, and
**`state/paper/fiscal`**. The readiness harness shares these exact directories, so running
`score_both_edges.py` and `paper_loop.py --strategy <name>` advance the *same* durable holdout — they are
two front-ends over one ledger per edge.

## How the forward holdout accrues

1. **Book once (human pre-commitment).** `book_trial` records the trial (so retuning the spec raises the
   deflation bar — retuning is self-penalizing, not free) and freezes the immutable `DeflationBasis`:
   `(n_trials, sr_std=None, eval_at_n=24, dsr_min=0.50, forward_start)`. `forward_start` is the research
   cutoff (the last in-sample month at book time, `2026-06-30`); **only months strictly after it count as
   holdout.** Booking is idempotent — re-running keeps the original frozen basis.
2. **Catch-up monthly.** `run_loop` runs the deterministic Research→Risk→Signal→Portfolio pipeline for
   each newly-knowable month: it reconciles finalized months into the **frozen** (scored, unbreakered) and
   **live** (operated, breaker-controlled) streams, records the new decision once, and emits a
   human-approval `Proposal`. In-sample history is still used to *compute* the expanding-window position,
   but is never *recorded* as holdout (the `forward_start` gate excludes it). Re-running a month is an
   idempotent no-op; a revised input for a decided month raises `DataRevisionError` rather than repainting.
3. The **frozen** stream is the genuine, untouched out-of-time performance — the only thing the verdict
   ever scores. The circuit breaker may flatten *future* `live` positions but can never touch `frozen`.

## The one-shot verdict (when and how it fires)

`promotion_verdict` is the **only** function that scores a holdout. It is fail-closed, one-shot,
pre-committed, NaN-fatal, and deterministic-on-read:

- It requires **exactly `eval_at_n = 24`** accrued forward months. Fewer ⇒ `HoldoutNotReadyError`
  (`n < 24`); more ⇒ `HoldoutNotReadyError` (`overshot n > 24` — the pre-committed point was missed, re-book
  with an explicit new schedule rather than choosing when to look). This is the no-optional-stopping guard.
- It **consumes** the single-use holdout: it durably records consumption (fsync) **before** computing any
  score, so a crash leaves the holdout *spent*, never re-peekable. A second call returns the **recorded**
  verdict (deterministic read), never a recompute.
- **PASS iff** forward `dsr ≥ 0.50` **and** `sr_annual > 0` (both non-NaN). On PASS, book the edge into the
  portfolio at the sleeve level, sized by its standalone risk and diversification vs the carry/macro book.
- It is **human-gated**: it requires a `HoldoutToken` bound to the exact frozen hash; no agent can
  self-issue it, and it is deliberately decoupled from the breaker (the breaker protects live capital; the
  verdict judges the frozen edge).

Because the verdict consumes the holdout, the readiness harness defaults to a **non-consuming** path
(below). The consuming verdict only runs under an explicit flag.

## The readiness harness: `scripts/score_both_edges.py`

One pass over **all** booked edges: book (idempotent) → catch-up over all knowable months → assess the
verdict → print a single honest STATUS TABLE (strategy, hash, instrument, forward_start, forward months
accrued, eval_at_n, verdict status).

- **Default (`--catch-up-only`, the safe mode):** after catch-up it runs a **non-consuming readiness
  check** that READS the ledger (`frozen_frame()` for accrued-n, `basis_for()` for `eval_at_n`,
  `consumed_hashes()`/`verdict_for()` for spent state) and reports what a verdict *would* do today — it
  **never calls `promotion_verdict`**, so it consumes nothing and is fully idempotent. Run it as often as
  you like.
- **`--attempt-verdict` (opt-in, CONSUMING):** also calls the one-shot `promotion_verdict` per edge,
  capturing any governance refusal (e.g. `HoldoutNotReadyError`) instead of crashing. **This consumes the
  holdout when exactly 24 months have accrued** — only run it when you intend to spend the single-use
  holdout at the pre-committed evaluation point.

Run command (safe default):

```
python scripts/score_both_edges.py
```

Consuming, one-shot scoring (only at the pre-committed 24-month point, when ready):

```
python scripts/score_both_edges.py --attempt-verdict
```

## The Dagster monthly schedule

`orchestration/dagster/paper_schedule.py` **factory-generates a per-strategy job** for every edge in
`SPECS`: for each `(name, spec)` it builds an `(asset, job, schedule)` triple
(`_make_strategy_defs`). Each strategy gets:

- an asset `paper_loop_tick_<name>` that runs the engine-touching catch-up (`_run_paper_loop`) for that
  edge against its own `state/paper/<name>` ledger and emits the proposal metadata (`action`,
  `n_forward_months`);
- a job `paper_loop_job_<name>` selecting that asset;
- a schedule `monthly_paper_schedule_<name>` with cron **`0 6 2 * *`** in **`America/Sao_Paulo`** — i.e.
  the **2nd of each month at 06:00 BRT**, after month-end returns become knowable (publication lag).

The engine import is guarded inside the run body so `defs` loads (assets present, un-run) in CI without the
monolith / xgboost / hmmlearn. The schedule **accrues** each edge's holdout monthly; it deliberately does
**NOT** schedule the verdict — scoring is the one-shot, human-gated, token-bearing step run by hand
(`scripts/paper_loop.py --strategy <name> --verdict`, or `score_both_edges.py --attempt-verdict`).

Run the schedule locally: `dagster dev -m orchestration.dagster.paper_schedule`.

## Honest current state (2026-06-20)

`ret_df` ends **2026-06** and `forward_start = 2026-06-30` for all edges, so **there are 0 out-of-time
months** — none exist yet. The correct, honest behavior is therefore:

- every holdout accrues **0 forward months**;
- the non-consuming readiness check reports `REFUSED: HoldoutNotReadyError 0<24` for all three;
- the consuming verdict, if attempted, raises `HoldoutNotReadyError` and refuses (capturing it is the
  proof the machinery is wired and correctly blocked).

No forward months were fabricated — that is the prime directive ("não invente resultados"). The expected
table today:

```
+------------------+------------------+-------+--------------+--------+-----------+------------------------------------------------------+
| strategy         | hash             | inst  | forward_start | fwd_n  | eval_at_n | verdict status                                       |
+------------------+------------------+-------+--------------+--------+-----------+------------------------------------------------------+
| momentum_front   | 288c80331e8b     | front | 2026-06-30   | 0      | 24        | REFUSED: HoldoutNotReadyError 0<24                    |
| nowcast_long     | c9d995d2df32     | long  | 2026-06-30   | 0      | 24        | REFUSED: HoldoutNotReadyError 0<24                    |
| fiscal_hard      | c1ea44037f12     | hard  | 2026-06-30   | 0      | 24        | REFUSED: HoldoutNotReadyError 0<24                    |
+------------------+------------------+-------+--------------+--------+-----------+------------------------------------------------------+
```

**Time to first verdict: ~24 months.** One genuine out-of-time month accrues per monthly tick (the Dagster
schedule or a manual catch-up). At exactly the 24th accrued forward month — roughly **2028-06** — the
one-shot verdict for each edge becomes eligible; a human then spends the single-use holdout once per edge.
Until then, the only honest verdict is to refuse, and that is what the system does.
