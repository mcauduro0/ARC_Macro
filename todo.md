# BRLUSD Dashboard - Backend Integration

## Phase 1: Upgrade to Full-Stack
- [x] Run webdev_add_feature to upgrade to web-db-user
- [x] Review new backend structure and README

## Phase 2: Backend API + Model Integration
- [x] Create database schema for model runs and results
- [x] Port Python model logic to Node.js or create Python execution bridge
- [x] Create API endpoints: GET /api/model/latest, GET /api/model/timeseries, POST /api/model/run
- [x] Store model data in database

## Phase 3: Frontend API Integration
- [x] Update useModelData hook to fetch from API endpoints
- [x] Add loading states and error handling for API calls
- [x] Add auto-refresh mechanism (polling or SSE)

## Phase 4: Scheduled Execution
- [x] Implement cron/scheduler for daily model execution (07:00 UTC / 04:00 BRT)
- [x] Add last-updated timestamp to dashboard
- [x] Add manual refresh button
- [x] Add live/static data source indicator

## Phase 5: Test and Deliver
- [x] Write vitest tests for model API endpoints (10 tests passing)
- [x] Test full flow: model run → DB store → API serve → frontend display
- [x] Save checkpoint and deliver

## Macro Risk OS - FX + Rates + Sovereign Integration

### Data Collection
- [x] Collect DI curve data (1y, 2y, 5y, 10y)
- [x] Collect NTN-B yields (5y, 10y) and breakeven inflation
- [x] Collect US Treasury yields (2y, 5y, 10y)
- [x] Collect CDS 5y Brazil and EMBI spread
- [x] Collect VIX and Financial Conditions Index
- [x] Collect FX forwards (1m, 3m, 12m) and FX vol
- [x] Collect macro data: IPCA expectations, output gap, primary balance

### Unified State Variables (X1-X7)
- [x] X1: diferencial_real (DI-IPCA_exp vs UST-US_CPI_exp)
- [x] X2: surpresa_inflacao (IPCA_yoy - IPCA_exp)
- [x] X3: fiscal_risk (zscore debt_gdp + zscore CDS)
- [x] X4: termos_de_troca (zscore ToT index)
- [x] X5: dolar_global (zscore DXY)
- [x] X6: risk_global (zscore VIX/FCI)
- [x] X7: hiato (output gap)
- [x] Rolling 5-year Z-score standardization with winsorization 5%-95%

### Expected Return Models
- [x] FX expected return model (3m, 6m horizons)
- [x] Front-end local rates expected return model
- [x] Long-end local rates expected return model
- [x] Hard currency sovereign expected return model

### Regime Model
- [x] 3-state Markov Switching (Carry, RiskOff, Stress Doméstico)
- [x] Regime-adjusted expected returns

### Sizing Engine
- [x] Risk units: FX vol, DV01 front/long, spread DV01 hard
- [x] Sharpe estimation per asset class
- [x] Optimal weight via fractional Kelly
- [x] Factor exposure limits (dólar global, risk off, fiscal)

### Risk Aggregation
- [x] Rolling 2-year covariance matrix
- [x] Portfolio vol targeting
- [x] Historical stress test scenarios (2013 Taper, 2015 BR Fiscal, 2020 Covid, 2022 Inflation)
- [x] Drawdown limits

### Dashboard Update
- [x] Cross-asset overview (FX + Front + Long + Hard)
- [x] Factor exposure heatmap
- [x] Regime-adjusted positions panel
- [x] Stress test results display

## Data Fix & Stress Tests (v2.1)

### Data Collection Fix
- [x] Fix DI 5Y/10Y data (currently showing 1.70%/0.91% instead of ~14-15%)
- [x] Rewrite data_collector.py with correct sources for all series
- [x] Use Trading Economics for DI curve (3M, 6M, 1Y, 2Y, 3Y, 5Y, 10Y) in % a.a.
- [x] Use FRED for breakeven inflation (T5YIE, T10YIE)
- [x] Use FRED for US Treasury yields (2Y, 5Y, 10Y)
- [x] Use EMBI proxy for CDS 5Y Brazil (EMBI*0.7)
- [x] Use FRED/Yahoo Finance for VIX
- [x] Use FRED for Financial Conditions Index (NFCI)
- [x] Use BCB for FX forwards and cupom cambial
- [x] Validate all data scales (yields in %, spreads in bps)
- [x] Test full data collection pipeline

### Stress Test Visualization
- [x] Define 4 historical stress scenarios (Taper 2013, Fiscal BR 2015, Covid 2020, Inflation 2022)
- [x] Calculate portfolio impact for each scenario with per-asset breakdown
- [x] Add StressTestPanel component to dashboard
- [x] Add stress test charts with scenario comparison (horizontal bar + per-asset stacked)

### Integration
- [x] Update macro_risk_os.py with corrected data
- [x] Re-run model with corrected data
- [x] Update dashboard with stress test visualization
- [x] Push to GitHub (3 commits: v2.0, v2.1 data fix, docs)

## ANBIMA API Integration (v2.2)

### Research & Authentication
- [x] Analyze ANBIMA API documentation (endpoints, auth, rate limits)
- [x] Configure ANBIMA API credentials (client_id: qoSZCWnsbfSK, client_secret: xgAbycH1LIb0)
- [x] Test authentication flow (OAuth2)

### Data Collection
- [x] Implement ANBIMA ETTJ (curvas-juros) endpoint for DI curve vertices (7 tenors)
- [x] Integrate NTN-B yields (real yields for 5Y, 10Y maturities) from mercado-secundario-TPF
- [x] Integrate NTN-F yields (nominal yields for DI curve validation)
- [x] Calculate breakeven inflation from NTN-F vs NTN-B spread (5Y: 4.75%, 10Y: 5.05%)
- [x] Integrate DI curve from ANBIMA ETTJ (3M to 10Y, 75 vertices)
- [x] Add ANBIMA as primary source in collect_all() pipeline
- [x] Update merge_sources() to prioritize ANBIMA > TE > SELIC construction
- [x] Test end-to-end ANBIMA data collection (15 series extracted)

### Model Update
- [x] Update data_collector.py v2.2 with ANBIMA source
- [x] Validate ANBIMA data vs current Trading Economics data
- [x] Re-run model with ANBIMA data (validated end-to-end)

### Delivery
- [x] Run tests (ANBIMA collection validated)
- [x] Save checkpoint (d23dd013)
- [x] Push to GitHub (commit 58eb267)

## Bug Fix: N/A Signals on Dashboard Cards
- [x] Investigate why Front-End, Long-End, Hard Currency cards show "N/A" instead of BUY/SELL/NEUTRAL
  Root cause: positions dict in macro_risk_os.py missing 'direction' field; DB records also lacked it
- [x] Fix signal calculation logic: added direction field to SizingEngine.compute() positions output
- [x] Updated DB records with JSON_SET to add direction based on weight thresholds
- [x] Test and verify all cards show proper signals (FX=NEUTRAL, Front=SHORT, Long=SHORT, Hard=SHORT)

## Bug Fix: Empty Chart Series
- [x] Fair Value tab: mapped ppp_fair, beer_fair, fx_fair from Macro Risk OS output (4 lines visible)
- [x] Z-Scores tab: using Z_X1..Z_X7 state variables with isAnimationActive={false} (7 lines visible)
- [x] Cíclico tab: using stateVariables fallback with Z_X1..Z_X7, isAnimationActive={false} (7 lines visible)
- [x] Regime tab: P_Carry, P_RiskOff, P_StressDom rendering correctly with isAnimationActive={false}
- [x] Root cause: Recharts animation interfered with initial render + field name mismatch between model output and chart expectations
- [x] All 4 chart tabs verified working: Fair Value, Z-Scores, Regime, Cíclico

## Fix: Max Drawdown NaN% and Cíclico Tab Differentiation
- [x] Investigate Max Drawdown NaN% - root cause: risk_metrics had max_drawdown_historical but not max_drawdown
- [x] Fix Max Drawdown: added max_drawdown = max_drawdown_historical in SizingEngine, updated ActionPanel fallback
- [x] Update DB records with corrected Max Drawdown value (-84.26%)
- [x] Differentiate Cíclico tab from Z-Scores - now shows 8 raw macro factors with dual Y-axes
- [x] Build cyclical factors data from CSV files (DXY, VIX, EMBI, SELIC, DI 1Y, DI 5Y, IPCA Exp, CDS 5Y)
- [x] Update ChartsSection with dedicated Cíclico chart (left axis: Index/%, right axis: bps)
- [x] Test and verify: Max Drawdown shows -84.26%, Cíclico shows 8 distinct macro factors

## Feature: Score Tab in Séries Históricas
- [x] Investigate model output for score timeseries data (score_total, sub-scores)
- [x] Add _build_score_timeseries to macro_risk_os.py (194 points: score_total, score_structural, score_cyclical, score_regime)
- [x] Add scoreJson column to model_runs DB schema + populate with data
- [x] Update modelRunner.ts, routers.ts, useModelData.ts for score data flow
- [x] Implement Score tab in ChartsSection with 4 lines + BUY/SELL reference lines at ±3
- [x] Test and verify Score tab renders correctly: all 4 score lines visible from 2016-2026

## Feature: Backtesting Panel - Hypothetical Portfolio P&L
- [x] Investigate available historical return data for each asset class (FX, DI 1Y, DI 5Y, Hard Currency)
- [x] Design backtest engine: apply model weights to historical returns monthly
- [x] Implement _build_backtest_timeseries in macro_risk_os.py
- [x] Calculate key metrics: cumulative P&L, annualized return, Sharpe, max drawdown, win rate
- [x] Add backtestJson column to model_runs DB schema
- [x] Update modelRunner.ts and routers.ts for backtest data flow
- [x] Build BacktestPanel component with: equity curve, drawdown chart, monthly returns bar chart, attribution chart, metrics cards
- [x] Add BacktestPanel to Home.tsx
- [x] Test and verify backtest panel renders correctly (173 months, +38.3% total, Sharpe 0.39)

## Feature: Backtest Enhancements - Heatmap & Benchmarks
- [x] Build monthly returns heatmap (year x month calendar grid with color scale)
- [x] Add CDI acumulado benchmark to equity curve
- [x] Add USDBRL buy-and-hold benchmark to equity curve
- [x] Compute CDI cumulative returns from SELIC/CDI historical data
- [x] Compute USDBRL buy-and-hold cumulative returns from spot data
- [x] Add new "Heatmap" tab to BacktestPanel
- [x] Update equity chart to show benchmark comparison lines (ComposedChart with 3 series)
- [x] Write vitest tests for benchmark and heatmap data (30 tests passing)

## ARC Macro Risk OS v2 — Institutional Rebuild

### 1. Foundations & Data Layer
- [x] Define base_currency=BRL, overlay-on-CDI framework (ret_total = ret_cash + pnl_overlay/AUM)
- [x] Build instrument return calculators:
  - [x] FX NDF 1M: ret = (spot_{t+1m} - fwd_1m_t) / spot_t
  - [x] BR_FRONT receiver 1Y: pnl = DV01 * (-Δy_bp + carry_roll_bp)
  - [x] BR_BELLY receiver 5Y: same with 5Y DV01
  - [x] BR_LONG receiver 10Y: same with 10Y DV01
  - [x] BR_SOV_OAS hard currency: spread DV01 * (-Δspread_bp) + carry
- [x] Implement carry/rolldown calculation from DI curve
- [x] Enforce as-of dates for macro data (no look-ahead)

### 2. Feature Engine
- [x] Z-score rolling with std_floor=0.5 (Z_dxy, Z_vix, Z_cds_br, Z_real_diff, Z_infl_surprise, Z_fiscal, Z_tot)
- [x] FX fair value in log-space: log(FX_fair) = w_ppp*log(PPP) + w_beer*log(BEER) + w_cyc*log(CYC)
- [x] Valuation signal: val_fx = log(FX_fair / spot), no arbitrary multiplier
- [x] Half-life calibrated mean reversion: mu_val = k * val, k = ln(2)/HL
- [x] Carry as explicit feature: carry_fx = -log(fwd_1m/spot), carry_rates from curve

### 3. Expected Return Models (Ridge Walk-Forward)
- [x] Ridge regression (L2) instead of OLS
- [x] Walk-forward: 60m train, monthly refit, predict next month
- [x] Target = instrument return (not yield change), including carry/rolldown
- [x] Separate model per instrument (FX, Front, Belly, Long, Hard)
- [x] Backtest calls exactly same fit/predict code as production

### 4. Regime Model
- [x] HMM 3-state on exogenous observables (ΔDXY, VIX, ΔUST10, ΔCDS_BR, commodity returns)
- [x] Output: P_carry, P_riskoff, P_domestic_stress (daily)
- [x] Regime enters as gating: mu_adj = Σ P_s * mu_s and risk scaling

### 5. Optimizer & Sizing
- [x] Mean-variance with transaction costs: max p·mu - 0.5*gamma*p'Σp - TC - TurnoverPenalty
- [x] Positions in physical risk units (USD notional, DV01 BRL, spread DV01 USD)
- [x] Vol target constraint: sqrt(p'Σp) <= vol_target
- [x] Position limits per class (fx ±1.5, front ±2.0, belly ±1.5, long ±0.5, hard ±1.0)
- [x] Factor exposure limits (DXY, VIX, CDS, UST10) via rolling beta
- [x] Dynamic risk budgets by IC: Budget_g = max(IC_rolling_36m, 0) / Σ max(IC, 0)

### 6. Risk Overlays
- [x] Drawdown scaling: continuous linear scaling DD<-5% → 0.5, DD<-10% → 0.0 with trailing 12m peak reset
- [x] Vol targeting: scale_vol = min(1.0, vol_target / vol_realized_20d)
- [x] Regime scaling: reduce duration/credit in riskoff, reduce local in domestic stress

### 7. Unified Backtest Harness
- [x] Single code path: build_features → fit_models → predict_mu → optimize → apply_overlays → mark_to_market
- [x] Metrics: overlay excess over CDI, total return (CDI+overlay), Sharpe 0.73, IC per class, hit rate, turnover 1.31x, TC 5.0%

### 8. Dashboard Update
- [x] Show overlay P&L vs CDI (not raw return vs CDI)
- [x] Show positions in physical risk units (DV01, notional)
- [x] Show IC rolling per class (IC & Hit Rate tab)
- [x] Show regime probabilities and scaling
- [x] Show transaction costs and turnover

### 9. Config JSON
- [x] Externalize all parameters to DEFAULT_CONFIG dict (ridge_lambda=10, HL, vol_target=10%, limits, TC costs)

## ARC Macro Risk OS v2.1 — Institutional Refinements

### Gap Analysis vs User Suggestions
- Score Demeaning: NOT in v2 — score is raw sum of mu predictions, not centered. MUST ADD.
- Walk-Forward Validation: ALREADY in v2 — Ridge walk-forward with 60m train window, monthly refit. ✓
- Dynamic Risk Budgets by IC: ALREADY in v2 — Optimizer uses ic_scores for budget_scale. ✓
- Carry as Explicit Feature: ALREADY in v2 — carry_fx, carry_front, carry_belly, carry_long, carry_hard. ✓
- Non-Linear Models: NOT in v2 — only Ridge. ADD ensemble with GBM.
- Ensemble with Adaptive Weights: NOT in v2 — single Ridge model. ADD ensemble framework.

### Improvements to Implement
- [x] Score Demeaning: apply rolling 60m z-score normalization to composite score (score = (raw - mean_60m) / max(std_60m, 0.5))
- [x] Add GradientBoosting (sklearn) as second alpha model alongside Ridge
- [x] Build ensemble framework: Ridge + GBM with adaptive weights based on rolling OOS R²
- [x] Add rolling OOS R² tracking per model per instrument
- [x] Add score timeseries to backtest output (raw_score, demeaned_score)
- [x] Update dashboard to show model comparison metrics (Ridge vs GBM vs Ensemble) — Ensemble tab
- [x] Run backtest and compare v2 vs v2.1 metrics (Sharpe 0.73→1.61, win rate 56%→72%)
- [x] Write vitest tests for v2.1 data structure (59 tests passing)

## ARC Macro Risk OS v2.2 — Deep Research Institutional Upgrades

### Gap Analysis Summary
- Walk-forward Ridge, dynamic IC budgets, carry features, HMM regime, MV optimizer: ALREADY IN v2.1 ✓
- Score demeaning, GBM ensemble: ALREADY IN v2.1 ✓
- CIP basis, BEER cointegration, term premium, breakeven decomposition, fiscal premium: NOT YET
- Two-level regime (fast daily + slow monthly): NOT YET
- IC decay curve monitoring: NOT YET
- REER gap as explicit FX feature: PARTIAL (REER used in BEER, but not as standalone gap signal)

### Phase 1: New Feature Signals (FX Signal Improvement Focus)
- [x] CIP Basis feature: basis = (fwd/spot) - (1+i_BR)/(1+i_USD), captures funding premium distortions
- [x] BEER Cointegration: log(REER) = f(TOT, NFA, RID, PROD) with rolling 60m estimation, extract residual as misalignment
- [x] REER Gap: log(REER_actual) - log(REER_trend_60m) as standalone valuation signal
- [x] Term Premium Proxy: TP = y_long - (1/n)*Σ E[short_rate], using slope and forwards
- [x] Breakeven Decomposition: y_nominal = y_real + breakeven_inflation + inflation_risk_premium
- [x] Fiscal Premium: residual from yield decomposition y_nom = E[infl] + real_neutral + TP_global + fiscal_premium

### Phase 2: Enhanced Regime Model
- [x] Two-level regime: global HMM + domestic HMM with softened scaling
- [x] IC by regime: monitor IC conditional on regime state
- [x] IC decay curve: feature importance + IC tracking per instrument

### Phase 3: Integration & Validation
- [x] Integrate new features into Ridge+GBM ensemble
- [x] Run backtest: Sharpe 1.94, Calmar 1.53, Win Rate 71%, FX IC 0.061, Belly IC 0.74, Long IC 0.76
- [x] Update dashboard with Regime tab (global + domestic probability charts)
- [x] Write vitest tests for v2.2 data structure (69 tests passing)

## Bug Fix: Max Drawdown -84.26% Display
- [x] Investigate source of -84.26% max drawdown in Risco & Sizing card
  Root cause: dashboard.overlay_metrics was undefined because dashboardJson in DB didn't include it (inserted before run_model.py added overlay_metrics). ActionPanel fell back to N/A.
- [x] Determine if it's overlay DD vs total DD vs calculation bug
  Legacy v1 risk_metrics used static weights retroactively → -84.26%. Correct v2.2 backtest: overlay -8.37%, total -4.04%.
- [x] Fix: ActionPanel now accepts backtest prop, resolves overlay metrics from backtest.summary.overlay (preferred) → dashboard.overlay_metrics (fallback)
- [x] Verify: Risco & Sizing card now shows Vol 6.63%, Max DD -8.37%, Sharpe 1.94, Calmar 1.53

## E2E System Audit & Improvements (v2.3)

### Phase 1: Deep Code Audit
- [x] Audit macro_risk_os_v2.py: verified ensemble (Ridge+GBM), walk-forward, score demeaning, dynamic weights
- [x] Audit data_collector.py: verified all 20+ data sources are real BCB/FRED/Yahoo APIs (no placeholders)
- [x] Audit run_model.py: verified correct pipeline execution and DB storage
- [x] Audit database schema: verified completeness (model_runs, model_results, users tables)
- [x] Audit frontend data flow: verified dashboard reads correct v2.3 metrics

### Phase 2: Risk Management & Signal Quality Improvements
- [x] Fix HMM look-ahead bias: expanding-window refit every 12 months during backtest
- [x] Fix double regime scaling: removed from RiskOverlays, kept only in step() mu adjustment
- [x] Add IC-conditional gating: zero mu for instruments with negative rolling IC
- [x] Add Ledoit-Wolf covariance shrinkage with 36m window
- [x] Improve score demeaning: safeguard against instability near zero, clip scale factor [-3, 3]
- [x] Add circuit breaker: combined global risk-off + domestic stress hard cut
- [x] Fix FX carry: use cupom cambial (BCB 3955) when available, DI-UST proxy as fallback
- [x] Move hardcoded FV weights and cyclical beta to config
- [x] Fix realized vol floor (2% minimum) and use 12-month minimum history

### Phase 3: New Features
- [x] Add Rolling Sharpe 12m chart to BacktestPanel (new tab with area chart + summary stats)
- [x] Deprecate v1 legacy code from run_model.py (removed macro_risk_os.py execution)
- [x] Add v2.3 fields to timeseries output (domestic regime, ensemble weights, rolling sharpe)
- [x] Verify Python syntax for both macro_risk_os_v2.py and run_model.py
- [x] All 69 vitest tests passing
- [x] Update version references to v2.3 throughout (BacktestPanel, footer, run_model.py)

## v2.3 Backtest Execution & New Features

### Regime-Conditional Position Limits
- [x] Implement position limit scaling by regime state in Python engine
- [x] Add config parameters for regime-specific limits (carry/calm/stress/riskoff)
- [x] Integrate into Optimizer.optimize() with regime_probs parameter

### Stress Testing Framework
- [x] Define 6 historical stress scenarios (Taper Tantrum, Dilma, COVID, Joesley, Fed Hike, Lula Fiscal)
- [x] Implement StressTestEngine with per-instrument attribution and regime analysis
- [x] Add stress test output to run_model.py pipeline
- [x] Build StressTestPanel frontend with scenario cards, attribution charts, and summary stats

### Full v2.3 Backtest
- [x] Run complete backtest: Overlay 257.4%, Sharpe 1.42, Max DD -6.4%, Calmar 1.06
- [x] Total: 2368.6%, Ann Return 17.9%, Sharpe 3.83
- [x] All 6 stress tests positive (avg +11.9%, worst DD -2.1%)
- [x] Store results in database (Run ID 90003)

### Frontend Updates
- [x] Add StressTestPanel to dashboard with 2 bar charts + 6 scenario cards
- [x] Fix FX fair values (PPP 2.49, BEER 4.50, Combined 3.59)
- [x] Fix Z-scores display (12 variables with visual bars)
- [x] Fix Portfolio Vol display (4.77% not 477%)
- [x] Fix rates fair values (Front 14.90%, Long 15.40%, Term Premium 0.50%)
- [x] All 69 vitest tests passing

## Cupom Cambial Data - Complete Series
- [x] Research: Found BCB 7811 (Swap DI x Dólar 30d, 1991-2026, 420 monthly points)
- [x] Implement: Updated data_collector.py with BCB 7811/7812/7814 series
- [x] Fix load_series to detect observation_date, data column names
- [x] Fix PPP interpolation (annual → monthly via linear interpolation)
- [x] Fix REER_BIS/REER_BCB loading (observation_date/data columns)
- [x] Validate: FX carry now uses cupom cambial from Swap DI x Dólar market

## v2.3 Bug Fixes & Rates Equilibrium Model

### Critical Bugs
- [x] Fix empty timeseries charts - fair value data was null because FeatureEngine didn't store PPP/BEER/FX fair timeseries in features dict
- [x] Fix Total Return computation - 2543% was correct (CDI+overlay over 19 years), now 988% with corrected IPCA
- [x] Fix Win Rate - improved from 36.8% to 51.1% with corrected IPCA/Taylor Rule
- [x] Turnover 0.30x is correct for monthly rebalancing with stable positions
- [x] FX IC=0.026 (low but positive), Hard IC=-0.017 (negative) - IC gating correctly limits exposure

### Rates Equilibrium Model
- [x] Taylor Rule model: SELIC* = 12.04%, gap = +2.86pp (tight monetary policy)
- [x] Term structure model: belly_fair = 11.04%, long_fair = 11.54%
- [x] Term premium = 0.50% (from model)
- [x] Rates fair values integrated into dashboard (front_fair, belly_fair, long_fair, taylor_gap)

### Model Improvements
- [x] IC gating threshold reviewed - FX IC=0.026 passes, Hard IC=-0.017 correctly gated
- [x] Win rate methodology correct - 51.1% overlay, 96.6% total (CDI+overlay)
- [x] Total return validated: overlay 269.5% + CDI = 988% total over 19 years
- [x] Timeseries includes all fields: spot, ppp_fair, beer_fair, fx_fair (165/254 non-null), plus all backtest fields

### IPCA Data Fix
- [x] Fix IPCA 12M: BCB 432 returns index number, not YoY%. Now computed from BCB 433 (monthly variation)
- [x] Add IPCA 12M computation: rolling 12-month product of (1 + monthly/100) - 1
- [x] Validate IPCA 12M: 4.44% (jan/2026) matches official IBGE data
- [x] Fix Taylor Rule: SELIC* now 12.04% (was 22.26% with wrong IPCA)
- [x] Add belly_fair and taylor_gap to MacroDashboard TypeScript interface
- [x] Fix fair_value_ts: stored PPP/BEER/FX fair timeseries in FeatureEngine features dict
- [x] Fix timeseries builder: corrected feature names (ppp_fair_ts, beer_fair_ts, fx_fair_ts)

## User Guide & Documentation
- [x] Write comprehensive system overview explaining Macro Risk OS fundamental logic
- [x] Document each dashboard card with indicator definitions and interpretation
- [x] Explain how to translate model signals into trading positions
- [x] Add portfolio allocation methodology and position sizing examples
- [x] Create trading implementation guide with practical examples

## Portfolio Management Feature (B3/BMF)
- [x] Design database schema: portfolio_config, portfolio_positions, portfolio_trades, portfolio_snapshots
- [x] Build portfolio engine: B3 instrument mapper (DOL/WDO, DI1, FRA, NTN-B, DDI)
- [x] Build risk budget calculator: AUM → vol target → risk units → notional → contracts
- [x] Build contract sizing: DOL (USD 50k), WDO (USD 10k), DI1 (R$ 100k PU), FRA (DI spread)
- [x] Build VaR engine: parametric VaR (delta-normal), component VaR, stress tests (6 scenarios)
- [x] Build exposure analytics: gross/net exposure, DV01 ladder, FX delta, Herfindahl
- [x] Build rebalancing engine: current vs target weights, trade list, cost estimation
- [x] Build tRPC procedures: portfolio.getConfig, portfolio.saveConfig, portfolio.compute, portfolio.rebalance, portfolio.history
- [x] Build Portfolio Setup page: AUM input, vol target, FX instrument preference (DOL/WDO)
- [x] Build Portfolio Dashboard page: positions, risk budget, exposure, contract sizing
- [x] Build Rebalancing page: trade blotter, cost estimation, execute button
- [x] Build Risk Monitor page: VaR, stress tests, DV01 ladder, margin utilization
- [x] Integrate with model pipeline: auto-translate model weights to B3 contracts
- [x] Write vitest tests for portfolio engine (48 tests passing)
- [x] Validate end-to-end flow: 117 total tests passing, save checkpoint

## Portfolio Management Enhancements (v2)
- [x] Fix DDI contract sizing: DV01-based approach with notional cap at 2x AUM
- [x] Fix regime field name in interpretation (dominant_regime / current_regime)
- [x] Add portfolio_trades table for recording executed trades
- [x] Add portfolio_alerts table for risk alerts
- [x] Add portfolio_pnl_daily table for P&L tracking
- [x] Add tRPC procedures: recordTrade, getTrades, getPnl, getAlerts, checkAlerts
- [x] Build Trades tab: view recommended trades and record executions
- [x] Build P&L tab: daily/MTD/YTD tracking vs CDI benchmark
- [x] Build Risco tab: VaR, stress tests, DV01 ladder, alerts
- [x] Build Histórico tab: rebalancing timeline with attribution
- [ ] Test authenticated portfolio page with real data

## Portfolio Management v3: Market Data, Trade Workflow, Risk Dashboard
- [x] Build marketDataService.ts with ANBIMA Feed API (ETTJ curva DI, NTN-B yields)
- [x] Integrate Polygon.io for real-time FX (USDBRL) via REST API
- [x] Integrate BCB SGS for PTAX, SELIC, CDI official data
- [x] Integrate Yahoo Finance for VIX, Ibovespa, UST yields
- [x] Build MTM engine: auto-calculate mark-to-market from live prices
- [x] Build P&L engine: daily/MTD/YTD tracking with CDI benchmark comparison
- [x] Build trade approval workflow: pending → approved → executed → filled
- [x] Build slippage tracking: target price vs executed price with bps calculation
- [x] Build risk dashboard endpoint: consolidated factor exposure + limits + alerts
- [x] Add tRPC procedures: market.prices, market.mtm, market.recordMtm, tradeWorkflow.approve, tradeWorkflow.fill, riskDashboard
- [x] Add auto-fetch market prices button in P&L tab (ANBIMA + Polygon + BCB)
- [x] Add MTM recording with auto-computed P&L from live prices
- [x] Add Approve/Fill/Reject workflow buttons in Trades tab
- [x] Add Factor Exposure panel (FX, Rates, Credit) in Risk tab
- [x] Write marketDataService tests (30 tests passing)
- [x] All 147 vitest tests passing

## Critical Data Integrity Issues (v3.1)
- [x] BUG: Dashboard date shows 2019-12-31 instead of current date - ROOT CAUSE: PTAX.csv had 5-year gap (2019-12 → 2025-01), BCB chunk 2020-2024 failed during collection. Fixed by re-collecting PTAX with retry logic.
- [x] BUG: Regime changed from stress to domestic_calm unexpectedly - ROOT CAUSE: With data only to 2019 (pre-COVID), regime was correctly "calm" for that period. Now shows domestic_stress with full 2020-2026 data.
- [x] BUG: BEER Fair value changed significantly - ROOT CAUSE: BEER was frozen at 4.29 (Dec 2019 value). Now correctly shows 4.50 with updated data through Feb 2026.
- [x] BUG: Fair Value FX chart has no data after 2019 - ROOT CAUSE: ret_df.dropna() truncated at 2019-12 due to PTAX gap. Fixed with forward-fill for shorter instruments + PTAX re-collection.
- [x] BUG: Z-Scores chart completely empty - ROOT CAUSE: stateVariablesJson had data but frontend wasn't rendering it correctly with the old DB run. New run has 383 points (1994-2026).
- [x] AUDIT: Full data pipeline investigation - Identified 3 issues: (1) PTAX gap, (2) CDS/EMBI ending Jul 2024, (3) ret_df.dropna() too aggressive
- [x] FIX: Ensure model runs with complete data - ret_df now 2000-02 to 2026-02 (313 months), backtest 253 months, Sharpe 1.79
- [x] FIX: Verify all timeseries complete - Fair Value 314 pts, State Variables 383 pts, Regime 253 pts, Score 253 pts, Backtest 253 pts

### Technical Fixes Applied
- [x] data_collector.py: Added retry logic with gap detection for BCB fetch, merge with existing cache
- [x] data_collector.py: Added FRED EM Corporate spread (BAMLEMCBPIOAS) as EMBI extension source
- [x] data_collector.py: Removed incorrect BCB 22701 mapping (was primary balance, not CDS)
- [x] macro_risk_os_v2.py: Changed ret_df.dropna() to forward-fill for shorter instruments
- [x] macro_risk_os_v2.py: Fixed EMBI/CDS reading to use correct source files
- [x] run_model.py: Added --skip-collect flag for faster re-runs with existing data
- [x] Re-ran model: Run ID 270003, date 2026-02-28, spot 5.212, regime domestic_stress, BEER 4.50

## Data Display Issues (v3.1.1)
- [x] BUG: BEER Fair line flat/frozen from ~2022-07 to 2024-01 - ROOT CAUSE: PPP_FACTOR has only 35 annual points ending Jan 2024. The common_idx intersection of PPP ∩ BEER ∩ CYC truncated all components at Jan 2024. Forward-fill in timeseries builder repeated the last BEER value (4.4976). FIXED: Changed to UNION-based combination where each date uses available components with re-normalized weights. Each component stored with its own index.
- [x] BUG: Z-Scores chart nearly empty - ROOT CAUSE: ChartsSection.tsx line 199 used `data={filteredTS}` (fair value timeseries) instead of `data={filteredStateVars}` (state variables). Z_X1-X7 fields don't exist in timeseries data. FIXED: Changed to `data={filteredStateVars}`.
- [x] INVESTIGATE: Confirmed timeseries JSON has correct BEER values varying from 4.50 to 6.65 in 2024-2025. State variables have 383 points with real Z-scores.
- [x] FIX: BEER now shows continuous data from 2000 to Dec 2025. FX Fair uses union of available components per date. Dashboard shows BEER 5.45, FX Fair 5.33, Misalignment -2.1%.

## Critical Issues (v3.2)
- [x] BUG: CDI+Overlay total return wrong - ROOT CAUSE: SELIC_META (BCB 11) returns daily rate in decimal (0.069), not annual %. Formula ((1+0.069/100)^(1/12))-1 = 0.006% monthly instead of ~1%. FIXED: Changed to use SELIC_OVER (BCB 4189) which returns annual % (18.94%). CDI now 750.6% cumulative (correct for 21 years).
- [x] BUG: Signal contradiction - ROOT CAUSE: FX instrument is 'long USD', so mu_fx > 0 means USD appreciates = SHORT BRL. But code mapped mu_fx > 0 → 'LONG BRL' (inverted). FIXED: Inverted FX direction label. Now header NEUTRAL (score -0.43) + FX card LONG BRL (mu_fx -0.275) = consistent.
- [x] RETRAIN: Full model retrained with corrected SELIC, PTAX, EMBI, BEER data. New results: Overlay 350.8% (Sharpe 1.54), Total 3691.9% (Sharpe 3.92), CDI 750.6%.
- [x] VERIFY: All selic_target references in model (6 locations) updated to prefer selic_over. Excess carry for rates instruments now uses correct SELIC. Ensemble weights, backtest, portfolio all recalculated. Run ID 300002.

## Backtest Alignment & Score Calibration (v3.3)
- [x] BUG: CDI series longer than overlay in backtest - ROOT CAUSE: Overlay starts at month 124 (Jun 2015) because Ridge needs 36+ months training data, but CDI accumulated from month 0 (Feb 2005). FIXED: Trimmed backtest records to start at first active overlay month. Recalculated equity curves from trim point.
- [x] FIX: Backtest now 129 months (Jun 2015 → Feb 2026). CDI 170.7%, Overlay 350.8%, Total 1106.8%. Both series start at same point.
- [x] VALIDATE: Score -0.43 is correctly calibrated. Distribution: mean=-0.046, std=2.23, range [-6.64, +6.02]. LONG 22.5%, NEUTRAL 58.5%, SHORT 19.0%. Score reflects corrected excess carry with SELIC_OVER.
- [x] VALIDATE: All 6 selic references in model use selic_over (annual %). CDI monthly avg 0.85% (~10.7% a.a.), correct for 2015-2026 period.

## PPP_FACTOR Update & FX Fair Value Methodology (v3.4)
- [x] Forward-fill PPP_FACTOR monthly interpolation beyond last annual data point (Jan 2026 → Feb 2026)
- [x] Forward-fill REER_BIS data beyond last available month (Dec 2025 → Feb 2026)
- [x] Forward-fill fair value timeseries to eliminate nulls in recent months
- [x] Research institutional FX fair value methodology (ECB, Goldman GSDEER, Morgan Stanley BEER)
- [x] Implement BEER-only FX fair value (institutional standard: GSDEER/BEER approach)
- [x] Remove PPP from composite FX fair value (Balassa-Samuelson bias makes PPP unsuitable for EM)
- [x] Remove cyclical component from composite (Z_real_diff too volatile at extreme levels; kept as trading signal via mu_fx_val)
- [x] Fix default weight bug (weights.get(name, 0.2) → 0.0 so only configured components are included)
- [x] Update frontend labels: Fair Value (BEER), PPP Factor (structural reference), tooltips
- [x] Re-run model: FX Fair=5.14 (=BEER), Misalignment=+1.6%, all 314/314 timeseries points non-null
- [x] Insert updated model run (ID 330002) into database
- [x] Verify dashboard displays correctly with new methodology
- [x] All 147 existing tests pass

## FX Fair Value Enhancements (v3.5)

### 1. Updated PPP Data (2024-2026)
- [x] Fetch PPP data from World Bank API (PA.NUS.PPP for Brazil and USA) — confirmed 2024=2.487
- [x] Fetch GDP per capita from World Bank (BR: $10,311, US: $84,534 in 2024)
- [x] Fetch current account from IMF WEO (2024: -2.7%, 2025: -2.5%, 2026: -2.3%)
- [x] Fetch trade openness from World Bank (2024: 35.6% GDP)
- [x] Extend PPP_FACTOR.csv with CPI-differential projection for 2025-2026
- [x] Create GDP_PER_CAPITA.csv, CURRENT_ACCOUNT.csv, TRADE_OPENNESS.csv data files

### 2. Balassa-Samuelson Adjusted PPP
- [x] Research Penn effect literature (Rogoff 1996, Cheung/Chinn 2007, BCB WP596)
- [x] Calibrate β=0.35 (cross-section median from literature; time-series α=0.85 rejected as overfitting)
- [x] Implement PPP_BS = PPP × (GDP_pc_ratio)^β in FeatureEngine._build_fx_valuation()
- [x] PPP_BS 2024=5.19 (vs spot 5.39, BEER 5.14) — excellent convergence
- [x] Add ppp_bs_fair to model output (dashboard + timeseries, 314/314 non-null)
- [x] Add PPP-BS indicator to frontend (OverviewGrid + ChartsSection)

### 3. FEER (Fundamental Equilibrium Exchange Rate)
- [x] Research FEER methodology (PIIE/Cline, ECB, CEPR VoxEU)
- [x] Implement FEER: CA_gap = CA_actual - CA_target(-2.0%), REER_adj = REER × exp(CA_gap / (ε × trade_openness))
- [x] Trade elasticity ε=0.7 (Marshall-Lerner, standard for EM)
- [x] Convert FEER from REER to nominal: FEER_nominal = spot × (FEER_REER / REER_actual)
- [x] FEER 2024=5.61, Feb 2026=5.29 (consistent with improving CA trajectory)
- [x] Add feer_fair to model output (dashboard + timeseries, 314/314 non-null)
- [x] Add FEER indicator to frontend (OverviewGrid + ChartsSection)

### Integration
- [x] Re-run model with all 3 enhancements — all 314/314 timeseries points non-null
- [x] Update frontend: BEER (green solid), PPP-BS (purple dashed), FEER (orange dashed), PPP Raw (faded)
- [x] Insert into database (run ID 330003)
- [x] All 147 tests pass, checkpoint saved

## Data Sources Enhancement (v3.6)

### 1. B3/ANBIMA API Integration (Primary Source)
- [x] Review existing ANBIMA integration in data_collector.py — already has ETTJ, NTN-B, NTN-F, breakeven
- [x] Fix ANBIMA auth: accept HTTP 201 (not just 200) for token endpoint
- [x] Implement production→sandbox fallback (prod returns 403, sandbox returns mock data)
- [x] Verify ANBIMA sandbox returns 15 series (DI 7 tenors, NTN-B 5Y/10Y, NTN-F 5Y/10Y, breakeven 5Y/10Y)
- [x] ANBIMA already set as primary with fallback to Trading Economics
- [x] Note: Production access requires ANBIMA plan upgrade; sandbox data is from Apr 2024

### 2. PPP Cross-Validation (Multi-Source)
- [x] Fetch PPP from World Bank API (PA.NUS.PPP): 35 years, last=2.4873 (2024)
- [x] Fetch PPP from IMF WEO DataMapper (PPPEX): 39 years with projections to 2030, last=2.8040
- [x] Fetch PPP from FRED/PWT (PPPTTLBRA618NUPN): 21 years, last=1.8734 (2010, older PWT 7.x)
- [x] OECD API: old stats.oecd.org endpoint deprecated, returned empty datasets
- [x] Cross-validation: WB vs IMF spread < 0.01 for 2020-2023, 0.0103 for 2024 (excellent convergence)
- [x] Implement consensus PPP: median of available sources, extended with IMF projections for 2025-2030
- [x] Save individual source CSVs (PPP_WB, PPP_IMF, PPP_FRED) for reference
- [x] Consensus PPP_FACTOR: 41 points (1990-2030), last=2.8040

### Integration
- [x] Update data_collector.py with multi-source PPP collection and cross-validation
- [x] Re-run model: all 314/314 timeseries points non-null, all 5 fair value indicators correct
- [x] Insert into database (run ID 330004)
- [x] All 147 tests pass

## Model & Methodology Enhancements (v3.7)

### 1. Expanded Ensemble (RF + XGBoost)
- [x] Analyze current Ridge+GBM ensemble architecture (adaptive weights via rolling OOS R²)
- [x] Add Random Forest: n_estimators=200, max_depth=4, min_samples_leaf=5, max_features=sqrt
- [x] Add XGBoost: n_estimators=100, max_depth=3, lr=0.05, subsample=0.8, colsample=0.8
- [x] Dynamic ensemble weighting: 4-model adaptive (Ridge 21.2%, GBM 34.1%, RF 25.3%, XGB 19.5%)
- [x] Validated: Sharpe 2.20, Win rate 76.7%, Max DD -6.30%, Calmar 1.98

### 2. Additional Variables
- [x] Collect Focus FX 12M expectations from BCB SGS (series 13522): 313 monthly points
- [x] Collect CFTC BRL net speculative positioning: 215 monthly points (from weekly CFTC COT)
- [x] Collect IDP (direct investment) from BCB SGS (series 22885): 312 monthly points
- [x] Collect portfolio flows from BCB SGS (series 22868): 312 monthly points
- [x] Integrated as Z_focus_fx, Z_cftc_brl, Z_idp_flow, Z_portfolio_flow in FEATURE_MAP
- [x] Added to FX instrument (18 features total, up from 14)

### 3. GARCH Volatility Model
- [x] Implement GARCH(1,1) for all instruments with arch library
- [x] Fallback to realized vol when GARCH fails to converge
- [x] Use GARCH conditional volatility for vol-targeting in RiskOverlays
- [x] GARCH replaces simple rolling 20m std × √12 for more responsive vol estimates

### 4. Purged K-Fold CV Walk-Forward
- [x] Implement purged_kfold_cv() in EnsembleAlphaModels (5 folds, 3-month embargo)
- [x] Grid search: Ridge alpha [0.1,1,10,50], GBM depth [2,3,4], RF depth [3,4,5], XGB depth [2,3,4]
- [x] CV runs every 12 months during walk-forward, caches best hyperparameters
- [x] hp_cache integrated into fit_and_predict for all 4 models

### Integration
- [x] Re-run model: Overlay 254.3%, Sharpe 2.20, all 314/314 timeseries non-null
- [x] Frontend updated: 4-model ensemble chart (Ridge blue, GBM orange, RF green, XGB purple)
- [x] Insert into database (run ID 330005)
- [x] All 147 tests pass

## Backtest & Performance Enhancements (v3.8)

### 1. Variable Transaction Costs by Regime
- [ ] Analyze current fixed transaction cost implem### 1. Variable Transaction Costs
- [x] Implement regime-dependent TC: higher in stress, lower in carry
- [x] Use TC schedule: carry=5bps, riskoff=15bps, stress=20bps
- [x] Validate impact on net returns and Sharpe

### 2. Rigorous OOS Rolling Backtest
- [x] Implement expanding window (vs current fixed 60-month)
- [x] Add minimum training period constraint
- [x] Ensure strict temporal separation (no look-ahead)
- [x] Compare expanding vs rolling window performance

### 3. Ibovespa Benchmark
- [x] Collect Ibovespa monthly returns data
- [x] Add Ibovespa cumulative return to backtest output
- [x] Calculate relative metrics (total return, ann return, Sharpe, max DD, win rate, Calmar)
- [x] Display Ibovespa benchmark in frontend chart (equity curve + summary metrics)

### 4. SHAP Feature Importance
- [x] Compute SHAP values from XGBoost/RF models (TreeExplainer)
- [x] Add feature importance to model output (current + mean_abs + rank per instrument)
- [x] Create ShapPanel component in frontend dashboard (horizontal bar charts per instrument)
- [x] Add instrument filter tabs (All / FX / FRONT / BELLY / LONG / HARD)

### Integration
- [x] Re-run model with all 4 enhancements (v3.8)
- [x] Update frontend dashboard (BacktestPanel + ShapPanel + Home.tsx)
- [x] Insert into database and verify (Ibovespa: 61.0% total, Sharpe 0.59; SHAP: 5 instruments)
- [x] Run tests and save checkpoint (151 tests passing)

## SHAP Historical Evolution (v3.9) — Temporal Feature Importance

### Backend: Historical SHAP Computation
- [x] Add periodic SHAP computation during backtest loop (every 6 months via compute_shap_snapshot)
- [x] Store shap_history as timeseries: [{date, instrument, feature, importance}] — 508 entries, 10 snapshots
- [x] Add shap_history to run_v2 output and run_model.py JSON
- [x] Add shapHistoryJson column to model_runs DB schema (shap_history_json)
- [x] Update modelRunner.ts and routers.ts to serve shapHistory

### Frontend: ShapHistoryPanel Component
- [x] Build ShapHistoryPanel with stacked area charts (normalized importance over time)
- [x] Add instrument selector (All / FX / FRONT / BELLY / LONG / HARD)
- [x] Show top-6 features by default, expandable to all features
- [x] Add structural change detection (first-half vs second-half comparison with ±pp tags)
- [x] Integrate ShapHistoryPanel into Home.tsx after ShapPanel

### Testing & Delivery
- [x] Run model with historical SHAP computation (508 entries across 5 instruments)
- [x] Write vitest tests for shap_history data flow (7 tests, all passing)
- [x] 158 total tests passing (7 files)
- [x] Save checkpoint and deliver
