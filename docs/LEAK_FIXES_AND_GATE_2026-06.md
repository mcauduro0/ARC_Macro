# Remaining Leak Fixes + Promotion Gate — Measured Impact (read skeptically)

**Date:** 2026-06-19
**TL;DR:** With the three remaining feature leaks fixed and a proper promotion gate applied, the
suspicious forward-target edge **collapses**. Overlay Sharpe falls from **3.91 → 0.15**, belly IC from
**0.64 → 0.06**, long IC from **0.63 → −0.09**; the mean **carry-neutralized IC is −0.03** and the
overlay's **Deflated Sharpe is ~0**. The gate verdict is **FAIL**. This is the audit thesis confirmed:
the apparent alpha was carry-dominance plus leakage, not skill.

---

## 1. What was fixed (the three remaining leaks)

All three are merged behind env toggles (default = fixed) so the impact is measurable and reversible.

| audit id | leak | fix | toggle |
|---|---|---|---|
| **regime-1** | HMM fed **smoothed** posteriors `P(s_t \| o_1..o_T)` (forward-backward conditions each month on the *future*) as a historical feature | use **filtered** posteriors `P(s_t \| o_1..o_t)` — `arc.regime.filtered_posteriors` (log forward recursion; prefix-invariant) | `ARC_HMM_FILTERED` |
| **feat-3** | feature matrix built with **unbounded** `ffill()` — a stale/discontinued series masquerades as fresh for years | **bounded** ffill (cap = `ARC_FFILL_LIMIT`, default 12 months), per-column lag-aware — `arc.features.bounded_ffill` | `ARC_BOUNDED_FFILL` |
| **eq-1/eq-3** | composite r\* rebuilt by applying the **as-of date's regime** to ALL history → the r\* feature at month t used a later month's regime classification | **causal per-date** weights: each month's r\* uses the regime probs **at that month** — `CompositeEquilibriumRate.compute_causal` | `ARC_CAUSAL_RSTAR_REGIME` |

regime-1 and eq-1/eq-3 compound: filtered regime probs make `regime_probs_df[t]` point-in-time, and
`compute_causal` then consumes them per-date — so the whole r\* feature becomes causal.

Each fix has a leakage/causality unit test: `tests/test_regime_filtered.py` (filtered is
prefix-invariant, smoothed is not), `tests/test_bounded_ffill.py`, `tests/test_equilibrium_causal.py`
(as-of invariance of causal r\*, and the legacy path's *non*-invariance pinned as contrast).

---

## 2. The promotion gate (`arc.eval.gate`)

A single PASS/FAIL ruler that refuses to be flattered by an in-sample number. It composes:

- **carry-neutralized IC** — IC of the prediction vs realized *after regressing carry out of both*.
  If the IC collapses once carry is removed, the "edge" was carry.
- **carry-only benchmark** — a cross-sectional carry-weighted return stream and per-instrument carry
  IC. The overlay must beat pure carry.
- **CPCV IC** — IC across combinatorial purged folds (mean / worst-fold), to expose
  period-concentration.
- **Deflated Sharpe (DSR) / PSR** on the overlay returns, deflated by the **real trial count** (30 —
  the audit's documented re-scored tuning iterations).
- **PBO** — computed only when a per-config trial-return matrix is supplied (otherwise reported N/A,
  not faked).

Runner: `scripts/promotion_gate.py` — one backtest with all causal fixes ON + `ARC_DUMP_DIAGNOSTICS=1`,
feeding the per-instrument (prediction, realized forward return, decision-time carry) panels into the
gate. Report: `server/model/output/promotion_gate_report.json`.

---

## 3. Result — all leaks fixed, gate applied

Live data snapshot, backtest 2015–2026 (overlay active 67 months; per-instrument IC over 138 months).

**Overlay (deflated):**

| metric | value | read |
|---|---:|---|
| Sharpe (annualized) | **0.15** | collapsed from 3.91 |
| PSR vs 0 | 0.64 | not significant |
| **Deflated Sharpe (vs 30 trials)** | **≈ 0.000** | does **not** survive selection bias |
| carry-only Sharpe (benchmark) | 0.01 | overlay barely above zero-carry |

**Per-instrument IC (forward, all leaks fixed):**

| instrument | IC | carry-neutralized IC | carry-only IC | CPCV mean / worst |
|---|---:|---:|---:|---:|
| front | −0.174 | −0.078 | −0.081 | −0.103 / −0.359 |
| belly | **+0.059** | +0.042 | +0.033 | +0.073 / −0.140 |
| long | −0.093 | −0.067 | +0.012 | −0.107 / −0.389 |
| fx | n/a | n/a | +0.198 | — |
| hard | n/a | n/a | +0.065 | — |

- **Aggregate carry-neutralized IC = −0.034** (t = −1.89). The signal adds **nothing beyond carry**;
  if anything it is marginally negative.
- **fx and hard report IC = NaN**: their alpha models emit **near-constant predictions** (degenerate),
  so the correlation is undefined. That is itself a finding — those sleeves are not producing a signal,
  only carry (fx carry-only IC +0.198 is the cupom-cambial carry, not skill).

**Gate verdict: FAIL.** Reasons: DSR ≈ 0 < 0.95; mean carry-neutralized IC −0.034 < 0.02; carry-neutral
IC t −1.89 < 2.0; worst purged-fold IC −0.389 (period-concentrated).

---

## 4. Before / after — controlled attribution of the three fixes

Same run, same data, same code; only the three new toggles flipped (forward-target and causal-winsorize
held ON in both). Source: `scripts/measure_leak_fixes.py`.

| metric | baseline (leaks present) | fixed | delta |
|---|---:|---:|---:|
| overlay Sharpe | 3.91 | **0.13** | −3.78 |
| overlay total return | 270.3% | **2.8%** | −267pp |
| overlay max drawdown | −1.29% | −5.42% | −4.13pp |
| overlay win rate | 86.6% | 46.3% | −40.3pp |
| mean IC | 0.417 | **0.011** | −0.406 |
| belly IC | 0.639 | **0.091** | −0.548 |
| long IC | 0.626 | **−0.064** | −0.690 |
| front IC | −0.013 | 0.007 | +0.020 |

The three leaks accounted for **essentially the entire** implausible edge: belly IC 0.64 → 0.09, long
IC 0.63 → −0.06, mean IC 0.42 → 0.01, overlay Sharpe 3.91 → 0.13. This is a same-run, same-data
controlled experiment — the cleanest possible attribution. (Run-to-run variation is small except for
`front`, whose ~1.3% annual vol makes its tiny predictions noisy; the gate run reported front IC −0.17
vs +0.01 here — both ≈ no signal.)

For reference, the prior documented state with these leaks **present** (forward-target ON,
`docs/FORWARD_TARGET_2026-06.md`): belly IC **0.639**, long IC **0.626**, mean IC **0.417**, overlay
Sharpe **3.91**. After the fixes (gate run above): belly IC **0.059**, long IC **−0.093**, overlay Sharpe
**0.15**. The implausible 0.6+ IC was leakage + carry, exactly as flagged.

---

## 5. Verdict

The forward-target fix was methodologically correct but its eye-popping uplift was an artifact. With the
remaining leaks removed and the honest ruler applied, **there is no demonstrated signal alpha beyond
carry** in the current configuration. The system should be treated as **carry-harvesting** until a
genuinely orthogonal signal is built and **passes this gate** (carry-neutralized IC with a positive
t-stat, overlay Sharpe that survives DSR and beats carry-only after costs).

This is the measurement layer working as designed: it deflated a beautiful backtest to the truth.

**Next (to build real edge, not chase the artifact):** (a) fix the regime `dropna`-global data
alignment (diagnostic P6 — `us_hy_spread` starting 2023 collapses the global HMM to uniform priors
pre-2023; per-series alignment instead); (b) give fx/hard non-degenerate signals or drop them from the
overlay; (c) only then search for orthogonal-to-carry predictors, gated by `arc.eval.gate`.
