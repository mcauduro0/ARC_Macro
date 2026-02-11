# ARC Macro Risk OS

**Institutional Cross-Asset Macro Risk Operating System for Brazil**

A full-stack dashboard that integrates FX, local rates (front-end and long-end), and hard currency sovereign into a unified risk framework. Built for institutional macro trading desks.

---

## Architecture

```
┌─────────────────────────────────────────────────┐
│                  Dashboard (React)               │
│  Status Bar → Overview Grid → Charts → Actions   │
├─────────────────────────────────────────────────┤
│              tRPC API (Express)                   │
│  model.latest | model.timeseries | model.run     │
├─────────────────────────────────────────────────┤
│           Python Model Engine                     │
│  Data Collection → State Variables → E[r] Models  │
│  → Markov Regime → Sizing → Risk Aggregation     │
├─────────────────────────────────────────────────┤
│              MySQL (TiDB)                         │
│  model_runs | model_timeseries | users           │
└─────────────────────────────────────────────────┘
```

## Quantitative Model (8 Blocks)

| Block | Module | Description |
|-------|--------|-------------|
| 1 | **PPP Estrutural** | Purchasing Power Parity (absolute + relative) using IPCA/CPI differentials |
| 2 | **BEER Fundamental** | Behavioral Equilibrium Exchange Rate via OLS on 7 state variables |
| 3 | **Expected Return Models** | Regression-based E[r] for FX, Front-End DI, Long-End DI, Hard Currency |
| 4 | **Regime Markov 3-State** | Carry / RiskOff / Stress Doméstico with transition probabilities |
| 5 | **Sizing Engine** | Fractional Kelly with Sharpe estimation, factor exposure limits |
| 6 | **Risk Aggregation** | Rolling 2Y covariance, portfolio vol targeting, drawdown limits |
| 7 | **Stress Tests** | Historical scenarios: Taper 2013, Fiscal BR 2015, Covid 2020, Inflation 2022 |
| 8 | **Dashboard** | Real-time cross-asset command center with live data |

## 7 Unified State Variables

| Variable | Name | Composition |
|----------|------|-------------|
| X1 | Diferencial Real | (DI - IPCA_exp) - (UST - US_CPI_exp) |
| X2 | Surpresa Inflação | IPCA_yoy - IPCA_exp |
| X3 | Risco Fiscal | Z(Dívida/PIB) + Z(CDS 5Y) |
| X4 | Termos de Troca | Z(Terms of Trade Index) |
| X5 | Dólar Global | Z(DXY) |
| X6 | Risco Global | Z(VIX) + Z(NFCI) |
| X7 | Hiato do Produto | Output Gap proxy |

All variables are standardized with **rolling 5-year Z-scores** and **winsorized at 5%-95%**.

## Data Sources

| Source | Series | Priority |
|--------|--------|----------|
| **ANBIMA Feed API** | DI curve ETTJ (3M-10Y, 75 vertices), NTN-B yields (real), NTN-F yields (nominal), Breakeven inflation | **PRIMARY** |
| **Trading Economics** | DI curve (3M, 6M, 1Y, 2Y, 3Y, 5Y, 10Y) | Fallback |
| **FRED** | UST yields (2Y, 5Y, 10Y), VIX, DXY, NFCI, CPI, Breakevens (T5YIE, T10YIE), HY Spread | Primary (US) |
| **BCB** | IPCA, SELIC, PTAX, Dívida Bruta/PIB, Resultado Primário, FX Forwards | Primary (BR macro) |
| **IPEADATA** | EMBI+ Risco Brasil, SELIC Over | Supplementary |
| **Yahoo Finance** | USDBRL, Commodities (CRB), VIX, DXY | Fallback |

## Tech Stack

- **Frontend**: React 19 + Tailwind CSS 4 + Recharts + Framer Motion
- **Backend**: Express 4 + tRPC 11 + Drizzle ORM
- **Database**: MySQL (TiDB)
- **Model Engine**: Python 3.11 (statsmodels, pandas, numpy, yfinance)
- **Scheduler**: Node.js cron (daily 07:00 UTC / 04:00 BRT)

## Installation

```bash
# Clone
git clone https://github.com/mcauduro0/ARC_Macro.git
cd ARC_Macro

# Install dependencies
pnpm install

# Configure environment
cp .env.example .env
# Edit .env with your database URL and API keys

# Push database schema
pnpm db:push

# Install Python dependencies
pip install pandas numpy statsmodels yfinance requests fredapi

# Configure ANBIMA API (optional - falls back to Trading Economics)
# Register at https://developers.anbima.com.br
# For production access, email anbimafeed@anbima.com.br with your client_id

# Development
pnpm dev

# Production
pnpm build && pnpm start
```

## Environment Variables

```env
DATABASE_URL=mysql://user:pass@host:port/db?ssl={"rejectUnauthorized":true}
JWT_SECRET=your-jwt-secret
FRED_API_KEY=your-fred-api-key  # Free at https://fred.stlouisfed.org/docs/api/api_key.html
ANBIMA_CLIENT_ID=your-client-id  # Register at https://developers.anbima.com.br
ANBIMA_CLIENT_SECRET=your-client-secret
ANBIMA_BASE_URL=https://api-sandbox.anbima.com.br  # Switch to api.anbima.com.br for production
```

## API Endpoints (tRPC)

| Procedure | Type | Auth | Description |
|-----------|------|------|-------------|
| `model.latest` | Query | Public | Latest model run with all cross-asset data |
| `model.timeseries` | Query | Public | Historical timeseries (fair values, Z-scores) |
| `model.status` | Query | Public | Model execution status |
| `model.run` | Mutation | Protected | Trigger manual model execution |

## Project Structure

```
client/src/
  components/
    StatusBar.tsx          # Live/Static indicator, spot, score, regime
    OverviewGrid.tsx       # 4 asset classes + state variables + regime
    ChartsSection.tsx      # Interactive charts with time filters
    StressTestPanel.tsx    # Stress test visualization with per-asset breakdown
    ActionPanel.tsx        # Portfolio-level risk metrics and sizing
    ModelDetails.tsx       # Regression statistics and model diagnostics
  hooks/
    useModelData.ts        # tRPC data hook with fallback to embedded data
  pages/
    Home.tsx               # Main dashboard page

server/
  model/
    data_collector.py      # Multi-source data collection (ANBIMA, TE, FRED, BCB, Yahoo)
    macro_risk_os.py       # Full Macro Risk OS engine (8 blocks)
    run_model.py           # Entry point for model execution
  modelRunner.ts           # Python execution bridge (child_process)
  routers.ts               # tRPC API endpoints
  db.ts                    # Database helpers

drizzle/
  schema.ts                # Database schema (model_runs, model_timeseries, users)
```

## License

MIT
