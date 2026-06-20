# Phase 4 — honest edge search (2026-06)

With the ruler trustworthy (arc.eval) and the feature pipeline proven point-in-time (Phase 3), the
money question: **is there any signal, orthogonal to carry, that is predictive out of sample and
stationary?** The audit thesis says the historical edge was carry + non-stationary regime-timing.
Phase 4 tests that directly — and confirms it.

## Method (honest by construction)

`arc/research/signals.py` evaluates one candidate (a single feature → one instrument's forward return)
through the full gate battery:

- **carry-neutralized IC** — predictive power beyond carry (against the instrument's TRUE return-carry).
- **half-sample H1/H2** — the bar is the SECOND half (~0.10), not the inflated first half; a steep
  H1→H2 drop is non-stationary, not edge.
- **refit-OOS CPCV** — re-fit a ridge on the single feature inside each purged fold (true OOS IC; sign
  learned in-fold). Primary edge metric.

We **pre-register** ~5 economically-motivated single-feature hypotheses per instrument (25 total) —
deliberately NOT screening all 58 features (that is data mining) — and deflate for the count tested.
Uses the PIT `feature_df` from `initialize()` (no 25-min walk-forward).

## Result: zero survivors

**All 25 pre-registered signals FAIL the gate.** The failures cluster exactly as the audit predicted:

- **Carry in disguise** (carry-neutral IC collapses): `hard/Z_cds_br`, `fx/reer_gap`, `fx/Z_tot`.
- **Non-stationary** (H1 ≫ H2): `belly/Z_rstar_composite` (H1 +0.27 → H2 +0.02), `belly/Z_term_premium`,
  `fx/beer_misalignment` (+0.40 → +0.08), `fx/Z_iron_ore`, `long/Z_debt_accel`, `front/term_premium_slope`.
- **No robust OOS** (worst purged fold deeply negative): most of the rest.

The closest miss was `fx/val_fx` (carry-neutral IC +0.25, H2 +0.08, refit-OOS +0.11) — but its worst
purged fold is −0.11, below the −0.10 robustness floor. Marginal, **not promotable**.

**There is no demonstrated stationary alpha beyond carry in the current feature set.** That is the
honest, expected verdict — and it is what the gate is for.

## A gate-integrity defect found and fixed

The one apparent survivor — `hard/Z_cds_br`, which looked excellent (carry-neutral IC +0.16, H2 +0.28
> H1, refit-OOS +0.22 with every fold positive) — was a **false positive from a carry-mismatch bug**:

- The `hard` sovereign-spread return earns the **spread carry** (`embi/10000/12`).
- But the engine's `carry_hard` feature is the **cupom cambial (FX carry)** (`macro_risk_os_v2.py`
  ~1135–1143: the comment says "spread level / 12" but the code uses the swap DI×Dólar rate). Its
  correlation with sovereign signals is ~0, so neutralizing `hard` against it does nothing.
- Neutralizing `Z_cds_br` against the **correct spread carry** collapses its carry-neutral IC from
  **+0.161 to −0.045** — the "edge" was the signal (CDS level, corr 0.48 with the spread carry)
  predicting the carry component of the return. Pure carry, not alpha.

This defect overstated `hard` everywhere it was carry-neutralized against `carry_hard` — including the
**promotion gate** (where `hard` carry-neutral IC read +0.47). It retroactively explains why `hard`
always looked like "the most plausible residual edge." Fixed in `scripts/signal_research.py` and
`scripts/promotion_gate.py` (both now neutralize `hard` against its spread carry). The engine feature
`carry_hard` itself (used as an alpha-model input) is left unchanged here — correcting it changes the
backtest and is a separate, measured follow-up.

## Delivered

- `arc/research/signals.py` + `arc/research/__init__.py` — `evaluate_signal`, `rank_signals`,
  `SignalThresholds`.
- `tests/test_signal_research.py` (CI-native) — genuine signal passes; noise, carry-in-disguise, and
  first-half-only all fail.
- `scripts/signal_research.py` — the pre-registered screen (correct per-instrument carry).
- `scripts/promotion_gate.py` — `hard` carry corrected to spread carry.

## Implication for the roadmap

The leakage hunt is exhausted and the signal search is honest: **no gated edge beyond carry yet.** The
next moves are genuine model/data improvements, each gated the same way: a nowcast/DFM to kill the
IBC-Br 2-month blindspot, regime-conditional signals, and richer data (ANBIMA real curve, positioning,
flows). And the autonomy layer (Phase 7) remains the biggest structural gap. No edge will be claimed
until it clears this gate — including the corrected carry.
