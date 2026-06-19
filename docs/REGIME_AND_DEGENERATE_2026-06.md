# HMM Bottleneck (P6) + Degenerate fx/hard Models — Fixes & a Leak They Exposed (read skeptically)

**Date:** 2026-06-19
**TL;DR:** Two correctness fixes (per-series alignment for the global HMM, and per-series feature
coverage for the alpha models) make the regime model and the fx/hard sleeves actually work. They are
causal and correct. But turning them on **raises the backtest IC from 0.01 → 0.36**, and adversarial
verification proved that jump is **largely a pre-existing look-ahead "repaint" leak the fixes
*exposed*, not new alpha** — concentrated in the regime→r\* feature channel. Carry is refuted; `hard`
is the only plausible genuine residual. The gate still FAILS. The fixes are committed as
correctness improvements; the 0.36 IC is **not** a track-record claim.

---

## 1. The two fixes

| audit id | bug | fix | toggle |
|---|---|---|---|
| **P6** | `_fit_hmm` did a **global** `pd.DataFrame(obs_dict).dropna()`; `us_hy_spread` (starts 2023) deleted every pre-2023 row → the global HMM collapsed to **uniform priors** for most of history | per-series coverage selection: keep observables with ≥60 obs in the as-of window, then dropna on that subset (causal — judged only on data ≤ asof) | `ARC_REGIME_PER_SERIES` |
| **fx/hard degeneracy** | the alpha-model `X.dropna()` is also global; `Z_hy_spread` (8 months) sits in fx's & hard's `FEATURE_MAP` → complete-case rows collapsed to **8** (< 36 floor) → fx/hard **silently skipped**, `mu` defaulted to **exactly 0** for all 138 months | `_select_covered_features`: drop features with < (training-floor) coverage before the complete-case dropna (causal) → fx 80 rows, hard 109 rows → they fit | `ARC_FEAT_PER_SERIES` |

Both slice `.loc[:asof_date]` **before** selecting columns and measure coverage only on the as-of
window, so they are point-in-time. Same global-`dropna` disease the audit flagged; same per-series
cure. Unit tests: `tests/test_feature_coverage.py`, plus the P6 smoke check (global probs vary
pre-2023, std ≈ 0.45 not uniform 0.33).

---

## 2. Controlled measurement (same data/code, only these two toggles flipped)

Source: `scripts/measure_hmm_degenerate.py` (all earlier causal fixes held ON in both runs).

| metric | baseline (off) | fixed (on) | delta |
|---|---:|---:|---:|
| overlay Sharpe | 0.13 | 0.81 | +0.68 |
| overlay total return | 2.8% | 106.3% | +103pp |
| overlay max drawdown | −5.4% | **−12.8%** | worse |
| mean IC | 0.011 | **0.360** | +0.348 |
| per-instr IC | front .007 / belly .091 / long −.064 (fx,hard skipped) | fx .41 / front .39 / belly .29 / long .20 / hard .52 | — |

A monthly IC of 0.36 is implausible → red flag → ran the gate + an adversarial verification.

---

## 3. Gate verdict (with a units bug fixed) + what the verification found

`scripts/promotion_gate.py`, all fixes ON, 138 months → **FAIL**.

- **mean carry-neutralized IC = 0.31, t = 9.72**; per-instrument carry-neutral ≈ raw IC; carry-only
  IC tiny (front −0.08, belly 0.03, long 0.01). → **carry is conclusively refuted** (neutralizing
  carry barely moves the IC).
- **DSR units bug fixed.** The gate deflated a *per-period* Sharpe (0.24/mo) with `sr_std=1.0` in
  per-period units → an impossible E[max Sharpe] ≈ 2.07/period (~7.2 ann.) → DSR ≈ 0 (a spurious
  FAIL). Fixed: `sharpe_stats` now defaults `sr_std` to the **Lo (2002) per-period Sharpe SE**
  `sqrt((1+sr²/2)/n)` (≈ 0.086 here). **Corrected DSR = 0.74** (PSR vs 0 = 0.994). Still < 0.95 for
  30 trials, and worst purged-fold IC = −0.143 → **FAIL stands, now for a meaningful reason.**
  (Regression test: `tests/test_gate.py::test_sharpe_stats_auto_sr_std_is_per_period_not_annual`.)

**Adversarial verification (3 diverse lenses + synthesis) — verdict: "mixed, leakage-dominant"
(conf. 0.78).** Evidence the verifier produced directly:

1. **Vintage canary (the proof).** Refitting the HMM as-of 2017 vs as-of 2020 **changes the regime
   probabilities at truly-past dates** (≤ 2017): `P_stress` mean |Δ| = **0.51**, max 1.0, median 0.81
   on moved months. The 12-month **refit relabels and recomputes the entire past**. Our
   `arc/regime/filtered.py` guarantees prefix-invariance only for a **fixed** model — it does **not**
   cover the refit.
2. **Propagation.** `rstar_regime_signal` (in every instrument's `FEATURE_MAP`) is non-invariant at
   past dates (mean |Δ| 0.36, 68% of past months move) → the repaint enters all 5 models' **training
   history** (`feat_df.loc[:asof]`).
3. **Smoking gun — IC decays by half-sample:** front +0.72→+0.03, belly +0.47→−0.02, long
   +0.54→−0.09, hard +0.76→+0.18; carry-only IC does **not** decay → the decay is specific to the
   model's predictions = the contamination signature.
4. **Mitigating bound.** The *live* decision reads `get_probs_at(asof)` = the causal as-of endpoint;
   the leak contaminates the **training** rows (repainted past), not a first-order decision-time peek.
   Hence "mixed," not pure leakage.
5. `hard` is the only genuine-edge candidate (2nd-half IC +0.178, CPCV min +0.153, fewest regime
   features, negative pred–carry corr).

**The mechanism is pre-existing** (the refit-then-rebuild-history structure predates this work);
P6 merely **activated** the dormant regime channel that carries it — the same pattern as the
forward-target fix exposing earlier leaks.

---

## 4. A limitation this exposed in the gate

The gate detects **carry** (neutralization) and **overfitting** (DSR/PBO/CPCV) — but **not**
look-ahead leakage directly. A leaky-but-not-carry, not-obviously-overfit signal can post a high
carry-neutral IC. Here the **worst-CPCV-IC guard (−0.143)** and the **implausibility of IC 0.31/mo**
caught it; in general the defense against look-ahead is an **as-of-invariance test on the actual
feature pipeline**, which we have for the leaf transforms but **not yet for the regime refit path**.

---

## 5. Next fix (precise, with an acceptance test)

1. **Make the regime feature append-only / point-in-time across refits.** Write `regime_probs[t]`
   once (at the first refit with asof ≥ t) and never overwrite it with a later vintage.
2. **Pin the label map a-priori** (e.g. lowest fitted-VIX state = carry) instead of full-window
   Viterbi `state_means`; z-score HMM inputs with a **trailing rolling** window, not full-window
   mean/std.
3. **Propagate** so `rstar_regime_signal` inherits the frozen-past values.
4. **Acceptance test (decisive):** a cross-refit as-of-invariance assertion — fit at asof=T and
   asof=T+k, assert `get_probs_at(t)` **and** `rstar_regime_signal[t]` are identical for all t ≤ T.
   (`tests/test_regime_filtered.py` misses this because it holds θ fixed.)
5. **Then re-run the gate** and compare first-half vs second-half IC. If the early-strong/late-dead
   decay disappears and IC stabilizes near the 2nd-half values (~0.0–0.18), leakage is confirmed and
   the headline IC must be restated to the online number. If belly stays ~0.25+, the edge survives.
6. **Gate hardening:** replace the post-hoc IC-stability CPCV with a **refit-OOS CPCV** (re-fit the
   alpha model inside each fold) so it can detect upstream parameter-vintage leakage.

---

## 6. Verdict

The P6 and fx/hard fixes are correct and committed. But the IC they reveal (0.36 raw / 0.31
carry-neutral) is **largely a refit-vintage regime repaint leak**, not alpha — carry is refuted, the
DSR FAIL was a units bug (now fixed; real DSR 0.74), and the IC decays out of sample. Only `hard`
shows a plausible residual. **Do not promote; do not treat 0.31/t=9.72 as a track record** until the
append-only/frozen-label regime fix + the cross-refit invariance test land. The honest-measurement
layer did its job: it caught a leak that a beautiful 106%-return backtest would otherwise have sold.
