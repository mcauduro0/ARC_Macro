# Phase 7.4 — the co-pilot (human-in-the-loop) + an honest statistical-power audit & the pooled holdout

Two complementary tracks the owner asked to "execute agora": **(b)** run the loop as a CO-PILOT (it
proposes, the human decides, each decision feeds a durable forward stream) and **(a)** look for more
history/instruments to raise statistical power before the ~2028 verdict. Both delivered honestly, fully
CI-tested (22 new tests, 387 green), with the disciplined result: a real human-in-the-loop operating
layer that **cannot touch the holdout**, and a measured power story whose only true forward-power lever is
cross-sectional pooling — pre-registered, not asserted.

---

## (b) The co-pilot — three streams, the holdout untouchable

The co-pilot is the human-in-the-loop front-end over the Phase 7 spine. The design keeps the scored
holdout sacrosanct by adding a THIRD, strictly separate stream rather than letting a human edit anything
that is scored:

| stream | who drives it | what it is |
|---|---|---|
| `frozen` | deterministic | the scored holdout — the verdict's ONLY input; the human can never touch it |
| `live` | deterministic + breaker | the auto-operate baseline (what a no-human system would do) |
| **`operator`** | **the human (co-pilot)** | **APPROVE / OVERRIDE / SKIP decisions — the real forward track record** |

- **`arc/autonomy/copilot.py`** — `propose()` advances the deterministic loop (which accrues frozen +
  live) and returns a human-facing `OperatorProposal`; `decide()` commits the human's
  APPROVE/OVERRIDE/SKIP as an **immutable** `OperatorDecision` (idempotent on `(month,hash)`; a different
  later choice raises `RepaintError` — you cannot repaint your own record); `copilot_status()` is an
  operational snapshot of all three streams with **no Sharpe/DSR/IC** (no back-door peek at a forward
  score).
- **`arc/autonomy/ledger.py`** — a new `OperatorDecision` record + `operator.jsonl`, with the same
  append-only / checksummed / duplicate-fatal discipline as every other ledger family.
- **`arc/autonomy/paper.py`** — `reconcile_operator()` realizes the operator stream (turnover from the
  prior operator position; entry from flat). `tick` / `reconcile` / `Decision` are **untouched** — the
  human overlay is purely additive.
- **`scripts/copilot.py`** — the CLI: `--propose` (advance + show proposals for every edge), `--decide`
  (`--strategy --action [--position] --rationale`), `--status`.

**Prime invariant (CI-proven, `tests/test_copilot.py`):** whatever the human does — even SKIP everything —
the frozen stream is **byte-identical** to a no-co-pilot run. `propose()` accrues the holdout even if the
human never decides; the operator stream stays empty until they act. 13 tests cover this plus
APPROVE==live-baseline, the operator reconcile arithmetic, override fat-finger/missing-position guards,
invalid action, decide-before-propose, immutability, duplicate-fatal, and the no-scores status.

**Revision-robustness (real, surfaced live):** the production momentum/nowcast ledgers already held a
2026-07 decision from prior accrual; live data has since revised, so re-ticking raised `DataRevisionError`
(the anti-repaint guard, working). `propose()` catches it, keeps the **locked** holdout decision, and
builds the proposal from it with a loud warning — never repainting.

**Run against the real engine (today, 2026-06):** the co-pilot proposes the first forward month (2026-07):

| sleeve | suggestion | frozen/proposed position | note |
|---|---|---|---|
| momentum_front | OPERATE | **-0.610** (short the 1Y receiver) | holdout locked (data revised since record) |
| nowcast_long | OPERATE | **+0.248** (long the 10Y receiver) | holdout locked (data revised since record) |
| fiscal_hard | HOLD(warmup) | — | signal not formable this month |

`--decide` verified end-to-end (committed APPROVE → immutable operator record with rationale + proposal
digest; all three streams correctly show 0 realized months — 2026-07 realizes in August).

---

## (a) Statistical power — measured, with the one honest accelerator pre-registered

`scripts/measure_statistical_power.py` (engine-touching, measured, no edge asserted):

- **Instrument cross-section:** 5 instruments, **N_eff = 2.05** (41% of nominal — the DI receivers are
  highly collinear).
- **The 3 booked sleeves are nearly independent:** avg |corr| **0.11**, **K_eff = 2.92 of 3**. This is
  the number that matters.
- **The forward verdict is bound by forward calendar months.** More in-sample history, and more
  macro-series history (features only — unused before `ret_df.index[0]`), do **NOT** change the verdict's
  inputs, so they do **NOT** shorten the time to promotion. Honest null on "more history → faster verdict".
- **The only honest accelerator is cross-sectional POOLING.** With K_eff=2.92, an equal-weight pooled
  holdout carries equivalent t-content in ~24/K_eff months.

### The pooled forward holdout (4th booked candidate, pre-registered)

`POOL_SPEC` (`arc/autonomy/spec.py`) is an equal-weight panel of the three sleeves, bound to their member
hashes (edit any member ⇒ the pool forks). `arc/autonomy/pool.py` mirrors the single verdict's discipline
(one-shot, fail-closed, pre-committed sample size, deterministic-on-read) on the pooled common-support
stream. Pre-registration numbers committed NOW, before any forward data (`scripts/pre_register_pool.py`):

| param | value | derivation (fixed in advance) |
|---|---|---|
| n_trials | **72** | 69 cumulative component search + 3 pooling d.o.f. (membership, equal-weight, eval formula) |
| eval_at_n | **12** | `max(12, ceil(24 / K_eff=2.92))`; the 12-month CALENDAR FLOOR guards regime-thinness |
| dsr_min | **0.50** | same bar as the singles (NOT lowered) |
| forward_start | 2026-06-30 | inherited from the members; only later COMMON months count |

**Booked** (`bfe8ee59…`) and **honestly blocked today**: 0 common forward months, verdict REFUSES
(`HoldoutNotReadyError 0<12`). When all three sleeves have realized 12 common forward months (~2027-07),
the pool can reach a one-shot deflated verdict **~1 year sooner** than a single sleeve.

**The honest caveat, stated loudly:** pooling is a BET that *several* sleeves carry real, similarly-signed
edge. If one is noise, pooling DILUTES it. The pool is not evidence; it is a pre-registered hypothesis the
forward holdout will judge exactly once.

### Verdict hardening (degenerate-fatal)

Measuring exposed a latent gap in BOTH verdicts: a near-zero-variance forward stream yields an absurd,
non-finite Sharpe from numerical noise and would PASS. Both `promotion_verdict` and `pooled_verdict` now
treat a degenerate (near-zero variance or NaN) stream as a **FAIL** — a "too perfect" forward stream is a
red flag, never a pass. Not gameable (it only rejects degenerate inputs); real 12–24-month streams are
unaffected.

### The DI_5Y in-sample bottleneck (documented, NOT patched with synthetic data)

`ret_df` starts ~2012-01 (174 months) because `DI_5Y` has a ~25-month gap (2010-01→2012-01) and `belly`
(a core instrument) is dropna'd on it, so the WHOLE matrix — including front/long/hard's REAL 2010–2012
returns — is trimmed. Filling DI_5Y (curve interpolation) would recover ~25 in-sample months for the
sleeves' gate calibration. **But the forward verdict's inputs are unchanged**, so this is a
backtest-robustness improvement, **not** a forward-power lever — and injecting interpolated 5Y data into a
"real data" path to extend a backtest is exactly what the honesty law forbids. Recorded as a finding +
recommendation (source real DI_5Y for 2010–2012, or splice with an explicit flag), deliberately not wired.

---

## Honest bottom line

- The co-pilot lets the owner operate as a human-in-the-loop **without any power to corrupt the holdout** —
  the frozen stream stays byte-identical, the operator stream is the owner's real, immutable forward track
  record, and the breaker/baseline keep running underneath.
- The only honest way to a confident verdict **before 2028** is cross-sectional pooling, and it is now
  pre-registered (eval_at_n=12, ~1y sooner) — a bet the forward holdout will settle, not a claim.
- More history (in-sample or macro) does not accelerate the verdict; that null is reported as a null.
- 22 new tests, 387 green. Nothing promoted; the forward holdout remains the sole judge.

## Delivered
- `arc/autonomy/copilot.py`, `arc/autonomy/pool.py`; `OperatorDecision` + `operator.jsonl` and
  `reconcile_operator` in ledger/paper; `POOL_SPEC`/`POOL_HASH` in spec; degenerate-fatal hardening in
  `monitor.promotion_verdict`.
- `scripts/copilot.py`, `scripts/measure_statistical_power.py`, `scripts/pre_register_pool.py`.
- `tests/test_copilot.py` (13), `tests/test_pool.py` (9).
