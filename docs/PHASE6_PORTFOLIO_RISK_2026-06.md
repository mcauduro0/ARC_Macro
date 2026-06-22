# Phase 6 — portfolio & risk SOTA (VaR/ES, DCC-GARCH covariance, Black-Litterman, paper-fill execution) + online selection

A massive parallel batch (6-agent authoring workflow + engine measurement). Builds the Phase 6 risk/portfolio/
execution infrastructure — and the deferred Phase 5 online-feature-selection item — as **pure, causal,
CI-tested, MEASURED** modules. Net: solid SOTA tooling (84 new tests), and the honest measurements say what
they should — **EQUAL weight and BATCH selection remain the baselines; no scheme clears the deflated bar.**
No alpha claimed; the forward holdout still decides.

## What was built (all pure, leakage-safe, CI-native)

| module | contents | tests |
|---|---|---|
| `arc/risk/var_es.py` | historical / parametric / Cornish-Fisher VaR + ES; `portfolio_var`; `pretrade_var_gate` (positive-loss convention; ES ≥ VaR; monotone in α) | 16 |
| `arc/risk/covariance.py` | RiskMetrics `ewma_cov`; `garch11_vol` (QMLE, variance-targeting); Engle `dcc_correlation` (1,1); `dcc_garch_cov` — all causal one-step forecasts, PSD-repaired, EWMA fallback | 19 |
| `arc/portfolio/black_litterman.py` | `implied_equilibrium_returns` (reverse opt); `black_litterman_posterior` (Idzorek-default Ω); `bl_optimal_weights` | 17 |
| `arc/execution/paper_fill.py` | order FSM (NEW→WORKING→PARTIAL→FILLED/…); `PaperFillSimulator` (next-price + slippage, liquidity-capped, costed); `realized_vs_paper` drag | 21 |
| `arc/intelligence/online_selection.py` | `rolling_elasticnet_importance`, `rolling_stability_selection`, `online_selected_mask` — causal rolling selection | 11 |

All are strictly point-in-time (causality verified by "poison-the-future" canaries), with closed-form test
cases (e.g. parametric VaR(0,1,5%)≈1.645, ES≈2.063; covariance PSD; BL no-views ⇒ posterior == prior).

## Honest measurements

**Portfolio construction (`scripts/measure_portfolio_risk.py`)** — combine the 3 booked sleeves, causal rolling
cov forecasts, deflated DSR (n_trials=3), leverage-invariant, +0.05 win bar:

| scheme | Sharpe | DSR | Δ deflated DSR vs EQUAL | maxDD |
|---|---|---|---|---|
| **EQUAL** | 0.780 | 0.986 | — | −2.10% |
| MIN_VARIANCE (EWMA) | 0.776 | 0.965 | −0.020 | −0.99% |
| **BLACK_LITTERMAN (EWMA)** | **0.940** | 0.992 | **+0.006** | −1.02% |
| MIN_VARIANCE (DCC) | 0.805 | 0.975 | −0.011 | −1.60% |
| BLACK_LITTERMAN (DCC) | 0.825 | 0.967 | −0.019 | −1.25% |

**Verdict: no scheme beats EQUAL on deflated DSR by the margin.** Black-Litterman (EWMA) lifts the *Sharpe*
(0.94 vs 0.78) and cuts drawdown, but the deflated-DSR gain (+0.006) is below the bar — construction tooling,
not demonstrated edge. EQUAL remains the baseline.

**Risk & realism tooling (same script):** EQUAL-book 95% monthly VaR ≈ 0.87%; `pretrade_var_gate` correctly
breaches at a tight limit (200% utilization) and passes at a loose one (50%); `PaperFillSimulator` at 2 bp
slippage + 2 bp cost shows ~0.08%/yr execution drag on the EQUAL book's rebalancing turnover (gross turnover
24.3). These are risk limits + fill realism, not alpha.

**Online feature selection (`scripts/measure_online_selection.py`)** — ONLINE vs BATCH on `long`, carry-neutral
IC, deflated for the feature-search count: **NO improvement** (best ONLINE Δ deflated-IC +0.000 < 0.03; ONLINE
raw cnIC 0.117 but H1 0.28 ≫ H2 0.07 = non-stationary; it churns the selected set and adds estimation noise).
BATCH (the optimistic full-sample baseline) stays the reference. Online *feature* selection adds no measured value.

## Honest bottom line

Phase 6 is delivered: VaR/ES gates, DCC-GARCH forward-looking covariance, Black-Litterman, and a paper-fill
execution simulator — all leakage-safe and CI-tested — plus the online-selection item closed out. Every
measurement returns the disciplined result: **the baselines (EQUAL weight, BATCH selection) are not beaten on
the deflated bar.** That is the system working: it builds real institutional plumbing without manufacturing an
edge. 367 pytest green. Promotion still happens only through the forward holdout.

## Delivered

- `arc/risk/{var_es,covariance}.py`, `arc/portfolio/black_litterman.py`, `arc/execution/paper_fill.py`,
  `arc/intelligence/online_selection.py` (+ package `__init__` exports) + 5 CI test files (84 tests).
- `scripts/measure_portfolio_risk.py`, `scripts/measure_online_selection.py`.
