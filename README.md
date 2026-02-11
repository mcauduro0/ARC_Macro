# ARC Macro Risk OS

Sistema institucional de análise macro para câmbio e juros brasileiros. Integra modelos quantitativos de FX (BRLUSD), juros locais (DI front-end e long-end) e crédito soberano (hard currency) em um dashboard operacional unificado.

---

## Arquitetura

```
┌─────────────────────────────────────────────────────────────┐
│                    Dashboard (React + Recharts)              │
│  Status Bar │ 4 Asset Cards │ State Vars │ Regime │ Charts  │
└──────────────────────────┬──────────────────────────────────┘
                           │ tRPC API
┌──────────────────────────┴──────────────────────────────────┐
│                   Backend (Express + tRPC)                    │
│  Model Runner │ Scheduler (07:00 UTC) │ MySQL Storage        │
└──────────────────────────┬──────────────────────────────────┘
                           │ child_process (Python 3.11)
┌──────────────────────────┴──────────────────────────────────┐
│                  Macro Risk OS Engine (Python)               │
│  Data Collector │ State Variables │ Expected Return Models   │
│  Markov Regime │ Sizing Engine │ Risk Aggregation            │
└─────────────────────────────────────────────────────────────┘
```

---

## Modelo Quantitativo

### Variáveis de Estado Unificadas (X1-X7)

| Variável | Nome | Composição |
|----------|------|------------|
| X1 | Diferencial Real | (DI - IPCA_exp) - (UST - US_CPI_exp) |
| X2 | Surpresa Inflação | IPCA_yoy - IPCA_exp |
| X3 | Risco Fiscal | zscore(Dívida/PIB) + zscore(CDS 5Y) |
| X4 | Termos de Troca | zscore(Índice ToT) |
| X5 | Dólar Global | zscore(DXY) |
| X6 | Risco Global | zscore(VIX) |
| X7 | Hiato do Produto | Output gap proxy |

Todas as variáveis são padronizadas via Z-score rolling 5 anos com winsorização 5%-95%.

### Classes de Ativos

| Classe | Instrumento | Risk Unit | Modelo |
|--------|-------------|-----------|--------|
| FX | USDBRL spot | FX vol | PPP + BEER + Cíclico |
| Front-End | DI 1Y | DV01 | Taylor Rule + Carry |
| Long-End | DI 5Y | DV01 | Term Premium + Fiscal |
| Hard Currency | EMBI spread | Spread DV01 | CDS + UST + Risk |

### Regime Markov 3-Estados

- **Carry**: Ambiente benigno, carry trade favorável
- **RiskOff**: Aversão a risco global (VIX elevado, DXY forte)
- **Stress Doméstico**: Crise fiscal/política brasileira

### Sizing

Peso ótimo via fractional Kelly (f = 0.25):

```
w_i = f × E[r_i] / σ²_i × regime_adj
```

Sujeito a: limites de exposição fatorial, target vol do portfólio, drawdown máximo.

---

## Stack Tecnológico

- **Frontend**: React 19, Tailwind CSS 4, Recharts, Framer Motion, shadcn/ui
- **Backend**: Express 4, tRPC 11, Drizzle ORM, MySQL (TiDB)
- **Modelo**: Python 3.11, statsmodels, pandas, numpy, yfinance, fredapi
- **Fontes de Dados**: BCB (SGS), FRED, Yahoo Finance, IPEADATA

---

## Instalação

### Pré-requisitos

- Node.js 22+
- Python 3.11+
- MySQL/TiDB
- pnpm

### Setup

```bash
# Instalar dependências Node
pnpm install

# Instalar dependências Python
pip install pandas numpy statsmodels yfinance fredapi requests

# Configurar variáveis de ambiente
cp .env.example .env
# Editar .env com suas credenciais

# Rodar migrações do banco
pnpm db:push

# Iniciar em desenvolvimento
pnpm dev
```

### Variáveis de Ambiente Necessárias

```
DATABASE_URL=mysql://user:pass@host:port/db
JWT_SECRET=your-jwt-secret
FRED_API_KEY=your-fred-api-key
```

---

## Estrutura de Diretórios

```
ARC_Macro/
├── client/                    # Frontend React
│   ├── src/
│   │   ├── components/        # StatusBar, OverviewGrid, ChartsSection, ActionPanel, ModelDetails
│   │   ├── hooks/             # useModelData (tRPC + fallback)
│   │   ├── data/              # Dados embutidos (fallback)
│   │   └── pages/             # Home (dashboard principal)
│   └── public/
├── server/                    # Backend Express + tRPC
│   ├── _core/                 # Framework (OAuth, context, env)
│   ├── model/                 # Python engine
│   │   ├── macro_risk_os.py   # Motor principal Macro Risk OS
│   │   ├── model_engine.py    # Motor legacy FX-only
│   │   ├── data_collector.py  # Coleta de dados expandida
│   │   ├── data_collection.py # Coleta de dados legacy
│   │   └── run_model.py       # Script runner
│   ├── modelRunner.ts         # Executor Python + scheduler
│   ├── db.ts                  # Helpers de banco
│   ├── routers.ts             # API tRPC endpoints
│   └── storage.ts             # S3 helpers
├── drizzle/                   # Schema + migrações
│   └── schema.ts              # Tabelas: users, model_runs, model_timeseries
├── shared/                    # Tipos compartilhados
├── scripts/                   # Scripts utilitários
└── todo.md                    # Tracking de features
```

---

## API Endpoints (tRPC)

| Procedure | Tipo | Auth | Descrição |
|-----------|------|------|-----------|
| `model.latest` | Query | Public | Dados mais recentes do Macro Risk OS |
| `model.history` | Query | Public | Histórico de runs (últimos 30) |
| `model.status` | Query | Public | Status de execução (running/idle) |
| `model.run` | Mutation | Protected | Disparar nova execução do modelo |

---

## Scheduler

O modelo executa automaticamente às **07:00 UTC** (04:00 BRT) diariamente. O scheduler verifica se já houve um run no dia e pula se já existir. Execução manual disponível via botão "Refresh" no dashboard (requer autenticação).

---

## Testes

```bash
pnpm test
```

11 testes vitest cobrindo: API endpoints, autenticação, cross-asset data, regime data, state variables.

---

## Licença

Proprietário. Uso interno apenas.
