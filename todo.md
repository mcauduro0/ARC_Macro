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
