# ARC Macro 2.0 — Operational Tutorial

**System**: ARC Macro Risk OS 2.0  
**URL**: [arc-macro.com](https://arc-macro.com)  
**Author**: Marcelo Cauduro  
**Last Updated**: June 2026

---

## 1. System Overview

ARC Macro 2.0 is a quantitative macro trading system designed for institutional management of Brazilian rates (DI futures) and FX (USDBRL) positions. The system operates as an **overlay on CDI** — meaning the base portfolio earns the interbank rate passively, and the model generates alpha by taking directional positions in three instrument sleeves.

The core philosophy is **autonomy with human oversight**: the model proposes positions monthly, but a human operator must explicitly APPROVE, SKIP, or OVERRIDE each sleeve before the position enters the operator stream. This creates an auditable chain of decisions that separates model output from portfolio execution.

### Architecture

The system consists of two components working in tandem:

| Component | Role | Location |
|-----------|------|----------|
| **Python Engine** | Quantitative model: data collection, feature engineering, Ridge+GBM ensemble, HMM regime detection, mean-variance optimization, risk overlays | DigitalOcean (157.230.187.3) + GPU Droplet (146.190.242.223) |
| **Node.js Dashboard** | Real-time operational interface: 7 pages for monitoring, decision-making, and audit | Manus WebDev (arc-macro.com) |

The model runs monthly via GitHub Actions, collecting ~45 macro series from BCB, FRED, ANBIMA, and Yahoo Finance, then executing the full pipeline (features → regime → alpha → optimize → risk overlays) on an RTX 6000 Ada GPU. Results are delivered to the dashboard via webhook.

### The Three Sleeves

ARC 2.0 manages three independent alpha sleeves, each targeting a different segment of the Brazilian yield curve or FX market:

| Sleeve | Instrument | B3 Ticker | What It Trades | Risk Unit |
|--------|-----------|-----------|----------------|-----------|
| **momentum_front** | DI Front (1Y) | DI1F27 | Short-term rates receiver/payer | DV01 in BRL |
| **nowcast_long** | DI Long (5Y) | DI1F31 | Long-term rates receiver/payer | DV01 in BRL |
| **fiscal_hard** | FX Spot (USDBRL) | WDO/DOL | Dollar long/short | USD notional |

Each sleeve has a **contract** that defines its evaluation period (24 months forward from July 2024), after which a statistical verdict determines whether the sleeve has demonstrated genuine skill (DSR > 1.0 over 36 trials).

### The Three Streams

Every sleeve maintains three parallel streams of positions, each serving a distinct purpose:

| Stream | Description | Who Controls It | Modifiable? |
|--------|-------------|-----------------|-------------|
| **Frozen** | Deterministic holdout — the position the model would have taken with no human intervention. This is the only input to the statistical verdict. | Model (immutable) | Never |
| **Live** | Auto-operate baseline — the model's current best proposal, updated monthly. | Model (automatic) | Never |
| **Operator** | Human decisions — APPROVE/SKIP/OVERRIDE choices made via Co-Pilot. This is what you actually trade. | You (the operator) | Once per (month, hash) |

The frozen stream exists to provide an unbiased evaluation of model skill. Even if you disagree with the model and SKIP every month, the frozen stream continues accruing returns that will eventually determine whether the sleeve gets promoted to full autonomy.

---

## 2. The Seven Pages

### 2.1 Command Center (`/`)

The Command Center is the system's primary status display. It shows all three sleeves side by side with their current state, plus the pool aggregate.

**What to look for:**

The top of each sleeve card shows the **action suggestion** badge:
- **OPERATE** (green): The model has a live proposal and the sleeve is healthy. You should review it in Co-Pilot.
- **HALT** (red): A circuit breaker has fired. The model proposes position = 0. Review the reasons before deciding.
- **HOLD(warmup)** (yellow): The sleeve is still warming up and has no proposal yet.

The **accrual bar** shows progress toward the verdict: `n_forward_months / eval_at_n`. When this reaches 24/24, the verdict fires.

Key metrics per sleeve:
- **Frozen position**: What the model holds in the immutable holdout.
- **Proposed (live)**: What the model recommends for the operator stream this month.
- **Sized exposure**: The proposed position after vol-targeting and risk overlays (in risk units).
- **VaR95**: The 1-day 95% Value-at-Risk for this sleeve's proposed position.

The **Pool** section at the bottom aggregates all three sleeves and shows the combined readiness state. The pool verdict requires `n_common_forward_months` across all sleeves — meaning the slowest sleeve determines pool readiness.

### 2.2 Co-Pilot (`/co-pilot`)

The Co-Pilot is where you make operational decisions. Each sleeve presents a decision form with three options:

**APPROVE**: Accept the model's proposed position. The operator stream takes the same position as the live stream for this month. Use this when you agree with the model's directional view and sizing.

**SKIP**: Stay flat (position = 0) for this month. The operator stream holds no position. Use this when:
- You disagree with the model's direction
- External information suggests the model is wrong
- A circuit breaker is active and you want to respect it
- You are uncertain and prefer to wait

**OVERRIDE**: Set your own position (any decimal value). Use this when:
- You agree with the direction but want different sizing
- You want a partial position (e.g., half the proposed size)
- You have conviction the model is undersized or oversized

**Immutability Rule**: Once you commit a decision for a given (strategy, month), it cannot be changed. This is by design — it prevents hindsight bias and ensures the operator stream is a genuine record of your real-time judgment. If you commit APPROVE for momentum_front in 2026-07, that decision is permanent.

**Decision Workflow**:
1. Review the proposal in Command Center (direction, size, VaR, circuit status)
2. Check the Macro page for regime context (carry vs. risk-off vs. stress)
3. Check the Risk page for current drawdown and VaR utilization
4. Navigate to Co-Pilot
5. Select your action (APPROVE / SKIP / OVERRIDE)
6. Optionally add a rationale (recommended for audit trail)
7. Click COMMIT

After committing, the sleeve shows a green "✓ committed" banner with your decision details.

### 2.3 Holdout (`/holdout`)

The Holdout page displays the frozen stream in detail. This is the **untouchable** deterministic record of what the model would have done without any human intervention.

**Why it matters**: The holdout is the only input to the statistical verdict. When the evaluation period completes (24 months), the system computes a Deflated Sharpe Ratio (DSR) on the frozen stream. If DSR > 1.0 (accounting for multiple testing across 36 trials), the sleeve is promoted — meaning it has demonstrated genuine out-of-sample skill that cannot be attributed to luck.

**What you see**:
- Monthly position history (the frozen position for each month)
- Cumulative return of the frozen stream
- Maximum drawdown of the frozen stream
- Months remaining until verdict

**Key principle**: You cannot touch the holdout. Even if the frozen position is losing money, it must continue accruing. This is the scientific integrity of the system — it prevents data snooping and ensures that any promotion is statistically valid.

### 2.4 Risk (`/risk`)

The Risk page shows portfolio-level risk metrics:

- **VaR (95% and 99%)**: Daily Value-at-Risk in BRL and as % of AUM
- **Current Drawdown**: Peak-to-trough decline from high-water mark
- **Maximum Drawdown**: Worst historical drawdown
- **Gross/Net Exposure**: Total and directional exposure across all sleeves
- **Vol Targeting**: Current realized vol vs. target (10% annual default)

**Circuit Breakers**: The system has automatic risk overlays that can halt a sleeve:
- Drawdown > -5%: Linear scaling from 1.0 to 0.0 (full halt at -10%)
- Vol spike > 2x target: Position reduced proportionally
- VaR limit binding: Position capped to respect VaR budget

When a circuit breaker fires, the sleeve's action suggestion changes to HALT and the proposed position goes to 0.

### 2.5 Macro (`/macro`)

The Macro page provides the economic context that drives the model's decisions:

**Regime Probabilities**: The HMM (Hidden Markov Model) estimates the probability of being in each of 5 macro regimes:
- **P_carry** (green): Favorable carry environment — rates stable, vol low, BRL supported
- **P_riskoff** (amber): Global risk aversion — USD strengthens, EM assets sell off
- **P_stress** (red): Acute stress — rapid moves, correlations spike
- **P_domestic_calm** (blue): Local fundamentals improving
- **P_domestic_stress** (purple): Fiscal or political shock specific to Brazil

**State Variables (Z-scores)**: Eight standardized macro factors that drive the model:
- Z_fiscal: Fiscal stress (debt/GDP + CDS)
- Z_terms_trade: Terms of trade (commodity prices)
- Z_dxy: Dollar strength (DXY index)
- Z_vix: Global risk (VIX)
- Z_cds: Brazil sovereign CDS 5Y
- Z_policy_gap: Monetary policy gap (Selic vs. neutral)
- Z_diff_real: Real interest rate differential (BR vs. US)
- Z_iron_ore: Iron ore price (key export)

**FX Fair Value**: The model's estimate of USDBRL fair value based on BEER (Behavioral Equilibrium Exchange Rate), PPP-BS (Purchasing Power Parity Balassa-Samuelson), and FEER (Fundamental Equilibrium Exchange Rate). The misalignment percentage shows how far spot is from fair.

**DI Curve**: Current term structure of DI futures (3M to 10Y), showing the shape of the yield curve.

### 2.6 Research (`/research`)

The Research page provides deeper analytical context:

- **Backtest Results**: Historical performance of the model (Sharpe, return, drawdown, win rate)
- **SHAP Feature Importance**: Which factors are driving the model's current positions
- **Model Changelog**: Version history with metrics comparison across model updates
- **IC (Information Coefficient)**: Rolling predictive accuracy per instrument

### 2.7 Ledger (`/ledger`)

The Ledger is the immutable audit trail. It shows:

- **Decisions**: Every monthly model decision (frozen position, signal, signal z-score)
- **Realizations**: Actual returns for each stream (frozen, live, operator)
- **Operator Decisions**: Your APPROVE/SKIP/OVERRIDE history with rationale and timestamps

This page is essential for compliance and performance attribution. Every decision is timestamped and linked to the specific model state (hash) that produced it.

---

## 3. Portfolio Execution Guide

### What Trades to Execute

The operator stream position tells you what to hold. The **sized exposure** is the final risk-adjusted position after all overlays. Here is how to translate system output into B3 trades:

| Sleeve | Positive Position | Negative Position | Flat (0) |
|--------|------------------|-------------------|----------|
| momentum_front | **Receive** DI1 (buy DI futures) — you profit if front-end rates fall | **Pay** DI1 (sell DI futures) — you profit if front-end rates rise | No position |
| nowcast_long | **Receive** DI1 long tenor (buy DI futures 5Y) — profit if long rates fall | **Pay** DI1 long tenor (sell DI futures 5Y) — profit if long rates rise | No position |
| fiscal_hard | **Buy USD** (buy WDO/DOL) — profit if BRL weakens | **Sell USD** (sell WDO/DOL) — profit if BRL strengthens | No position |

### Sizing Methodology

The system outputs positions in **risk units** (not contracts). To convert to B3 contracts:

**For DI futures (momentum_front, nowcast_long)**:
```
contracts = sized_exposure × AUM / (DV01_per_contract × 100)
```
Where DV01 per contract depends on the tenor and current yield level. For DI1F27 (1Y), DV01 ≈ R$9.50 per contract per bp. For DI1F31 (5Y), DV01 ≈ R$42 per contract per bp.

**For FX (fiscal_hard)**:
```
WDO contracts = sized_exposure × AUM / (contract_size × spot)
```
Where WDO contract size = USD 10,000 and DOL contract size = USD 50,000.

### Monthly Workflow

The recommended operational cadence is:

1. **Model runs** (automated, monthly via GitHub Actions): Data collection → feature engineering → alpha estimation → optimization → risk overlays → webhook to dashboard.

2. **Review** (you, within 24h of model run): Check Command Center for new proposals. Review Macro page for regime context. Check Risk page for current drawdown.

3. **Decide** (you, in Co-Pilot): APPROVE, SKIP, or OVERRIDE each sleeve. Add rationale for audit trail.

4. **Execute** (you, on B3 via broker): Place the trades corresponding to your operator decisions. The system tells you direction and size; you handle execution timing and broker selection.

5. **Monitor** (ongoing): Check the dashboard periodically for circuit breaker activations, regime changes, or data quality alerts.

### When to SKIP

SKIP is the conservative choice. Use it when:
- The model is in a regime transition (probabilities are close to 50/50)
- A circuit breaker is active (HALT status)
- You have material non-public information that contradicts the model
- Drawdown is approaching your personal risk tolerance
- The model has recently been wrong and you want to wait for confirmation

### When to OVERRIDE

OVERRIDE is for experienced operators who want to express a view different from the model:
- Half-sizing: If the model proposes +1.4 but you want to be cautious, OVERRIDE with +0.7
- Directional disagreement with different sizing: The model says +1.4 but you think +0.5 is more appropriate given current vol
- Tactical adjustment: You agree with the model's medium-term view but want to reduce exposure ahead of a known event (COPOM meeting, FOMC, fiscal vote)

---

## 4. Understanding the Verdict

The verdict is the statistical test that determines whether a sleeve has genuine skill. It fires automatically when `n_forward_months` reaches `eval_at_n` (24 months).

**Deflated Sharpe Ratio (DSR)**: The verdict uses DSR rather than raw Sharpe because it accounts for multiple testing. With 36 trials (n_trials), a raw Sharpe of 0.5 might be luck; DSR adjusts for this by computing the probability that the observed Sharpe could have been generated by chance given the number of strategies tested.

**Threshold**: DSR > 1.0 means the sleeve has demonstrated skill at a level that cannot be attributed to luck with high confidence.

**What happens after promotion**:
- The sleeve moves from "accruing" to "promoted" status
- The operator stream can optionally be set to auto-follow the live stream (full autonomy)
- The frozen holdout continues running for ongoing monitoring

**Current status** (as of June 2026):
- momentum_front: 18/24 months accrued — 6 months to verdict
- nowcast_long: 14/24 months accrued — 10 months to verdict
- fiscal_hard: 10/24 months accrued — 14 months to verdict (currently HALTED)

---

## 5. Risk Management Framework

### Vol Targeting

The system targets 10% annualized portfolio volatility. Positions are scaled so that:
```
sqrt(p' × Σ × p) ≤ vol_target
```
Where p is the position vector and Σ is the rolling 2-year covariance matrix.

### Drawdown Scaling

When drawdown exceeds -5%, positions are linearly scaled down:
- DD = -5%: scale = 1.0 (no reduction)
- DD = -7.5%: scale = 0.5 (half position)
- DD = -10%: scale = 0.0 (full halt)

The trailing 12-month peak resets annually to prevent permanent halting after a recovery.

### Position Limits

| Instrument | Max Long | Max Short |
|-----------|----------|-----------|
| FX (USDBRL) | +1.5 | -1.5 |
| DI Front (1Y) | +2.0 | -2.0 |
| DI Long (5Y) | +0.5 | -0.5 |

### Factor Exposure Limits

The optimizer constrains factor exposures (DXY, VIX, CDS, UST10) via rolling beta estimation. This prevents the portfolio from becoming a pure bet on any single macro factor.

---

## 6. Data Sources and Model Pipeline

### Data Collection (45 series)

| Source | Series | Frequency |
|--------|--------|-----------|
| BCB (Banco Central) | SELIC, IPCA, IGP-M, expectations, FX forwards, cupom cambial | Daily/Monthly |
| FRED (Federal Reserve) | UST yields, DXY, VIX, NFCI, CPI, breakevens | Daily |
| ANBIMA | DI curve (ETTJ), NTN-B yields, NTN-F yields | Daily |
| Yahoo Finance | USDBRL spot, iron ore, commodity indices | Daily |

### Model Pipeline

1. **Feature Engineering**: 8 Z-scored state variables + carry + valuation signals
2. **Alpha Models**: Ridge regression + Gradient Boosting ensemble (adaptive weights based on rolling OOS R²)
3. **Regime Detection**: 3-state HMM on (ΔDXY, VIX, ΔUST10, ΔCDS_BR, commodity returns)
4. **Optimization**: Mean-variance with transaction costs, vol targeting, position limits, factor exposure limits
5. **Risk Overlays**: Drawdown scaling, vol targeting, regime-conditional scaling

### Execution Schedule

The model runs monthly via GitHub Actions workflow (`run-model-gpu.yml`):
- **Data collection**: GitHub Actions runner (standard compute)
- **Model execution**: SSH to GPU Droplet (RTX 6000 Ada, ~26 minutes)
- **Result delivery**: Webhook POST to arc-macro.com with full model output

---

## 7. Glossary

| Term | Definition |
|------|-----------|
| **AUM** | Assets Under Management — the total capital allocated to the strategy |
| **CDI** | Certificado de Depósito Interbancário — Brazil's overnight interbank rate (benchmark) |
| **DI1** | Futuro de Taxa de Juros — B3 interest rate futures contract |
| **DOL** | Full-size USD futures on B3 (USD 50,000 per contract) |
| **DSR** | Deflated Sharpe Ratio — Sharpe adjusted for multiple testing |
| **DV01** | Dollar Value of 01 — P&L from a 1bp move in yield |
| **FEER** | Fundamental Equilibrium Exchange Rate |
| **HMM** | Hidden Markov Model — regime detection algorithm |
| **Overlay** | Alpha strategy layered on top of passive CDI exposure |
| **PPP-BS** | Purchasing Power Parity (Balassa-Samuelson adjusted) |
| **Sleeve** | An independent alpha strategy within the portfolio |
| **VaR** | Value at Risk — maximum expected loss at a confidence level |
| **WDO** | Mini USD futures on B3 (USD 10,000 per contract) |

---

## 8. Quick Reference Card

### Daily Check (2 minutes)
1. Open [arc-macro.com](https://arc-macro.com) → Command Center
2. Verify all sleeves show expected status (OPERATE/HALT)
3. Check for any new circuit breaker activations (red HALT badges)

### Monthly Decision (15 minutes)
1. After model run webhook arrives → Command Center shows new proposals
2. Review Macro page: regime probabilities, state variables, FX fair value
3. Review Risk page: current drawdown, VaR utilization
4. Navigate to Co-Pilot → APPROVE/SKIP/OVERRIDE each sleeve
5. Execute trades on B3 within 24 hours of decision

### Emergency Protocol
- If drawdown exceeds -7.5%: System auto-scales positions to 50%
- If drawdown exceeds -10%: System halts all positions
- If data source fails > 24h: Dashboard shows degradation alert
- If model run fails: Previous month's positions remain (no automatic change)

---

*This document describes the ARC Macro 2.0 system as deployed at arc-macro.com. The system is in its accrual phase — no sleeve has been promoted yet. All operator decisions are immutable and auditable via the Ledger page.*
