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
