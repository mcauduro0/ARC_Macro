# Phase 7.5 — live pre-trade VaR/ES + covariance risk gate in the loop

The optional Phase 6 item: wire the Phase 6 risk tooling (VaR/ES + DCC-GARCH covariance) as a LIVE
pre-trade gate in the paper loop. Delivered as a causal, operational sizing overlay that caps leverage to
a pre-committed loss budget — **without ever touching the scored `frozen` holdout** (CI-proven
byte-identical). 9 new tests, 396 green. No alpha claimed: a VaR gate bounds losses, it does not make money.

## What it does

`arc/autonomy/risk_gate.py`:
- `pretrade_leverage_gate(returns, requested_leverage, limits)` — caps a single sleeve's vol-target
  leverage so the SIZED book's one-month-ahead tail stays within budget:
  `applied = min(vol-target leverage, var_limit/VaR_per_unit, es_limit/ES_per_unit)`. VaR is
  **Cornish-Fisher** by default (fat-tail aware: negative skew / excess kurtosis raise it above the
  Gaussian the vol target assumes). Inactive below a 24-month history floor (tails need data).
- `portfolio_pretrade_gate(panel, weights, ..., cov_method)` — the BOOK gate: parametric portfolio VaR/ES
  from the causal covariance FORECAST `Σ_{T+1|T}` (`dcc_garch_cov` or `ewma_cov`), so the cross-sleeve
  correlation IS used. Same min(vol-target, VaR, ES) cap.
- `RiskLimits` — a pre-committed ABSOLUTE monthly loss budget (default VaR 5.5% / ES 7.5% @95%); absolute
  by design (a higher vol target makes the gate bind sooner — correct risk control).

## The non-negotiable invariant

Wired into `run_loop` (optional `risk_limits`), the gate rewrites **only** the operational
`leverage` / `sized_exposure` and adds Proposal fields (`var_forecast`, `es_forecast`, `risk_gate_binding`,
`risk_gate_active`). It estimates risk from the raw `frozen` sleeve returns (causal — reading the holdout's
realized returns to SIZE is fine; only the reverse, operations changing the score, is forbidden). It
NEVER changes the `frozen` (scored) or raw `live` ledger positions. `tests/test_risk_gate.py` proves the
frozen stream is **byte-identical** with the gate on vs off. The co-pilot (`scripts/copilot.py`) shows the
VaR-capped size + which limit binds (`--var-limit` / `--es-limit` / `--no-risk-gate`).

## Honest measurement (`scripts/measure_pretrade_gate.py`)

Causal month-by-month replay over each sleeve's in-sample stream (vol target 10%):

**Default backstop budget (VaR 5.5% / ES 7.5%)** — nearly transparent for the vol-controlled sleeves:

| sleeve | bind% | worstM vol→gate | maxDD vol→gate |
|---|---|---|---|
| momentum_front | 0.0% | −0.116 → −0.116 | −22.2% → −22.2% |
| nowcast_long | 0.0% | −0.083 → −0.083 | −8.4% → −8.4% |
| fiscal_hard | 0.7% | −0.106 → −0.106 | −15.2% → −15.2% |
| **POOL (book, ewma)** | **6.0%** | −0.074 → −0.074 | −7.5% → −7.5% |

The default budget sits above the sleeves' normal vol-targeted tail, so it is a **hard backstop that
rarely triggers** (the book binds 6% at its higher combined leverage). The worst realized months are
**unchanged** — they are surprises trailing VaR cannot predict (the honest limitation of any pre-trade VaR
gate). Latest DCC-GARCH book snapshot: per-unit VaR 0.77%, ES 0.96%; vol-target leverage 5.45 → 5.45
(vol_target binds — the book is well-behaved).

**Tighter budget (VaR 3.5% / ES 4.5%)** — the gate now binds and shows its teeth + the honest tradeoff:

| sleeve | bind% | ret vol→gate | vol vol→gate | maxDD vol→gate |
|---|---|---|---|---|
| momentum_front | 85.9% | 7.5% → 6.6% | 11.4% → 10.0% | −22.2% → −18.8% |
| nowcast_long | 100% | 7.2% → 5.3% | 8.1% → 6.2% | −8.4% → −6.9% |
| fiscal_hard | 100% | 5.2% → 3.6% | 9.6% → 7.6% | −15.2% → −13.0% |

A tighter budget cuts leverage and so dials **vol and drawdown down roughly proportionally** — at the cost
of proportional return. That is exactly what a VaR/ES cap is: an operational **risk dial**, not a
risk-adjusted-return improver. It is real, calibratable, and causal.

## Honest bottom line

The Phase 6 VaR/ES + DCC-GARCH covariance is now a live pre-trade gate in the loop and the co-pilot —
a hard, calibratable loss-budget backstop that bounds leverage using fat-tail-aware tail estimates and the
cross-sleeve covariance. It makes no alpha claim, it cannot touch the scored holdout (proven), and the
honest measurement shows it for what it is: operational tail/drawdown control with a proportional return
cost when tightened, transparent as a loose backstop. 9 new tests, 396 green.

## Delivered
- `arc/autonomy/risk_gate.py` (+ exports); `run_loop` `risk_limits` wiring + Proposal fields; co-pilot
  `propose()` + CLI flags + VaR/gate columns.
- `scripts/measure_pretrade_gate.py`; `tests/test_risk_gate.py` (9).
