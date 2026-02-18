# ML Model Retraining Plan — Post-Methodology Changes

## Problem Statement

The ML models (Ridge, GBM, RF, XGBoost) and the HMM regime model were trained before the following methodology changes were implemented:

1. **Composite Equilibrium Rate (r\*)** — 5-model framework (Fiscal, Parity, Market-Implied, State-Space, Regime)
2. **SELIC\* and Policy Gap** — Equilibrium policy rate and deviation from actual SELIC
3. **Regime-Dependent Weights** — Model weights that shift across Carry/RiskOff/Stress regimes
4. **Fiscal Decomposition** — Base + fiscal + sovereign components of r\*
5. **Sovereign Risk Score** — Composite 0-100 risk score with CDS term structure

These new signals are among the most powerful predictors available but are **not included** in the current FEATURE_MAP used by the alpha models.

## Current Feature Map (Before)

| Instrument | Current Features | Count |
|-----------|-----------------|-------|
| FX | Z_dxy, Z_vix, Z_cds_br, Z_real_diff, Z_tot, mu_fx_val, carry_fx, Z_cip_basis, Z_beer, Z_reer_gap, Z_hy_spread, Z_ewz, Z_iron_ore, Z_bop, Z_focus_fx, Z_cftc_brl, Z_idp_flow, Z_portfolio_flow | 18 |
| Front | Z_real_diff, Z_infl_surprise, Z_fiscal, carry_front, Z_term_premium, Z_us_real_yield, Z_pb_momentum, Z_portfolio_flow | 8 |
| Belly | Z_real_diff, Z_fiscal, Z_cds_br, Z_dxy, carry_belly, Z_term_premium, Z_tp_5y, Z_us_real_yield, Z_fiscal_premium, Z_us_breakeven, Z_portfolio_flow | 11 |
| Long | Z_fiscal, Z_dxy, Z_vix, Z_cds_br, carry_long, Z_term_premium, Z_fiscal_premium, Z_debt_accel, Z_us_real_yield, Z_portfolio_flow | 10 |
| Hard | Z_vix, Z_cds_br, Z_fiscal, Z_dxy, carry_hard, Z_hy_spread, Z_us_real_yield, Z_ewz, Z_us_breakeven, Z_cftc_brl, Z_portfolio_flow | 11 |

## New Features to Add

| Feature | Source | Instruments | Rationale |
|---------|--------|-------------|-----------|
| `Z_policy_gap` | SELIC - SELIC* (z-scored) | front, belly, long | Policy gap is the strongest predictor of rate direction |
| `Z_rstar_composite` | Composite r* (z-scored) | front, belly, long, hard | Equilibrium rate level signals mean-reversion |
| `Z_rstar_momentum` | 6m change in r* (z-scored) | front, belly, long | Rising r* = bearish for receivers |
| `Z_fiscal_component` | Fiscal component of r* | belly, long, hard | Fiscal premium directly impacts long-end |
| `Z_sovereign_component` | Sovereign component of r* | hard, long | Sovereign risk premium for credit |
| `Z_selic_star_gap` | DI_1Y - SELIC* | front, belly | Market pricing vs equilibrium |
| `rstar_regime_signal` | r* regime classification | all | Restrictive/neutral/accommodative signal |

## Enhanced Feature Map (After)

| Instrument | Added Features | New Count |
|-----------|---------------|-----------|
| FX | Z_policy_gap, rstar_regime_signal | 20 |
| Front | Z_policy_gap, Z_rstar_composite, Z_rstar_momentum, Z_selic_star_gap, rstar_regime_signal | 13 |
| Belly | Z_policy_gap, Z_rstar_composite, Z_rstar_momentum, Z_fiscal_component, Z_selic_star_gap, rstar_regime_signal | 17 |
| Long | Z_policy_gap, Z_rstar_composite, Z_rstar_momentum, Z_fiscal_component, Z_sovereign_component, rstar_regime_signal | 16 |
| Hard | Z_rstar_composite, Z_fiscal_component, Z_sovereign_component, rstar_regime_signal | 15 |

## HMM Regime Model Enhancement

Current observables: ΔDXY, VIX, ΔUST10, ΔCDS_BR, commodity returns

**Add**: Z_policy_gap, Z_fiscal_premium (for domestic HMM)

## Execution Steps

1. Add new feature builders to `_build_composite_equilibrium()` in FeatureEngine
2. Update FEATURE_MAP in both AlphaModels and EnsembleAlphaModels
3. Update RegimeModel observables for domestic HMM
4. Run full backtest with new features (walk-forward, expanding window)
5. Compare metrics before/after retraining
6. Update frontend with new model outputs
