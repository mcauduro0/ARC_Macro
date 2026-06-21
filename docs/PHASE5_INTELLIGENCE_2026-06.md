# Phase 5 (increment) — intelligence layer: uncertainty, confidence-sizing, meta-labeling (measured, honest)

A parallel batch (5-agent authoring workflow + engine measurement + integration) that builds the Phase 5
**intelligence infrastructure** — and, crucially, **measures whether it actually helps**, deflated and
in-sample, rather than asserting it does. The project's ruler stands: there is no demonstrated alpha beyond
carry; the three booked sleeves are candidates under forward paper. Phase 5 adds *machinery*, not a track
record. It also lands the `BOP_CURRENT` current-account data fix.

## The intelligence package (`arc/intelligence/`, pure + CI-native, 36 tests)

Every function is strictly point-in-time (expanding/trailing only) so it cannot leak; each module ships
adversarial as-of-invariance tests (a prediction at an interior point is byte-identical whether or not later
data exists, and "poisoning the future" cannot change a past value).

| module | functions | what it does |
|---|---|---|
| `uncertainty.py` | `predictive_vol`, `conformal_intervals`, `interval_confidence` | causal trailing vol; **split-conformal** prediction intervals (half-width = the (1−α) quantile of \|realized−pred\| over the *strictly past* calibration set, with the finite-sample +1 correction); width→confidence map |
| `sizing.py` | `confidence_scaled_position`, `inverse_vol_position` | resize an existing causal position by a causal expanding-percentile of confidence (bounded `[lo,hi]`), or by inverse predictive vol to a target (clipped) |
| `meta_labeling.py` | `meta_labels`, `meta_label_proba` | López de Prado meta-labels (was the primary bet's *sign* right?) + a causal expanding-window logistic that predicts P(correct) for **sizing** — never a side, never standalone alpha |

Tests: 14 (uncertainty) + 13 (sizing) + 9 (meta-labeling) = **36**, all CI-native (no engine, no network),
including learnability checks (meta-labeling separates correct/wrong on a real signal and clusters at 0.5 on
pure noise — no spurious confidence).

## The honest measurement (`scripts/measure_intelligence.py`)

For each booked sleeve it compares **FLAT** causal sizing against three intelligence variants, on the
*identical* costed return calc, scored by **deflated DSR** (leverage-invariant, so no "win" can come from
adding notional). A variant only "wins" if it beats FLAT by ≥ **+0.05** deflated DSR. In-sample only; the
forward holdout is untouched.

| edge | FLAT DSR | best variant | Δ deflated DSR | verdict |
|---|---|---|---|---|
| `momentum_front` | 0.532 | INVERSE_VOL | +0.000 | **no improvement** (CONFIDENCE_VOL even hurts, −0.39) |
| `nowcast_long` | 0.549 | **CONFIDENCE_VOL** | **+0.060** | **tentative** (Sharpe +0.227, maxDD −4.5%→−3.2%) |
| `fiscal_hard` | 0.140 | META | +0.015 | **no improvement** |

**Overall (honest):** sizing intelligence does **not** broadly improve the candidates. The one exception is
`nowcast_long` + conformal-width confidence scaling (deflated DSR 0.549 → 0.609, leverage-invariant) — a
**tentative, in-sample hypothesis to confirm on forward paper, not a result and not an alpha claim**. This is
the expected, disciplined outcome: the infrastructure exists and is measured, and we report the null where it
is null. (Report JSON: `server/model/output/measure_intelligence.json`.)

## Side-fix — `BOP_CURRENT` was the trade balance, now the current account (verified, not guessed)

`server/model/data_collector.py` mapped `BOP_CURRENT` → SGS **22707**, which is the **trade balance**
(balança comercial), not the current account. Corrected to SGS **22701** (Transações correntes – saldo,
monthly, USD mn, BPM6). Verification (value-level, not assumed):

- IPEADATA `PAN12_STC12` ("Transações correntes - saldo (BPM6)", Mensal, US$ mn, Bacen) is the target.
- Cross-referenced by **value**: SGS **22701** matches `PAN12_STC12` to the decimal across the last 14 months
  (e.g. 2026-04 = **−1764.7**, a deficit — correct for Brazil); SGS **22707** is *positive* (a surplus → trade
  balance); SGS 23079 is current-account **as % of GDP** (not USD mn) and was rejected. Confirmed live after
  the BCB SGS API recovered: `sgs.22701` returns −1764.7 for 2026-04.
- Corroborated in-repo: `server/model/data_collection.py:89` already maps `22701 → BOP_CURRENT_ACCOUNT`.

**Downstream (no refactor needed):** `bop_current` feeds `Z_bop` (rolling z — scale-invariant), the BEER
cointegration, and RealRateParityRStar Model 2 — all USD-mn-monthly, so scale is unchanged, but the
*meaning* improves (a usually-positive trade-balance series replaced by the usually-negative current account,
which is the external-vulnerability fundamental those features actually want). A data re-collection + feature
rebuild is warranted so those features reflect the corrected fundamental; the monthly accrual cycle's refresh
will pull it (BCB SGS is back up, so the canonical source is used).

## Honest bottom line

Phase 5 infrastructure is built, leakage-safe, and **measured**: no broad sizing edge, one tentative
in-sample nowcast hypothesis to carry into forward paper, and a real data-correctness fix to the current
account. No alpha claimed; the forward holdout remains the only promoter. 247 pytest green.

## Delivered

- `arc/intelligence/{uncertainty,sizing,meta_labeling}.py` + `__init__.py` exports; `tests/test_intelligence_{uncertainty,sizing,meta_labeling}.py` (36 tests).
- `scripts/measure_intelligence.py` (deflated, leverage-invariant FLAT-vs-intelligence comparison).
- `server/model/data_collector.py` — `BOP_CURRENT` 22707 → **22701** (verified current account).
