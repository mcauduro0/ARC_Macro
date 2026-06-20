# Cross-Refit Regime Repaint — Fix + a Hypothesis the Data Refuted (read skeptically)

**Date:** 2026-06-19
**TL;DR:** We fixed the verified cross-refit "repaint" leak (a-priori labeling + append-only
`regime_probs`), and the cross-refit as-of-invariance test now passes. **But the fix did NOT reduce
the IC** — and a second, stricter experiment (refit θ every step, strictly causal) **also** left the
IC unchanged. So the regime IC inflation is **not** θ-vintage look-ahead. The data refuted the prior
"leakage-dominant" hypothesis. The IC is a **period-concentrated regime-timing effect** (strong
2015–2020, fades after) that correctly **fails the gate**. Carry remains refuted; publication-lag
(P5) is the one untested contributor left.

---

## 1. The fix (correctness, verified)

The adversarial review (docs/REGIME_AND_DEGENERATE) proved the 12-month HMM refit **repainted the
past**: it recomputed the entire `regime_probs` history with the new vintage's θ and a full-window
Viterbi state→regime relabeling, so a later refit moved truly-past regime probabilities (canary:
past-date `P_stress` moved ~0.5 between asof-2017 and asof-2020). That contaminates the training
feature history. Fix (toggle `ARC_REGIME_POINT_IN_TIME`, default on), in `_fit_hmm`/`fit`:

1. **A-priori labeling** — label carry/stress/riskoff by the HMM's **fitted `means_`** on the
   indicator column (lowest = carry … highest = riskoff), not a full-window Viterbi pass. Label
   identity depends only on θ, so it cannot be chosen with hindsight and is stable across refits.
2. **Append-only `regime_probs`** — each date is written once (at the first refit reaching it) and
   never overwritten by a later vintage.

**Acceptance test** (`tests/test_regime_pointintime.py`, the one the leaf-level
`test_regime_filtered.py` missed because it held θ fixed): fit at asof=A2 must not change
`regime_probs[t]` for any t ≤ A1. **Passes** — past dates are byte-for-byte invariant
(Δ < 1e-9); the legacy path repaints them (Δ > 1e-3).

---

## 2. The surprise: the fix did not move the IC

Gate with the fix on (refit interval 12, 138 months):

| | mean carry-neutral IC | DSR | worst CPCV IC | verdict |
|---|---:|---:|---:|:--|
| before (repaint present) | 0.310 | 0.74¹ | −0.143 | FAIL |
| after (cross-refit fix) | **0.348** | 0.76 | −0.142 | FAIL |

¹ after the separate DSR units fix. The IC did not fall; `front` even rose (0.37 → 0.46).

**The contamination signature (IC decay by half-sample) persists** with the fix:

| inst | IC all | IC H1 (2015–20) | IC H2 (2020–26) |
|---|---:|---:|---:|
| front | 0.454 | 0.745 | 0.186 |
| belly | 0.255 | 0.514 | 0.108 |
| long | 0.334 | 0.574 | 0.095 |
| hard | 0.454 | 0.690 | 0.287 |
| fx | 0.243 | 0.388 | 0.003 |

---

## 3. The decisive experiment: strictly-causal θ every step

If the residual leak were the **within-block θ** (append-only still appends each 12-month block with
the block-end θ) or the initial in-sample fit, then refitting θ **every step** (expanding window, each
date scored with θ fit only on data up to it) should drop the IC. It did **not**:

| | mean IC | front H1/H2 | belly H1/H2 | hard H1/H2 |
|---|---:|---:|---:|---:|
| refit every 12m (committed) | 0.35 | 0.745 / 0.186 | 0.514 / 0.108 | 0.690 / 0.287 |
| refit **every step** (expanding) | 0.39 | 0.728 / 0.200 | 0.700 / 0.150 | 0.755 / 0.270 |

**Two independent strictly-causal regime implementations both preserve the IC and the H1≫H2 decay.**
That is strong evidence the IC is **not** a θ-vintage look-ahead. This **refutes** the prior
adversarial hypothesis ("leakage-dominant", conf 0.78) — the repaint was real but is **not** what
inflates the IC. (A good reminder that an empirical test beats a confident reasoned argument.)

---

## 4. What the IC actually is

The global regime is fit on **market observables** (VIX, DXY, UST, HY, commodities, EWZ) whose
month-end values are known at the decision time, so the regime feature at t is causal. A causal
risk-on/risk-off state legitimately carries some predictive power for next-month rates/FX returns
(risk-premium timing). The IC is **strongly period-concentrated**: large in the 2015–2020
high-volatility era (impeachment, recession, COVID) and small/zero afterward. That is exactly what
the gate flags:

- **DSR 0.76 < 0.95** — does not survive deflation against 30 trials.
- **worst purged-fold IC −0.142** — period-concentrated, not stationary.
- **IC decays H1 ~0.6–0.7 → H2 ~0.1–0.2** — the honest forward-looking estimate is the H2 level.

So this is best read as **in-sample-overfit / non-stationary regime-timing**, not promotable alpha —
**not** carry (refuted: carry-neutral IC ≈ raw IC) and **not** θ look-ahead (refuted by §3). `hard`
holds up best (H2 IC 0.27, CPCV min +0.28) and remains the only plausible genuine residual.

---

## 5. Verdict & next

- **Keep the cross-refit fix** — it is a correctness improvement (proven repaint removed; invariance
  test green) even though it did not change this IC. a-priori labeling also removes label-flip risk.
- **Do not change the refit cadence** — strictly-causal per-step θ gives the same result at much
  higher cost; the 12-month cadence + append-only is sufficient (its residual within-block θ is
  empirically immaterial).
- **Honest IC ≈ the H2 / late-period value (~0.1–0.2), not the in-sample-inflated H1.** The system
  still has **no deflation-surviving, stationary edge**; the gate's FAIL stands.
- **Next:** (a) gate hardening — **refit-OOS CPCV** (re-fit the alpha model inside each fold) to
  characterize period-concentration properly; (b) **P5 publication-lag** — the one untested leak
  suspect (ipca/ibc/debt entering `selic_star` and Z-features at their reference month rather than
  their release date); (c) regime-conditional sizing only if a genuinely stationary signal emerges
  under refit-OOS validation.
