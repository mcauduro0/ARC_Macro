# Phase 5b — forward-sizing pre-registration, BOP rebuild impact, online weights, r* credible intervals

A parallel batch (4-agent authoring workflow + a full data re-collection + engine measurement). It finishes
the three follow-ups honestly: pre-register the nowcast sizing hypothesis for **forward** confirmation (not
in-sample), measure the impact of the corrected current-account series, and complete the Phase 5 remainder
(online/adaptive weights + r* credible intervals). Net: infrastructure built and **measured**, two clean
nulls reported, one uncertainty quantification delivered, and a data-correctness rebuild quantified. No alpha
claimed; the forward holdout remains the only promoter.

## (1) Nowcast confidence-vol sizing — PRE-REGISTERED for forward confirmation (nothing judged in-sample)

The Phase 5 measurement found a *tentative in-sample* gain for `nowcast_long` + conformal-width confidence
sizing (deflated DSR +0.060). "Confirm only on forward paper" is literally impossible today (0 out-of-time
months), so confirming it now would be self-deception. Instead it is **pre-registered**:

- `arc/autonomy/forward_experiments.py` — a `FORWARD_EXPERIMENTS` registry committing the **exact deterministic,
  causal sizing rule** (`confidence_vol`: expanding-mean point pred → split-conformal width → `interval_confidence`
  → `confidence_scaled_position(lo=0.25, hi=1.0)` applied to the recorded `held_position`) and a **pre-committed
  PASS/FAIL criterion** (`sized forward DSR (deflated) ≥ flat + 0.05 AND sized Sharpe > flat`, deflated by the
  same persisted basis — no second multiple-testing budget). The git commit is the timestamped pre-registration.
- `scripts/confirm_sizing_forward.py` — read-only; recomputes flat-vs-sized from the **frozen** ledger when
  `eval_at_n` months accrue. Today it correctly prints **`NOT READY: n=0<eval_at_n=24`**. It never consumes the
  holdout, never imports the engine, and does **not** touch the autonomy spine (`paper/ledger/spec/loop/...`
  verified untouched). 13 CI-native tests.

The +0.060 is recorded as *motivation only*; the verdict is deferred to the out-of-time stream.

## (2) BOP_CURRENT rebuild impact — the fix changes meaning, not just a label

After re-collecting with the corrected mapping (SGS 22707 trade balance → **22701 current account**),
`scripts/measure_bop_impact.py` quantified the difference (live SGS pulls, 1995–2026, 376 months):

- **Sign profile (confirms the fix):** old 22707 = **77.9% positive** (surplus, mean +2216 USD mn); new 22701
  = **83.8% negative** (deficit, mean −3236 USD mn). Mean level shift −5452 USD mn.
- **Levels:** corr(old, new) = **0.367**, sign-disagreement **61.7%** of months.
- **`Z_bop`** (engine causal rolling z, window 60): corr(old, new) = **0.797**, but **sign-disagreement 21.0%**
  of months; latest 2026-04 `Z_bop` old **1.538** vs new **0.743**.

**Verdict:** even though the rolling-z normalizes scale, the two z-series materially differ (0.80 corr, 21% sign
flips) — in ~1 in 5 months the external-vulnerability signal would have pointed the *wrong way* under the old
(trade-balance) mapping. BEER cointegration and RealRateParity r* Model 2 take `bop_current` as a regressor
(scale absorbed by the fit, so muted numeric impact) but now carry the correct economic fundamental. A
data-correctness improvement, not an alpha claim. (The on-disk `BOP_CURRENT.csv` now matches 22701; the old
series is preserved at `BOP_CURRENT_OLD_22707.csv` for the before/after.)

## (3a) Online/adaptive combination weights — NO improvement (EQUAL wins)

`arc/intelligence/online_weights.py` (pure, causal, 15 CI tests): `ewma_performance_weights` (EW Sharpe-proxy,
strict-past via `.shift(1)`) and `rolling_inverse_variance_weights`. `scripts/measure_online_weights.py` combines
the 3 booked sleeves' flat streams (161 months, deflated, leverage-invariant, +0.05 win bar):

| scheme | Sharpe | DSR | maxDD | Δ deflated DSR vs EQUAL |
|---|---|---|---|---|
| **EQUAL** | +0.780 | **0.986** | −2.1% | — |
| EWMA_PERF | +0.569 | 0.891 | −3.1% | −0.095 |
| INVERSE_VARIANCE | +0.496 | 0.836 | −1.2% | −0.150 |

**Verdict:** online combination weights do **not** add measured risk-adjusted value here; **equal weight
remains the baseline** (the honest, expected outcome with only 3 sleeves). Online *feature* selection is
explicitly deferred (out of scope). (Side note: the equal-weight 3-sleeve book's in-sample DSR 0.986 reflects
diversification across low-correlated candidates — still in-sample, still awaiting forward paper.)

## (3b) r* credible intervals from the Kalman state covariance

`StateSpaceRStar` (the Holston-Laubach-Williams-style Kalman r* model) now records the per-step **filtered
posterior variance** of the r* state (`P[0,0]`) and exposes `credible_intervals(z=1.96) → [rstar, std, lo, hi]`
— `estimate()`'s return is unchanged, so existing callers are unaffected. `scripts/measure_rstar_intervals.py`
reports the bands on engine data (6 CI-native tests):

| date | r* | 95% CI |
|---|---|---|
| 2018-08 | 2.01% | [1.03, 3.00] |
| 2022-06 | 2.58% | [1.60, 3.56] |
| **2026-04** | **8.69%** | **[7.72, 9.67]** |

Honest uncertainty quantification (~±1pp at 95%), not a forecast — the first of the Phase 5 "uncertainty"
items wired into a real engine model.

## Honest bottom line

Phase 5 is substantially complete: uncertainty (conformal + r* Kalman intervals), sizing, meta-labeling, and
online weights all exist, are leakage-safe, and are **measured** — with two clean nulls (online weights; broad
sizing) and one pre-registered forward hypothesis (nowcast confidence sizing). The current-account data fix is
rebuilt and its impact quantified. 283 pytest green. Nothing promoted; the forward holdout decides.

## Delivered

- `arc/autonomy/forward_experiments.py` + `scripts/confirm_sizing_forward.py` + `tests/test_forward_experiments.py` (13).
- `scripts/measure_bop_impact.py` (live before/after of the current-account fix).
- `arc/intelligence/online_weights.py` (+ `__init__` exports) + `scripts/measure_online_weights.py` + `tests/test_online_weights.py` (15).
- `server/model/composite_equilibrium.py` — `StateSpaceRStar` credible intervals; `scripts/measure_rstar_intervals.py` + `tests/test_rstar_intervals.py` (6).
