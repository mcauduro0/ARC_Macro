# P5 publication lag + gate hardening (refit-OOS CPCV & half-sample IC decay) — 2026-06

This round did two things the audit asked for, and the measurement turned up a third, more important
finding that changes the verdict on the overlay.

## 1. P5 — publication lag (look-ahead removal)

Macro series are indexed by their **reference month** but released weeks-to-months later. Using
`value[M]` at the close of month `M` is look-ahead: on 2020-03-31 you did *not* yet know March IPCA or
the January IBC-Br. `DataLayer.build_monthly` now shifts each lagged series forward by its real release
lag, behind `ARC_PUBLICATION_LAG` (default on):

| series | lag (months) | series | lag |
|---|---|---|---|
| `ipca_monthly` | +1 | `bop_current` | +1 |
| `ipca_yoy` | +1 | `ibc_br` | +2 |
| `debt_gdp` | +1 | `reer` | +1 |
| `primary_balance` | +1 | `tot` | +1 |

Real-time market series (PTAX, DI, swaps, CDS, EWZ, VIX, USTs) are **not** shifted. Focus expectations
(`ipca_exp`) are survey-dated and already point-in-time, so they are not shifted either.

Test: `tests/test_publication_lag.py` (guarded — needs xgboost/hmmlearn + collected data) confirms a
lagged series (`ibc_br`) equals `shift(2)` of the unshifted series and a real-time series (`ptax`) is
byte-identical with the toggle on/off.

## 2. Gate hardening — refit-OOS CPCV

`arc.eval.gate.refit_oos_cpcv(X, y)` runs a **true** out-of-sample combinatorial purged CV: for each
purged/embargoed split it **re-fits** a closed-form standardized ridge (numpy-only, so the gate stays
dependency-light and CI-safe) on the train rows and predicts the held-out rows. Unlike `cpcv_ic` — which
splits already-computed predictions and therefore inherits whatever the upstream fit did — this re-fits
inside every fold, so it probes model overfitting / period-concentration. It still **cannot** detect a
leak baked into the feature *values* themselves; only as-of-invariance tests catch that.

Tests in `tests/test_gate.py` confirm it recovers a genuine linear signal (OOS IC > 0.2) and rejects
pure noise (|IC| < 0.15).

## 3. The decisive measurement — P5 did NOT fix the IC decay

The hypothesis going in: P5 should knock down the implausibly high early-period IC (the H1≫H2 decay that
is the contamination signature). **It did not.** Half-sample carry-neutralized IC, P5-off (PR#14) vs
P5-on (this run):

| instrument | cnIC **H1** off→on | cnIC **H2** off→on |
|---|---|---|
| front | 0.745 → **0.801** | 0.186 → 0.241 |
| belly | 0.514 → **0.657** | 0.108 → 0.187 |
| long  | 0.574 → **0.593** | 0.095 → 0.137 |
| hard  | 0.690 → **0.725** | 0.287 → 0.337 |

The first-half inflation is intact — if anything slightly higher. Publication lag is a correct fix *in
principle* (it removes real look-ahead), but it is **not the driver** of the implausible IC. The
contamination lives in the **features themselves**, not in the publication timing. (Likely suspects for a
follow-up as-of-invariance pass: full-sample normalizations / cointegration betas / interpolations in the
valuation block — `ppp_factor` interpolation, BEER/Balassa-Samuelson betas, the equilibrium r* composite.
Not yet proven; that is the next investigation, not a claim.)

## 4. The gate gave a FALSE PASS — and now it does not

With P5 on, the *old* gate returned **PASS**: overlay Sharpe(ann)=1.31, DSR=0.997, mean carry-neutral
IC=0.370 (t=9.19), worst CPCV IC=−0.078. Every existing check is blind to the half-sample decay:

- `cpcv_ic` is **post-hoc** — it splits the already-contaminated predictions, so it inherits the leak.
- mean carry-neutral IC and its t-stat are **dominated by the inflated H1**.
- DSR deflates against trial count, but the in-sample Sharpe is genuinely high *because* of the
  contaminated first half.

A gate that passes contaminated alpha is worse than no gate. So this round adds the missing check:

**`half_sample_carry_neutral_ic(pred, realized, carry)`** computes the carry-neutralized IC on the first
vs second half (chronological, residualized within each half) and reports `{full, h1, h2, drop}`.
`promotion_report` aggregates the per-instrument median and **FAILs** when
`median(cnIC_H1 − cnIC_H2) > GateThresholds.ic_decay_drop_max` (default **0.15**). Rationale: a genuine,
stationary edge has H1 ≈ H2; a steep drop means the model looked brilliant when most of the sample lay in
its "future" and decays to its honest level once that look-ahead is exhausted.

Re-scoring the frozen `gate_diagnostics.json` through the hardened gate:

```
PASSED: False
median cnIC  H1=0.657  H2=0.187  decay=0.456
reasons:
  - carry-neutral IC decays 0.456 from first to second half (H1=0.657 -> H2=0.187, max 0.15)
    — non-stationary skill is the contamination signature, not edge
```

The gate now correctly **FAILs** the overlay. That is the honest, expected outcome.

## What this means

- **The overlay is not promotable.** Its apparent edge is concentrated in the early sample and decays ~3–4×
  out of it. Until an as-of-invariance pass on the feature block removes the residual look-ahead, the
  measured IC cannot be trusted as alpha.
- **The measurement infrastructure is now harder to fool.** The gate has three independent OOS lenses:
  post-hoc CPCV stability, refit-OOS CPCV (re-fit inside folds), and half-sample decay. The decay lens is
  the one that caught this case.
- refit-OOS coverage is data-limited: with the per-instrument feature maps + complete-case requirement,
  only `hard` had enough rows (mean OOS IC 0.327 — itself a flag worth chasing). Thresholds were relaxed
  (coverage 36→24, min obs 40→30) so more instruments run when data allows; the limitation is logged, not
  hidden.

## Files

- `server/model/macro_risk_os_v2.py` — `build_monthly` publication-lag shift (`ARC_PUBLICATION_LAG`).
- `arc/eval/gate.py` — `refit_oos_cpcv`, `half_sample_carry_neutral_ic`, `GateThresholds.ic_decay_drop_max`,
  decay check wired into `promotion_report`.
- `arc/eval/__init__.py` — exports.
- `scripts/promotion_gate.py` — prints H1/H2 + decay, runs per-instrument refit-OOS (relaxed coverage).
- `tests/test_gate.py` — refit-OOS + half-sample-decay tests; `tests/test_publication_lag.py` — P5 shift.
