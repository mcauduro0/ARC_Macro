# SOP — Macro Risk OS v3.10

## Standard Operating Procedure: Documentação Técnica e Operacional Completa

**Versão:** 3.10.5  
**Data:** Fevereiro 2026  
**Classificação:** Confidencial — Uso Interno  
**Autor:** Equipe Quantitativa

---

## Sumário

1. [Visão Geral do Sistema](#1-visão-geral-do-sistema)
2. [Arquitetura Técnica](#2-arquitetura-técnica)
3. [Pipeline de Dados](#3-pipeline-de-dados)
4. [Modelo Quantitativo](#4-modelo-quantitativo)
5. [Motor de Regime (HMM)](#5-motor-de-regime-hmm)
6. [Otimizador de Portfólio](#6-otimizador-de-portfólio)
7. [Overlays de Risco](#7-overlays-de-risco)
8. [Backtest Walk-Forward](#8-backtest-walk-forward)
9. [Stress Tests](#9-stress-tests)
10. [SHAP e Interpretabilidade](#10-shap-e-interpretabilidade)
11. [Sistema de Alertas e Notificações](#11-sistema-de-alertas-e-notificações)
12. [Banco de Dados](#12-banco-de-dados)
13. [Frontend e Dashboard](#13-frontend-e-dashboard)
14. [Procedimentos Operacionais](#14-procedimentos-operacionais)
15. [Parâmetros de Configuração](#15-parâmetros-de-configuração)
16. [Glossário](#16-glossário)

---

## 1. Visão Geral do Sistema

O **Macro Risk OS** é um sistema quantitativo de alocação tática para ativos brasileiros de renda fixa e câmbio, operando como um overlay sobre CDI. O sistema combina modelos de machine learning (ensemble de Ridge, GBM, Random Forest e XGBoost), detecção de regime via Hidden Markov Models (HMM) de dois níveis, e otimização de portfólio com overlays de risco dinâmicos.

O objetivo central é gerar retornos excedentes (alpha) sobre o CDI através da alocação tática em cinco instrumentos:

| Instrumento | Descrição | Proxy de Mercado | Duration Aprox. |
|---|---|---|---|
| **FX** | NDF USDBRL 1M (long USD) | PTAX / USDBRL | N/A |
| **Front-End** | Receptor DI 1Y | DI Jan+1 | 1.0 ano |
| **Belly** | Receptor DI 5Y | DI Jan+5 | 4.5 anos |
| **Long-End** | Receptor DI 10Y | DI Jan+10 | 7.5 anos |
| **Hard Currency** | Spread soberano (EMBI+) | EMBI+ / CDS 5Y | 5.0 anos |

O sistema opera em frequência **mensal**, com rebalanceamento ao final de cada mês. A janela de treinamento é de **36 meses rolling**, e o backtest out-of-sample cobre o período de agosto de 2015 até o presente (aproximadamente 127 meses).

---

## 2. Arquitetura Técnica

### 2.1 Stack Tecnológico

O sistema é construído sobre uma arquitetura full-stack moderna com separação clara entre o motor quantitativo (Python) e a camada de apresentação/API (Node.js/React):

| Camada | Tecnologia | Função |
|---|---|---|
| **Modelo Quantitativo** | Python 3.11 (NumPy, Pandas, scikit-learn, XGBoost, hmmlearn, SHAP, arch) | Coleta de dados, feature engineering, alpha models, regime detection, backtest, stress tests |
| **Backend API** | Node.js + Express + tRPC 11 | API tipada, autenticação OAuth, orquestração do modelo, alertas |
| **Frontend** | React 19 + Tailwind CSS 4 + Recharts | Dashboard institucional, visualizações, painéis interativos |
| **Banco de Dados** | MySQL/TiDB (Drizzle ORM) | Persistência de runs, alertas, changelog, usuários |
| **Autenticação** | Manus OAuth + JWT | Sessões seguras, cookies httpOnly |

### 2.2 Estrutura de Diretórios

```
brlusd-dashboard/
├── server/
│   ├── model/
│   │   ├── macro_risk_os_v2.py      # Motor quantitativo principal (~3600 linhas)
│   │   ├── run_model.py             # Orquestrador: coleta → modelo → dashboard JSON
│   │   ├── data_collector.py        # Pipeline de coleta multi-source (~1280 linhas)
│   │   └── data/                    # CSVs de séries temporais (cache local)
│   ├── routers.ts                   # Endpoints tRPC (model.*, alerts.*, changelog.*)
│   ├── modelRunner.ts               # Scheduler e executor do modelo
│   ├── alertEngine.ts               # Geração de alertas e notificações push
│   ├── db.ts                        # Helpers de query (Drizzle)
│   └── _core/                       # Framework: OAuth, LLM, storage, notification
├── client/src/
│   ├── pages/Home.tsx               # Dashboard principal
│   ├── components/                  # 17 componentes React
│   │   ├── StatusBar.tsx            # Barra de status (spot, score, regime, direction)
│   │   ├── OverviewGrid.tsx         # 5 cards de instrumentos (FX, Front, Belly, Long, Hard)
│   │   ├── ChartsSection.tsx        # Séries históricas (6 tabs: Score, Regime, Z-Scores, etc.)
│   │   ├── BacktestPanel.tsx        # Equity curve, attribution, métricas
│   │   ├── ShapPanel.tsx            # SHAP feature importance (barras horizontais)
│   │   ├── ShapHistoryPanel.tsx     # Evolução temporal do SHAP
│   │   ├── StressTestPanel.tsx      # 6 cenários de stress históricos
│   │   ├── ActionPanel.tsx          # Expected return, sizing, risk metrics
│   │   ├── ModelAlertsPanel.tsx     # Alertas (regime change, SHAP shift, drawdown)
│   │   ├── ModelChangelogPanel.tsx  # Changelog com deltas entre versões
│   │   └── ModelDetails.tsx         # Detalhes de regressão e ensemble weights
│   └── hooks/useModelData.ts        # Hook central de dados (tRPC queries)
├── drizzle/schema.ts                # Schema do banco (5 tabelas)
└── shared/                          # Tipos e constantes compartilhados
```

### 2.3 Fluxo de Execução

O fluxo completo de uma execução do modelo segue esta sequência:

```
1. TRIGGER (manual via tRPC ou scheduled)
   └─→ modelRunner.ts::runModel()

2. DATA COLLECTION (Python: data_collector.py)
   └─→ 7 fontes: ANBIMA → Trading Economics → FRED → FMP → Yahoo → BCB → IPEADATA
   └─→ Merge, validação, salvamento em CSVs

3. MODEL EXECUTION (Python: macro_risk_os_v2.py::run_v2())
   ├─→ DataLayer: load CSVs → build monthly → compute instrument returns
   ├─→ FeatureEngine: Z-scores, BEER, CIP basis, Taylor Rule, carry, term premium
   ├─→ BacktestHarness (walk-forward):
   │   ├─→ RegimeModel.fit() (HMM expanding window, refit every 12m)
   │   ├─→ EnsembleAlphaModels.fit_and_predict() (Ridge+GBM+RF+XGB, 36m rolling)
   │   ├─→ ProductionEngine.step():
   │   │   ├─→ IC gating → Score demeaning → Regime adjustment
   │   │   ├─→ Covariance (Ledoit-Wolf shrinkage, 36m)
   │   │   ├─→ Optimizer.optimize() (SLSQP, regime-conditional limits)
   │   │   └─→ RiskOverlays.apply() (drawdown, vol target, circuit breaker)
   │   ├─→ Mark-to-market → Record metrics
   │   └─→ SHAP snapshots (every 6 months)
   ├─→ StressTestEngine: 6 cenários históricos
   └─→ Output JSON (dashboard + backtest + stress + SHAP)

4. DASHBOARD CONSTRUCTION (Python: run_model.py)
   └─→ Transform output → dashboard JSON (positions, regime, fair values, etc.)

5. DATABASE PERSISTENCE (Node.js: modelRunner.ts)
   └─→ INSERT into model_runs (dashboard_json, backtest_json, shap_json, etc.)

6. POST-RUN ALERTS (Node.js: alertEngine.ts)
   ├─→ Detect: regime change, SHAP shift, score change, drawdown
   ├─→ INSERT into model_alerts
   ├─→ INSERT into model_changelog
   └─→ Push notifications via notifyOwner()
```

---

## 3. Pipeline de Dados

### 3.1 Fontes de Dados

O sistema coleta dados de **7 fontes primárias** com hierarquia de prioridade e fallback automático:

| Fonte | Dados Coletados | Prioridade | Frequência |
|---|---|---|---|
| **ANBIMA Feed API** | ETTJ (curva DI pré), NTN-B yields, breakevens | Primária (BR rates) | Diária |
| **Trading Economics** | DI curve (3M-10Y) | Fallback (BR rates) | Diária |
| **FRED** | UST yields (2Y, 5Y, 10Y), VIX, DXY, NFCI, US CPI, breakevens, HY spread | Primária (US) | Diária/Semanal |
| **FMP (Financial Modeling Prep)** | UST backup, calendário econômico | Backup (US rates) | Diária |
| **Yahoo Finance** | USDBRL, commodities (BCOM, iron ore), EWZ, Ibovespa | Primária (FX/Equity) | Diária |
| **BCB SGS** | IPCA (mensal + 12M), SELIC (meta + over), PTAX, Dívida/PIB, balanço de pagamentos, IDP, fluxo de portfólio, cupom cambial (Swap DI×Dólar) | Primária (BR macro) | Mensal |
| **IPEADATA** | EMBI+, SELIC Over, NTN-B yields | Complementar | Mensal |

Adicionalmente, dados estruturais são coletados do **World Bank** (PPP, GDP per capita) e **BIS** (REER).

### 3.2 Séries Temporais Coletadas

O sistema mantém aproximadamente **60+ séries temporais** em cache local (diretório `server/model/data/`), organizadas por categoria:

**Câmbio e FX:**
- `USDBRL.csv`, `PTAX.csv` — Spot USDBRL
- `SWAP_DIXDOL_30D.csv`, `SWAP_DIXDOL_90D.csv`, `SWAP_DIXDOL_360D.csv` — Cupom cambial (BCB 7811)
- `FX_CUPOM_LIMPO_30D.csv` — Cupom limpo (BCB 3954, fallback)
- `FOCUS_FX_12M.csv` — Pesquisa Focus: expectativa USDBRL 12M
- `CFTC_BRL_NET_SPEC.csv` — Posicionamento especulativo CFTC

**Curva DI (Juros Brasileiros):**
- `DI_3M.csv`, `DI_6M.csv`, `DI_1Y.csv`, `DI_2Y.csv`, `DI_5Y.csv`, `DI_10Y.csv`
- `ANBIMA_DI_*` — Overrides da ANBIMA (quando disponíveis)
- `SELIC_META.csv`, `SELIC_OVER.csv`

**Inflação:**
- `IPCA_MONTHLY.csv` — Variação mensal IPCA (BCB 433)
- `IPCA_12M.csv` — IPCA acumulado 12 meses
- `IPCA_EXP_12M.csv` — Expectativa IPCA 12M (Focus)

**Taxas US:**
- `UST_2Y.csv`, `UST_5Y.csv`, `UST_10Y.csv` — Treasury yields
- `US_TIPS_5Y.csv`, `US_TIPS_10Y.csv` — TIPS (juros reais)
- `US_BREAKEVEN_10Y.csv` — Breakeven de inflação
- `US_CPI_EXP.csv` — Expectativa CPI

**Risco e Crédito:**
- `CDS_5Y.csv` — CDS Brasil 5Y
- `EMBI_SPREAD.csv` — EMBI+ spread
- `US_HY_SPREAD.csv` — US High Yield spread
- `VIX_YF.csv` — VIX
- `DXY_YF.csv` — Dollar Index

**Macro Brasil:**
- `DIVIDA_BRUTA_PIB.csv` — Dívida bruta/PIB
- `PRIMARY_BALANCE.csv` — Resultado primário
- `TERMS_OF_TRADE.csv` — Termos de troca
- `IBC_BR.csv` — Índice de atividade econômica
- `BOP_CURRENT.csv` — Conta corrente
- `IDP_FLOW.csv` — Investimento direto no país
- `PORTFOLIO_FLOW.csv` — Fluxo de portfólio

**Estruturais:**
- `PPP_FACTOR.csv` — Paridade do poder de compra
- `REER_BIS.csv` / `REER_BCB.csv` — Taxa de câmbio real efetiva
- `GDP_PER_CAPITA.csv` — PIB per capita (para Balassa-Samuelson)
- `CURRENT_ACCOUNT.csv` — Conta corrente/PIB
- `TRADE_OPENNESS.csv` — Abertura comercial

### 3.3 Processo de Merge e Validação

O `data_collector.py` implementa uma hierarquia de merge rigorosa:

1. **ANBIMA como primária** para taxas brasileiras (DI curve, NTN-B, breakevens). Trading Economics é armazenado como fallback sob prefixo `TE_`.
2. **Cross-validation** automática: quando ambas as fontes estão disponíveis, calcula correlação entre ANBIMA e TE para validar consistência.
3. **Construção da curva DI**: se dados diretos não estão disponíveis, o sistema constrói taxas sintéticas a partir de SELIC + spread (e.g., `DI_1Y = SELIC + spread_1y_hist`).
4. **Validação**: verifica cobertura temporal, detecta gaps, e alerta sobre séries com dados insuficientes.

### 3.4 Tratamento de Dados Especiais

O sistema aplica tratamentos específicos para garantir consistência:

- **IPCA 12M**: calculado via composição rolling de 12 meses da variação mensal `(1+m1/100)×(1+m2/100)×...×(1+m12/100) - 1) × 100`, não usando o índice bruto.
- **PPP Factor**: dados anuais são interpolados linearmente para frequência mensal, com forward-fill de até 6 meses.
- **REER**: forward-fill de até 6 meses para compensar o lag de publicação do BIS.
- **EMBI Spread**: normalização automática se valores estão em unidades erradas (`> 2000 → /100`). Fallback para `CDS_5Y / 0.7` se EMBI indisponível.
- **Winsorização**: todas as séries de retorno são winzorizadas nos percentis 5-95 para limitar outliers.

---

## 4. Modelo Quantitativo

### 4.1 Feature Engineering

O `FeatureEngine` constrói **30+ features** organizadas em categorias:

#### 4.1.1 Z-Scores Macroeconômicos (Rolling 36m)

Cada Z-score é calculado como `Z = (x - mean_36m) / std_36m`, usando janela rolling de 36 meses:

| Feature | Fórmula | Interpretação |
|---|---|---|
| `Z_real_diff` | `(DI_1Y - IPCA_exp) - (UST_2Y - US_CPI_exp)` | Diferencial de juros reais BR-US |
| `Z_infl_surprise` | `IPCA_yoy - IPCA_exp` | Surpresa inflacionária |
| `Z_fiscal` | `mean(Z(debt_gdp), Z(cds_5y))` | Risco fiscal composto |
| `Z_tot` | `Z(terms_of_trade)` | Termos de troca |
| `Z_dxy` | `Z(DXY)` | Força do dólar global |
| `Z_vix` | `Z(VIX)` | Volatilidade implícita global |
| `Z_cds_br` | `Z(CDS_5Y)` ou `Z(EMBI)` | Risco-país |
| `Z_hy_spread` | `Z(US_HY_Spread)` | Apetite por risco global |
| `Z_ewz` | `Z(ret_EWZ)` | Retorno equity EM/BR |
| `Z_iron_ore` | `Z(ret_iron_ore)` | Retorno minério de ferro |
| `Z_bop` | `Z(BOP_current)` | Balanço de pagamentos |
| `Z_focus_fx` | `Z((spot - focus_exp) / focus_exp)` | Surpresa FX vs Focus |
| `Z_cftc_brl` | `Z(CFTC_net_spec)` | Posicionamento especulativo |
| `Z_idp_flow` | `Z(IDP_12m_sum)` | Fluxo de investimento direto |
| `Z_portfolio_flow` | `Z(portfolio_6m_sum)` | Fluxo de portfólio |

#### 4.1.2 Sinais de Valuation Cambial

| Feature | Metodologia | Descrição |
|---|---|---|
| `Z_beer` | BEER cointegration (OLS rolling 60m) | `log(REER) = f(ToT, BOP, IBC, real_diff) + ε`. Resíduo = misalignment. Positivo = BRL sobrevalorizado. |
| `Z_reer_gap` | `log(REER) - log(REER_trend_60m)` | Gap do REER vs tendência de longo prazo |
| `mu_fx_val` | BEER fair value com mean-reversion | `(BEER_fair - spot) / spot × β_cyclical`. Sinal de convergência ao fair value. |
| `ppp_bs_fair` | Balassa-Samuelson PPP | PPP ajustado por produtividade relativa (GDP per capita ratio) |
| `feer_fair` | Fundamental Equilibrium ER | Câmbio consistente com conta corrente sustentável e abertura comercial |

#### 4.1.3 Sinais de Carry

| Feature | Fórmula | Descrição |
|---|---|---|
| `carry_fx` | `(DI_1Y - cupom_cambial) / 100 / 12` | Carry do NDF 1M (prêmio forward) |
| `carry_front` | `(DI_1Y - SELIC) / 100 / 12` | Carry excedente do receptor 1Y |
| `carry_belly` | `(DI_5Y - SELIC) / 100 / 12` | Carry excedente do receptor 5Y |
| `carry_long` | `(DI_10Y - SELIC) / 100 / 12` | Carry excedente do receptor 10Y |
| `carry_hard` | `EMBI_spread / 10000 / 12` | Carry do spread soberano |

#### 4.1.4 Sinais Estruturais

| Feature | Metodologia | Descrição |
|---|---|---|
| `Z_term_premium` | `DI_10Y - DI_1Y` (slope da curva) | Prêmio de termo; alto = curva steep |
| `Z_tp_5y` | `DI_5Y - DI_1Y` | Prêmio de termo 5Y |
| `Z_cip_basis` | `(DI_swap - UST) - ((1+DI)/(1+UST) - 1)` | Desvio da paridade coberta de juros |
| `Z_fiscal_premium` | `CDS_5Y - f(VIX, DXY)` | Componente fiscal do CDS (resíduo) |
| `Z_debt_accel` | `Δ12m(debt_gdp)` | Aceleração da dívida/PIB |
| `Z_us_real_yield` | `Z(TIPS_10Y)` | Juros reais US |
| `Z_us_breakeven` | `Z(US_breakeven_10Y)` | Expectativa de inflação US |
| `Z_pb_momentum` | `Δ3m(primary_balance)` | Momentum do resultado primário |

#### 4.1.5 Taylor Rule

O sistema estima uma **Selic de equilíbrio** via Taylor Rule adaptada:

```
selic* = r* + π_exp + 0.5×(π_yoy - π_target) + 0.5×output_gap
```

Onde `r*` é estimado como a mediana rolling de 60 meses do juro real ex-ante `(SELIC - IPCA_exp)`. O gap `(SELIC_atual - selic*)` é usado como sinal para o front-end: gap positivo indica política monetária restritiva (sinal de receiver).

Fair values derivados:
- `front_fair = selic*` (fair value do DI 1Y)
- `belly_fair = selic* + term_premium_5y_hist` (fair value do DI 5Y)
- `long_fair = selic* + term_premium_10y_hist` (fair value do DI 10Y)

### 4.2 Alpha Models (Ensemble)

O sistema usa um **ensemble de 4 modelos** de machine learning, cada um treinado walk-forward por instrumento:

| Modelo | Tipo | Hiperparâmetros | Força |
|---|---|---|---|
| **Ridge** | Regressão linear regularizada | λ = 10.0 (default), CV purged | Estabilidade, interpretabilidade |
| **GBM** | Gradient Boosting (scikit-learn) | n_estimators=100, max_depth=3, lr=0.05 | Captura não-linearidades |
| **RF** | Random Forest | n_estimators=100, max_depth=4 | Robustez a outliers |
| **XGB** | XGBoost | n_estimators=100, max_depth=3, lr=0.05 | Performance em dados tabulares |

#### 4.2.1 Feature Map por Instrumento

Cada instrumento usa um subconjunto específico de features, refletindo seus drivers fundamentais:

| Instrumento | Features (18 max) |
|---|---|
| **FX** | Z_dxy, Z_vix, Z_cds_br, Z_real_diff, Z_tot, mu_fx_val, carry_fx, Z_cip_basis, Z_beer, Z_reer_gap, Z_hy_spread, Z_ewz, Z_iron_ore, Z_bop, Z_focus_fx, Z_cftc_brl, Z_idp_flow, Z_portfolio_flow |
| **Front-End** | Z_real_diff, Z_infl_surprise, Z_fiscal, carry_front, Z_term_premium, Z_us_real_yield, Z_pb_momentum, Z_portfolio_flow |
| **Belly** | Z_real_diff, Z_fiscal, Z_cds_br, Z_dxy, carry_belly, Z_term_premium, Z_tp_5y, Z_us_real_yield, Z_fiscal_premium, Z_us_breakeven, Z_portfolio_flow |
| **Long-End** | Z_fiscal, Z_dxy, Z_vix, Z_cds_br, carry_long, Z_term_premium, Z_fiscal_premium, Z_debt_accel, Z_us_real_yield, Z_portfolio_flow |
| **Hard Currency** | Z_vix, Z_cds_br, Z_fiscal, Z_dxy, carry_hard, Z_hy_spread, Z_us_real_yield, Z_ewz, Z_us_breakeven, Z_cftc_brl, Z_portfolio_flow |

#### 4.2.2 Treinamento Walk-Forward

Para cada mês `t` no backtest:

1. **Janela de treinamento**: `[t-36, t-1]` (36 meses rolling)
2. **Features disponíveis**: apenas features com dados até `t-1` (sem look-ahead)
3. **Target**: retorno realizado do instrumento no mês `t`
4. **Fit**: cada um dos 4 modelos é treinado na janela
5. **Predict**: cada modelo gera `μ_i` (retorno esperado para o mês `t+1`)
6. **Ensemble**: combinação ponderada `μ_ensemble = Σ(w_i × μ_i)`

#### 4.2.3 Pesos do Ensemble (Adaptativos)

Os pesos do ensemble são proporcionais à **correlação OOS ponderada exponencialmente** (halflife = 24 meses) de cada modelo:

```python
w_model = exp_weighted_corr(predictions_oos, realized_returns, halflife=24)
w_normalized = w_model / sum(w_models)  # normalizado para somar 1
```

Isso significa que modelos com melhor performance recente recebem mais peso. O sistema rastreia `w_ridge`, `w_gbm`, `w_rf`, `w_xgb` ao longo do tempo.

#### 4.2.4 Hyperparameter Tuning (Purged K-Fold CV)

A cada **12 meses**, o sistema executa purged k-fold cross-validation para selecionar hiperparâmetros ótimos por instrumento. O "purge" garante que não há vazamento temporal entre folds de treinamento e teste.

### 4.3 Score Composto e Demeaning

O **score total** é a soma dos `μ` de todos os instrumentos. Para evitar viés direcional persistente, o score é normalizado via **z-score rolling de 60 meses**:

```
score_demeaned = (score_raw - mean_60m) / max(std_60m, 0.5)
```

O `std` mínimo de 0.5 previne instabilidade quando a variância histórica é muito baixa. O scale factor é clipado em `[-3.0, 3.0]` para evitar amplificação extrema.

A **direção** do modelo é determinada pelo score demeaned:
- `score > +0.5` → **LONG BRL** (short USD)
- `score < -0.5` → **SHORT BRL** (long USD)
- `-0.5 ≤ score ≤ +0.5` → **NEUTRAL**

---

## 5. Motor de Regime (HMM)

### 5.1 Arquitetura de Dois Níveis

O modelo de regime usa **dois HMMs independentes** que capturam dinâmicas distintas:

#### Nível 1: Regime Global (3 estados)

Observáveis:
- `d_dxy`: variação mensal do DXY
- `vix`: nível do VIX
- `d_ust10`: variação mensal do UST 10Y
- `hy_spread`: US High Yield spread
- `ret_comm`: retorno mensal de commodities (BCOM)
- `ret_ewz`: retorno mensal do EWZ

Estados:
- **Carry** (`P_carry`): baixa volatilidade, spreads apertados, commodities em alta
- **Risk-Off** (`P_riskoff`): VIX elevado, DXY forte, spreads alargando
- **Stress** (`P_stress`): VIX extremo, flight-to-quality, commodities em queda

#### Nível 2: Regime Doméstico (2 estados)

Observáveis:
- `d_cds`: variação mensal do CDS Brasil 5Y
- `fx_vol`: volatilidade realizada do FX (rolling 6m, anualizada)
- `d_debt`: variação 12m da dívida/PIB

Estados:
- **Domestic Calm** (`P_domestic_calm`): CDS estável, FX vol baixa, fiscal controlado
- **Domestic Stress** (`P_domestic_stress`): CDS subindo, FX vol alta, deterioração fiscal

### 5.2 Combinação dos Regimes

As probabilidades dos dois níveis são combinadas para gerar 5 probabilidades finais:

```
P_carry, P_riskoff, P_stress (global)
P_domestic_calm, P_domestic_stress (doméstico)
```

O **regime dominante** é determinado pelo estado global com maior probabilidade. A combinação global × doméstico afeta os scaling factors aplicados ao μ de cada instrumento (Seção 6).

### 5.3 Refit do HMM

O HMM é refitado a cada **12 meses** durante o backtest, usando **janela expandente** (não rolling). Isso garante que o modelo de regime tem acesso a toda a história disponível para estimar as matrizes de transição, enquanto os alpha models usam janela rolling de 36m.

A separação é intencional: regimes são fenômenos de longo prazo (carry vs. stress), enquanto os sinais de alpha são de curto/médio prazo.

---

## 6. Otimizador de Portfólio

### 6.1 Formulação

O otimizador resolve o seguinte problema de maximização:

```
max  μ'·p·budget - 0.5·γ·p'Σp - TC(p, p_prev) - turnover_penalty
s.t. p'Σp ≤ σ²_target
     -w_max_i ≤ p_i ≤ w_max_i  (regime-conditional)
```

Onde:
- `μ`: vetor de retornos esperados (regime-adjusted)
- `p`: vetor de pesos
- `Σ`: matriz de covariância (Ledoit-Wolf shrinkage, 36m rolling)
- `γ = 2.0`: coeficiente de aversão ao risco
- `budget`: scaling por IC (Information Coefficient) rolling
- `TC`: custos de transação regime-dependentes
- `σ_target = 10% a.a.`: vol target do overlay

O solver utilizado é **SLSQP** (Sequential Least Squares Programming) do scipy.

### 6.2 Custos de Transação

Os custos de transação são definidos por instrumento e multiplicados por um fator regime-dependente:

| Instrumento | TC Base (bps) | × Carry | × Risk-Off | × Stress |
|---|---|---|---|---|
| FX | 5 | 1.0× | 1.5× | 2.5× |
| Front-End | 2 | 1.0× | 1.5× | 2.5× |
| Belly | 3 | 1.0× | 1.5× | 2.5× |
| Long-End | 4 | 1.0× | 1.5× | 2.5× |
| Hard Currency | 5 | 1.0× | 1.5× | 2.5× |

O multiplicador de turnover adicional é de **2 bps** sobre o turnover total.

### 6.3 Limites de Posição (Regime-Conditional)

| Instrumento | Carry | Risk-Off | Stress |
|---|---|---|---|
| FX | ±1.00 | ±0.80 | ±0.50 |
| Front-End | ±1.50 | ±1.00 | ±0.50 |
| Belly | ±1.50 | ±0.75 | ±0.40 |
| Long-End | ±0.75 | ±0.40 | ±0.25 |
| Hard Currency | ±1.00 | ±0.60 | ±0.30 |

Os limites efetivos são uma **média ponderada** pelas probabilidades de regime: `limit_eff = P_carry × limit_carry + P_riskoff × limit_riskoff + P_stress × limit_stress`.

### 6.4 IC Gating e Dynamic Budgets

O sistema implementa **IC gating**: se o Information Coefficient rolling (36m) de um instrumento cai abaixo do threshold (default: 0.0), o μ desse instrumento é escalado para baixo. Instrumentos com IC positivo recebem budget proporcionalmente maior (até 1.5×).

### 6.5 Regime Adjustment do μ

Antes da otimização, os μ são escalados por fatores regime-dependentes de dois níveis:

**Global scaling:**

| Instrumento | Carry | Risk-Off | Stress |
|---|---|---|---|
| FX | 1.0 | 0.7 | 0.5 |
| Front-End | 1.0 | 0.5 | 0.3 |
| Belly | 1.0 | 0.4 | 0.3 |
| Long-End | 1.0 | 0.3 | 0.2 |
| Hard Currency | 1.0 | 0.3 | 0.2 |

**Domestic scaling:**

| Instrumento | Calm | Stress |
|---|---|---|
| FX | 1.0 | 0.95 |
| Front-End | 1.0 | 0.85 |
| Belly | 1.0 | 0.80 |
| Long-End | 1.0 | 0.70 |
| Hard Currency | 1.0 | 0.90 |

O scaling combinado é o **produto** dos dois: `μ_adj = μ_demeaned × global_scale × domestic_scale`.

---

## 7. Overlays de Risco

Após a otimização, três overlays de risco são aplicados sequencialmente aos pesos:

### 7.1 Drawdown Scaling

Escala linear contínua baseada no drawdown corrente do overlay:

| Drawdown | Scale Factor |
|---|---|
| 0% | 1.00 |
| -5% | 0.50 |
| -10% | 0.00 (mínimo efetivo: 0.10) |

A interpolação é linear entre os breakpoints. O floor de 0.10 garante que o sistema mantém uma posição mínima para permitir recuperação.

### 7.2 Vol Targeting

Se a volatilidade realizada (GARCH(1,1) anualizada) excede o target de 10% a.a., os pesos são escalados proporcionalmente:

```
vol_scale = min(1.0, vol_target / realized_vol)
```

O GARCH(1,1) é fitado nos últimos 60 meses de retornos do overlay, com fallback para vol realizada simples se o GARCH falhar. A vol é floored em 2% e capped em 50%.

### 7.3 Circuit Breaker

Um **circuit breaker** é ativado quando há stress simultâneo global E doméstico:

```
Se P_riskoff > 0.7 E P_domestic_stress > 0.7:
  belly, long → × 0.5
  hard → × 0.4
  front → × 0.7
```

Este é um mecanismo de proteção de último recurso, independente dos regime adjustments do μ.

---

## 8. Backtest Walk-Forward

### 8.1 Metodologia

O backtest segue uma metodologia **walk-forward estrita** sem look-ahead bias:

1. **Período**: agosto 2015 → presente (~127 meses OOS)
2. **Início**: após 36 meses de treinamento inicial (dados desde ~2012)
3. **Rebalanceamento**: mensal (último dia útil)
4. **HMM refit**: a cada 12 meses (janela expandente)
5. **Alpha model refit**: mensal (janela rolling 36m)
6. **HP tuning**: a cada 12 meses (purged k-fold CV)

### 8.2 Cálculo de Retornos por Instrumento

**FX (NDF 1M long USD):**
```
ret_fx = Δspot/spot - cupom_cambial/100/12
```
Positivo quando USD se valoriza (BRL deprecia) líquido do custo de carry.

**Front-End (Receptor DI 1Y):**
```
ret_front = -Δ(DI_1Y)/100 × duration_1Y + excess_carry + rolldown
excess_carry = (DI_1Y - SELIC) / 100 / 12
rolldown = slope(3M→1Y) × (9/12) / 12
```

**Belly (Receptor DI 5Y):**
```
ret_belly = -Δ(DI_5Y)/100 × 4.5 + excess_carry_5Y + rolldown_5Y
rolldown_5Y = slope(2Y→5Y) × (3/5) / 12
```

**Long-End (Receptor DI 10Y):**
```
ret_long = -Δ(DI_10Y)/100 × 7.5 + excess_carry_10Y + rolldown_10Y
rolldown_10Y = slope(5Y→10Y) × (5/10) / 12
```

**Hard Currency (Spread DV01):**
```
ret_hard = -Δ(EMBI_spread)/10000 × 5.0 + spread_carry
spread_carry = EMBI_spread / 10000 / 12
```

### 8.3 Métricas de Performance

O backtest calcula as seguintes métricas para o overlay e para o total (CDI + overlay):

| Métrica | Descrição |
|---|---|
| Total Return | Retorno acumulado (%) |
| Annualized Return | Retorno anualizado (CAGR) |
| Annualized Vol | Volatilidade anualizada (σ × √12) |
| Sharpe Ratio | Return / Vol |
| Max Drawdown | Pior pico-a-vale (%) |
| Calmar Ratio | Return / |Max DD| |
| Win Rate | % de meses com retorno positivo |
| IC per Instrument | Information Coefficient rolling (corr pred vs realized) |
| Hit Rate per Instrument | % de meses com sinal correto |
| Attribution per Instrument | Contribuição de cada instrumento ao retorno total |
| Total TC | Custos de transação acumulados |
| Avg Monthly Turnover | Turnover médio mensal |

### 8.4 Benchmark

O sistema inclui o **Ibovespa** como benchmark de referência, calculando as mesmas métricas para comparação. O benchmark primário implícito é o **CDI** (já que o overlay é excess return sobre CDI).

---

## 9. Stress Tests

### 9.1 Cenários Históricos

O `StressTestEngine` avalia a performance do modelo durante 6 episódios de stress históricos:

| Cenário | Período | Categoria | Descrição |
|---|---|---|---|
| **Taper Tantrum** | Mai-Set 2013 | Global | Fed sinaliza tapering do QE. EM selloff, BRL -15%, DI +300bps |
| **Crise Dilma** | Jan-Dez 2015 | Doméstico | Deterioração fiscal, downgrade, crise política. BRL -33%, DI +400bps |
| **Joesley Day** | Mai-Jul 2017 | Doméstico | Gravações de Temer. BRL -8% intraday, circuit breaker |
| **COVID-19** | Fev-Mai 2020 | Global | Pandemia. BRL -25%, VIX 82, EMBI +300bps |
| **Fed Hiking** | Jan-Out 2022 | Global | Aperto agressivo do Fed. DXY +15%, UST 10Y +250bps |
| **Fiscal Lula** | Abr-Ago 2024 | Doméstico | Preocupações fiscais, BRL fraco, DI repricing |

### 9.2 Métricas por Cenário

Para cada cenário, o sistema calcula:
- Retorno do overlay durante o período
- Retorno total (CDI + overlay)
- Max drawdown durante o cenário
- Pesos médios por instrumento
- Regime dominante durante o período

---

## 10. SHAP e Interpretabilidade

### 10.1 SHAP Feature Importance

O sistema usa **TreeSHAP** (via XGBoost) para calcular a importância de cada feature por instrumento. O SHAP é computado de duas formas:

1. **Global importance** (`mean_abs`): média do valor absoluto dos SHAP values sobre toda a janela de treinamento. Indica a importância geral da feature.
2. **Current importance** (`current`): SHAP value para a observação mais recente. Indica a contribuição da feature para a previsão atual.

### 10.2 SHAP Temporal (Snapshots)

A cada **6 meses** durante o backtest, o sistema salva um snapshot do SHAP por instrumento. Isso permite rastrear mudanças estruturais nos drivers do modelo ao longo do tempo (e.g., se `Z_fiscal` ganhou importância relativa após 2024).

### 10.3 Alertas de SHAP Shift

O `alertEngine.ts` monitora mudanças na importância relativa das features entre runs:
- **Threshold de cruzamento**: alerta quando uma feature cruza 20% de importância relativa
- **Shift absoluto**: alerta quando uma feature muda mais de 15pp em importância relativa
- **Mínimo absoluto**: só alerta se a feature tem pelo menos 5% de importância

---

## 11. Sistema de Alertas e Notificações

### 11.1 Tipos de Alertas

O `alertEngine.ts` gera alertas automaticamente após cada model run:

| Tipo | Severidade | Trigger | Exemplo |
|---|---|---|---|
| `regime_change` | info/warning/critical | Mudança de regime dominante | "Carry → Risk-Off" |
| `regime_change` | warning | Surge de probabilidade de stress (>15pp) | "Stress +18pp sem mudança de regime" |
| `shap_shift` | warning | Feature cruza 20% importância relativa | "Z_fiscal crossed 20% (Long-End)" |
| `score_change` | info/warning | Score muda >2 pontos ou inverte direção | "Score: +3.2 → -1.5 (Direction Reversal)" |
| `drawdown_warning` | warning/critical | Max DD excede -10% | "Drawdown: -12.3%" |

### 11.2 Push Notifications

O sistema envia notificações push ao owner via `notifyOwner()` para:

1. **Regime changes** (severity > info)
2. **Drawdown > -5%** (threshold mais baixo que o alerta formal de -10%)
3. **Score direction reversals** (LONG → SHORT ou vice-versa)
4. **SHAP feature importance surges** (warning level)
5. **Model run summary** (sempre, após cada run): spot, score, regime, Sharpe, DD, contagem de alertas

### 11.3 Changelog

O `alertEngine.ts` também gera uma entrada de changelog após cada run, registrando:
- Versão, data, score, regime, probabilidades
- Métricas de backtest (Sharpe, return, max DD, win rate)
- Pesos por instrumento
- Lista de mudanças significativas (regime, score, posições)

---

## 12. Banco de Dados

### 12.1 Schema (5 Tabelas)

#### `users`
Tabela de usuários autenticados via Manus OAuth.

| Coluna | Tipo | Descrição |
|---|---|---|
| id | INT (PK, auto) | ID interno |
| openId | VARCHAR(255) | ID único do OAuth |
| name | VARCHAR(100) | Nome do usuário |
| email | VARCHAR(255) | Email |
| avatarUrl | TEXT | URL do avatar |
| role | ENUM('admin', 'user') | Papel (default: 'user') |
| createdAt, updatedAt | TIMESTAMP | Timestamps |

#### `model_runs`
Armazena cada execução do modelo com todos os JSONs de resultado.

| Coluna | Tipo | Descrição |
|---|---|---|
| id | INT (PK, auto) | ID da run |
| status | ENUM('running', 'completed', 'failed') | Status da execução |
| runDate | VARCHAR(10) | Data da run (YYYY-MM-DD) |
| dashboardJson | JSON | Dashboard completo (posições, regime, fair values, state vars) |
| backtestJson | JSON | Backtest (timeseries + summary) |
| shapJson | JSON | SHAP importance por instrumento |
| shapHistoryJson | JSON | SHAP snapshots temporais |
| timeseriesJson | JSON | Séries temporais para charts |
| errorMessage | TEXT | Mensagem de erro (se failed) |
| executionTimeMs | INT | Tempo de execução em ms |
| createdAt | TIMESTAMP | Timestamp de criação |

#### `model_alerts`
Alertas gerados automaticamente pelo alertEngine.

| Coluna | Tipo | Descrição |
|---|---|---|
| id | INT (PK, auto) | ID do alerta |
| modelRunId | INT (FK) | Run que gerou o alerta |
| alertType | ENUM('regime_change', 'shap_shift', 'score_change', 'drawdown_warning') | Tipo |
| severity | ENUM('info', 'warning', 'critical') | Severidade |
| title | VARCHAR(255) | Título curto |
| message | TEXT | Mensagem detalhada |
| previousValue, currentValue | VARCHAR(100) | Valores antes/depois |
| threshold | DECIMAL(10,4) | Threshold que foi violado |
| instrument, feature | VARCHAR(50) | Instrumento/feature relacionados |
| detailsJson | JSON | Detalhes adicionais |
| isRead | BOOLEAN | Lido pelo usuário |
| isDismissed | BOOLEAN | Dispensado pelo usuário |
| createdAt | TIMESTAMP | Timestamp |

#### `model_changelog`
Histórico de versões com métricas comparativas.

| Coluna | Tipo | Descrição |
|---|---|---|
| id | INT (PK, auto) | ID |
| modelRunId | INT (FK) | Run associada |
| version | VARCHAR(20) | Versão do modelo |
| runDate | VARCHAR(10) | Data da run |
| score | DECIMAL(10,4) | Score composto |
| regime | VARCHAR(50) | Regime dominante |
| regimeCarryProb, regimeRiskoffProb, regimeStressProb | DECIMAL(10,4) | Probabilidades |
| backtestSharpe, backtestReturn, backtestMaxDD, backtestWinRate | DECIMAL(10,4) | Métricas de backtest |
| backtestMonths | INT | Meses de backtest |
| weightFx, weightFront, weightBelly, weightLong, weightHard | DECIMAL(10,4) | Pesos por instrumento |
| trainingWindow | INT | Janela de treinamento (meses) |
| nStressScenarios | INT | Número de cenários de stress |
| changesJson | JSON | Lista de mudanças |
| metricsJson | JSON | Métricas detalhadas |
| createdAt | TIMESTAMP | Timestamp |

### 12.2 Endpoints tRPC

| Endpoint | Tipo | Autenticação | Descrição |
|---|---|---|---|
| `model.latestRun` | Query (public) | Não | Retorna a run mais recente com todos os JSONs |
| `model.run` | Mutation (protected) | Sim | Trigger manual de uma nova execução do modelo |
| `alerts.list` | Query (public) | Não | Lista alertas não dispensados |
| `alerts.unreadCount` | Query (public) | Não | Contagem de alertas não lidos |
| `alerts.markRead` | Mutation (protected) | Sim | Marca alerta como lido |
| `alerts.dismiss` | Mutation (protected) | Sim | Dispensa alerta |
| `alerts.dismissAll` | Mutation (protected) | Sim | Dispensa todos os alertas |
| `changelog.list` | Query (public) | Não | Lista changelog (últimas 50 entradas) |

---

## 13. Frontend e Dashboard

### 13.1 Hierarquia Visual

O dashboard segue uma hierarquia institucional "Command Center":

```
┌─────────────────────────────────────────────────────────┐
│ STATUS BAR: Spot | Score | Regime | Direction | Updated │
├─────────────────────────────────────────────────────────┤
│ ALERTS: Regime changes, SHAP shifts, drawdown warnings  │
├─────────────────────────────────────────────────────────┤
│ OVERVIEW GRID: 5 cards (FX | Front | Belly | Long | HC) │
│   Cada card: direction, E[r], fair value, Sharpe, Vol,  │
│   weight, risk unit. Borda colorida por sinal do Sharpe │
├─────────────────────────────────────────────────────────┤
│ CHARTS: 6 tabs (Score | Regime | Z-Scores | Fatores     │
│   Cíclicos | Pesos | Mu E[r])                          │
├─────────────────────────────────────────────────────────┤
│ BACKTEST: Equity curve, attribution, métricas           │
│   Badge: "Training: 36m rolling" | "5 instrumentos"    │
├─────────────────────────────────────────────────────────┤
│ SHAP: Feature importance (barras horizontais)           │
├─────────────────────────────────────────────────────────┤
│ SHAP HISTORY: Evolução temporal (heatmap/line)          │
├─────────────────────────────────────────────────────────┤
│ STRESS TESTS: 6 cenários históricos                     │
├─────────────────────────────────────────────────────────┤
│ ACTION PANEL: Expected return, sizing, risk metrics     │
├─────────────────────────────────────────────────────────┤
│ CHANGELOG: Versões com deltas (Sharpe, DD, weights)     │
├─────────────────────────────────────────────────────────┤
│ MODEL DETAILS: Regressão stats, ensemble weights        │
└─────────────────────────────────────────────────────────┘
```

### 13.2 Componentes Principais

| Componente | Arquivo | Função |
|---|---|---|
| **StatusBar** | `StatusBar.tsx` | Barra superior com spot USDBRL, score composto, regime dominante, direção, timestamp |
| **ModelAlertsPanel** | `ModelAlertsPanel.tsx` | Lista de alertas com badges de severidade, expandível, ações de dismiss/mark read |
| **OverviewGrid** | `OverviewGrid.tsx` | 5 cards de instrumentos com métricas-chave. Borda cyan (Sharpe+), rose (Sharpe-), amber (zero) |
| **ChartsSection** | `ChartsSection.tsx` | 6 tabs de séries históricas: Score Composto, Probabilidades de Regime, Z-Scores, Fatores Cíclicos, Pesos (5 instrumentos), Mu/E[r] (5 instrumentos). Filtros: 5Y, 10Y, ALL |
| **BacktestPanel** | `BacktestPanel.tsx` | Equity curve (overlay vs CDI vs Ibovespa), attribution por instrumento, tabela de métricas, badges de training window |
| **ShapPanel** | `ShapPanel.tsx` | Barras horizontais de SHAP importance por instrumento, com current vs mean_abs |
| **ShapHistoryPanel** | `ShapHistoryPanel.tsx` | Evolução temporal do SHAP (snapshots a cada 6 meses) |
| **StressTestPanel** | `StressTestPanel.tsx` | Cards de cenários de stress com retorno, DD, e descrição |
| **ActionPanel** | `ActionPanel.tsx` | Expected return 3m/6m, sizing recomendado, métricas de risco |
| **ModelChangelogPanel** | `ModelChangelogPanel.tsx` | Tabela de versões com deltas (Sharpe, return, DD, win rate, pesos) |
| **ModelDetails** | `ModelDetails.tsx` | Detalhes de regressão, ensemble weights, state variables |

### 13.3 Design System

- **Tema**: Dark mode (slate/zinc background)
- **Cores de regime**: Carry = emerald, Risk-Off = amber, Stress = rose
- **Cores de instrumento**: FX = cyan, Front = blue, Belly = violet, Long = amber, Hard = rose
- **Tipografia**: Monospace para valores numéricos, sans-serif para labels
- **Cards**: Borda superior colorida por sinal do Sharpe

---

## 14. Procedimentos Operacionais

### 14.1 Execução Manual do Modelo

Para executar o modelo manualmente:

1. Acessar o dashboard autenticado
2. Clicar no botão "Run Model" (requer autenticação)
3. O sistema executa sequencialmente:
   - `data_collector.py` (coleta de dados, ~2-5 min)
   - `macro_risk_os_v2.py` (modelo + backtest, ~10-20 min)
   - Persistência no banco de dados
   - Geração de alertas e notificações
4. O dashboard atualiza automaticamente ao concluir

Alternativamente, via API:
```bash
curl -X POST http://localhost:3000/api/trpc/model.run \
  -H "Content-Type: application/json" \
  -H "Cookie: session=<token>"
```

### 14.2 Monitoramento

**Indicadores de saúde do sistema:**
- Status da última run (completed/failed) e tempo de execução
- Cobertura de dados (séries com dados recentes vs. stale)
- Alertas não lidos (badge no painel)
- Notificações push (regime changes, drawdown warnings)

**Logs:**
- `devserver.log`: logs do servidor Node.js
- `stderr` do Python: logs detalhados do modelo (cada etapa logada)
- `browserConsole.log`: erros do frontend

### 14.3 Troubleshooting

| Problema | Causa Provável | Solução |
|---|---|---|
| Modelo falha com "Insufficient data" | Série temporal com gap ou fonte offline | Verificar `data/` CSVs, re-executar `data_collector.py` isoladamente |
| SHAP retorna vazio | XGBoost não convergiu (dados insuficientes) | Verificar se há pelo menos 36 meses de dados para o instrumento |
| Alertas não aparecem | Nenhuma mudança significativa entre runs | Normal — alertas só são gerados quando thresholds são violados |
| Score sempre ~0 | Score demeaning com histórico insuficiente | Precisa de pelo menos 12 meses de histórico para demeaning funcionar |
| Notificações não chegam | `notifyOwner()` falhou (serviço indisponível) | Non-fatal — verificar logs, notificações são best-effort |

### 14.4 Atualização de Dados

O `data_collector.py` deve ser executado periodicamente para manter os dados atualizados. A frequência recomendada é **diária** (para dados de mercado) ou **semanal** (para dados macro com lag).

Fontes com lag conhecido:
- **REER (BIS)**: ~2 meses de lag. Forward-fill automático.
- **PPP (World Bank)**: anual. Interpolação linear + forward-fill.
- **Dívida/PIB (BCB)**: ~2 meses de lag.
- **IPCA (BCB)**: ~15 dias de lag.

---

## 15. Parâmetros de Configuração

### 15.1 DEFAULT_CONFIG

| Parâmetro | Valor | Descrição |
|---|---|---|
| `training_window_months` | 36 | Janela de treinamento dos alpha models |
| `ridge_lambda` | 10.0 | Regularização L2 do Ridge |
| `gamma` | 2.0 | Aversão ao risco no otimizador |
| `overlay_vol_target_annual` | 0.10 (10%) | Vol target anualizada do overlay |
| `score_demeaning_window` | 60 | Janela rolling para z-score do score composto |
| `ic_gating_threshold` | 0.0 | IC mínimo para manter posição |
| `ic_gating_min_obs` | 24 | Observações mínimas antes de ativar IC gating |
| `cov_window_months` | 36 | Janela da matriz de covariância |
| `cov_shrinkage` | true | Usar Ledoit-Wolf shrinkage |
| `regime_refit_interval` | 12 | Refit do HMM a cada N meses |
| `turnover_penalty_bps` | 2 | Penalidade de turnover (bps) |
| `fx_cyclical_beta` | 0.05 | Beta do sinal cíclico no FX fair value |
| `fx_fv_weights` | {"beer": 1.0} | Peso dos modelos de fair value (BEER only) |

### 15.2 Drawdown Overlay

| Parâmetro | Valor |
|---|---|
| `dd_5` | -5% |
| `dd_10` | -10% |
| `scale_at_dd_5` | 0.50 |
| `scale_at_dd_10` | 0.00 (efetivo: 0.10) |

### 15.3 Position Limits (Base)

| Instrumento | Max Weight |
|---|---|
| FX | ±1.00 |
| Front-End | ±1.50 |
| Belly | ±1.50 |
| Long-End | ±0.75 |
| Hard Currency | ±1.00 |

---

## 16. Glossário

| Termo | Definição |
|---|---|
| **Alpha** | Retorno excedente sobre o benchmark (CDI) |
| **BEER** | Behavioral Equilibrium Exchange Rate — modelo de câmbio de equilíbrio |
| **CDI** | Certificado de Depósito Interbancário — taxa de referência brasileira |
| **CIP** | Covered Interest Parity — paridade coberta de juros |
| **DD** | Drawdown — queda do pico ao vale |
| **DI** | Depósito Interfinanceiro — taxa de juros futuros brasileira |
| **EMBI+** | Emerging Markets Bond Index Plus — spread soberano |
| **FEER** | Fundamental Equilibrium Exchange Rate |
| **GARCH** | Generalized Autoregressive Conditional Heteroskedasticity |
| **HMM** | Hidden Markov Model — modelo de regime |
| **IC** | Information Coefficient — correlação entre previsão e realizado |
| **Ledoit-Wolf** | Método de shrinkage para estimação de matriz de covariância |
| **NDF** | Non-Deliverable Forward — contrato a termo de câmbio |
| **OOS** | Out-of-Sample — fora da amostra de treinamento |
| **Overlay** | Retorno excedente sobre CDI (alpha puro) |
| **PPP** | Purchasing Power Parity — paridade do poder de compra |
| **PTAX** | Taxa de câmbio oficial do BCB |
| **REER** | Real Effective Exchange Rate — câmbio real efetivo |
| **SHAP** | SHapley Additive exPlanations — método de interpretabilidade |
| **SLSQP** | Sequential Least Squares Programming — solver de otimização |
| **Taylor Rule** | Regra de política monetária (Selic de equilíbrio) |
| **Walk-Forward** | Metodologia de backtest sem look-ahead bias |

---

## 17. Risk Limits & Governance

Esta seção documenta os limites de risco formais, processos de aprovação e framework de governança do Macro Risk OS. Todos os limites são codificados no `DEFAULT_CONFIG` e aplicados automaticamente pelo sistema. Qualquer alteração requer aprovação formal conforme o processo descrito abaixo.

### 17.1 Limites de Posição por Instrumento

Os limites de posição são expressos em unidades de peso normalizado (weight). Um weight de 1.0 corresponde a uma posição de risco unitário no instrumento (ex: USD 1M notional em FX, BRL 100/bp DV01 em rates). Os limites são simétricos (long e short) e variam por regime.

| Instrumento | Limite Base (Carry) | Limite Risk-Off | Limite Stress | Unidade de Risco |
|---|---|---|---|---|
| FX (USDBRL) | ±1.00 | ±0.80 | ±0.50 | USD notional via NDF 1M |
| Front-End (DI 1Y) | ±1.50 | ±1.00 | ±0.50 | DV01 em BRL (receiver swap) |
| Belly (DI 2-3Y) | ±1.50 | ±0.75 | ±0.40 | DV01 em BRL (receiver swap) |
| Long-End (DI 5Y) | ±0.75 | ±0.40 | ±0.25 | DV01 em BRL (receiver swap) |
| Hard Currency (Sov) | ±1.00 | ±0.60 | ±0.30 | Spread DV01 em USD |

A seleção do regime de limites é automática: o sistema usa as probabilidades do HMM para identificar o regime dominante e aplica os limites correspondentes. Quando P_riskoff > 50%, os limites de Risk-Off são ativados. Quando P_domestic_stress > 50%, os limites de Stress são ativados.

### 17.2 Limites de Exposição a Fatores

Além dos limites por instrumento, o otimizador impõe limites de exposição a fatores de risco sistêmico, calculados via beta rolling do portfólio contra cada fator.

| Fator | Limite (Beta Máximo) | Descrição |
|---|---|---|
| DXY (Dólar Global) | ±1.50 | Exposição ao dólar americano global |
| VIX (Volatilidade) | ±1.50 | Sensibilidade à volatilidade implícita |
| CDS Brasil 5Y | ±1.00 | Exposição ao risco soberano brasileiro |
| UST 10Y | ±1.00 | Sensibilidade à taxa longa americana |

Estes limites impedem que o portfólio acumule exposição direcional excessiva a fatores macro, mesmo quando os sinais de alpha apontam na mesma direção.

### 17.3 Drawdown Stop-Loss

O sistema implementa um mecanismo de drawdown scaling contínuo que reduz progressivamente o risco conforme o drawdown do overlay aumenta. Este mecanismo funciona como um stop-loss dinâmico, não binário.

| Nível de Drawdown | Fator de Escala | Efeito |
|---|---|---|
| 0% (sem drawdown) | 1.00 | Posições normais |
| -2.5% | 0.75 | Redução de 25% |
| -5.0% | 0.50 | Redução de 50% |
| -7.5% | 0.25 | Redução de 75% |
| -10.0% | 0.00 | **Posições zeradas** (circuit breaker) |

A interpolação entre os pontos é linear. O drawdown é calculado sobre o equity do overlay (excesso sobre CDI), usando um trailing peak com reset a cada 12 meses. Na prática, o `scale_at_dd_10` é implementado como 0.10 (não zero absoluto) para permitir reentrada gradual.

### 17.4 Circuit Breaker de Regime

Além do drawdown scaling, existe um circuit breaker de regime que é ativado quando há estresse simultâneo global e doméstico. Este é o último nível de defesa do sistema.

**Condição de ativação:** P_riskoff > 70% **E** P_domestic_stress > 70% simultaneamente.

| Instrumento | Corte no Circuit Breaker |
|---|---|
| Belly (DI 2-3Y) | 50% de redução |
| Long-End (DI 5Y) | 50% de redução |
| Hard Currency | 60% de redução |
| Front-End (DI 1Y) | 30% de redução |
| FX | Sem corte adicional (já limitado pelo regime) |

Este circuit breaker é aplicado **após** todos os outros overlays (drawdown, vol targeting, regime scaling) e representa um hard limit para cenários extremos.

### 17.5 Vol Targeting

O sistema mantém um target de volatilidade anualizada de **10%** para o overlay. Quando a volatilidade realizada (janela de 20 dias úteis) excede o target, as posições são proporcionalmente reduzidas.

A fórmula é: `vol_scale = min(1.0, vol_target / vol_realized_20d)`. Isto significa que o vol targeting nunca aumenta posições (scale ≤ 1.0), apenas reduz quando a vol realizada está acima do target.

### 17.6 Custos de Transação

Os custos de transação são modelados explicitamente no otimizador e variam por instrumento e regime. Custos mais altos em regimes de stress refletem o alargamento de bid-ask spreads observado empiricamente.

| Instrumento | Custo Base (bps) | Carry (×1.0) | Risk-Off (×1.5) | Stress (×2.5) | Dom. Stress (×2.0) |
|---|---|---|---|---|---|
| FX | 5 | 5 bps | 7.5 bps | 12.5 bps | 10 bps |
| Front-End | 2 | 2 bps | 3 bps | 5 bps | 4 bps |
| Belly | 3 | 3 bps | 4.5 bps | 7.5 bps | 6 bps |
| Long-End | 4 | 4 bps | 6 bps | 10 bps | 8 bps |
| Hard Currency | 5 | 5 bps | 7.5 bps | 12.5 bps | 10 bps |

Adicionalmente, uma penalidade de turnover de **2 bps** é aplicada sobre o turnover total do portfólio para desincentivar rebalanceamentos excessivos.

### 17.7 Processo de Aprovação para Mudanças de Parâmetros

Toda alteração nos parâmetros do modelo deve seguir o processo formal abaixo. O objetivo é garantir rastreabilidade, evitar regressões e manter a integridade do backtest.

**Nível 1 — Ajustes Operacionais (aprovação do operador):**
Alterações que não afetam a lógica do modelo, como atualização de fontes de dados, correção de bugs em data collection, ou ajuste de thresholds de alerta. Estas mudanças podem ser implementadas pelo operador do sistema e documentadas no changelog.

**Nível 2 — Ajustes de Parâmetros (aprovação do gestor de risco):**
Alterações em parâmetros do `DEFAULT_CONFIG` que afetam sizing, limites ou custos. Exemplos: mudança de `vol_target`, `position_limits`, `gamma`, `transaction_costs_bps`. Requer:
1. Documentação da justificativa (por que mudar)
2. Backtest comparativo (antes vs. depois) com métricas: Sharpe, max DD, turnover, IC
3. Aprovação formal do gestor de risco
4. Registro no changelog com versão incrementada

**Nível 3 — Mudanças Estruturais (aprovação do comitê):**
Alterações na arquitetura do modelo: novo instrumento, novo alpha model, mudança de regime model, alteração da função objetivo do otimizador. Requer:
1. Proposta técnica escrita com fundamentação teórica
2. Backtest completo OOS com walk-forward
3. Análise de robustez (sensibilidade a parâmetros)
4. Apresentação ao comitê de investimentos
5. Aprovação formal com ata registrada
6. Período de shadow trading (modelo roda em paralelo sem execução) de pelo menos 3 meses

### 17.8 Auditoria e Compliance

O sistema mantém trilha de auditoria completa através de:

1. **Model Changelog**: cada run é versionada com métricas comparativas, pesos, regime, e lista de mudanças. Armazenado na tabela `model_changelog`.
2. **Alertas**: todas as violações de threshold são registradas na tabela `model_alerts` com timestamp, severidade, e valores antes/depois.
3. **Notificações Push**: eventos críticos (regime change, drawdown > -5%) geram notificação imediata ao owner.
4. **SHAP Interpretability**: cada run produz decomposição SHAP por instrumento, permitindo explicar por que o modelo tomou cada decisão.
5. **Backtest Walk-Forward**: o backtest usa exatamente o mesmo código que a produção (single code path), eliminando discrepâncias entre backtest e live.

---

## 18. Runbook de Incidentes

Este runbook documenta procedimentos step-by-step para cenários de falha operacional. Cada incidente é classificado por severidade e inclui critérios de escalation.

### 18.1 Classificação de Severidade

| Severidade | Definição | Tempo de Resposta | Escalation |
|---|---|---|---|
| **P1 — Crítico** | Sistema inoperante ou posições incorretas em produção | Imediato (< 15 min) | Gestor de risco + CTO |
| **P2 — Alto** | Funcionalidade degradada, dados parcialmente incorretos | < 1 hora | Operador sênior |
| **P3 — Médio** | Componente não-crítico falhou, workaround disponível | < 4 horas | Operador |
| **P4 — Baixo** | Cosmético ou melhoria, sem impacto operacional | Próximo ciclo | Backlog |

### 18.2 Incidente: Fonte de Dados Offline

**Severidade:** P2 (Alto) — dados stale podem gerar sinais incorretos.

**Sintomas:**
- Model run falha com erro "Insufficient data" ou "Connection timeout"
- CSVs no diretório `data/` não atualizados (timestamp antigo)
- Dashboard mostra dados de data anterior

**Diagnóstico:**
1. Verificar qual fonte falhou: `python3 data_collector.py 2>&1 | grep ERROR`
2. Identificar a fonte específica nos logs (ANBIMA, FRED, BCB, Trading Economics, Yahoo Finance)
3. Testar conectividade: `curl -s https://api.anbima.com.br/feed/precos-indices/v1/titulos-publicos/mercado-secundario-TPF -H "Authorization: Bearer <token>"` (para ANBIMA)
4. Verificar se a API mudou (status code, formato de resposta)

**Resolução:**
1. **Se fonte temporariamente offline** (manutenção programada, timeout): aguardar e re-executar. O sistema usa forward-fill automático para séries com lag de até 5 dias úteis.
2. **Se fonte permanentemente alterada** (API deprecada, endpoint mudou): atualizar `data_collector.py` com novo endpoint ou fonte alternativa. Fontes de fallback:
   - DI Curve: ANBIMA (primária) → Trading Economics (fallback) → SELIC + spread construction (último recurso)
   - US Treasuries: FRED (primária) → Yahoo Finance (fallback)
   - CDS/EMBI: FRED EMBI (primária) → Trading Economics (fallback)
   - VIX: FRED (primária) → Yahoo Finance (fallback)
3. **Se múltiplas fontes offline** (evento sistêmico): manter posições inalteradas (não rebalancear). Notificar gestor de risco. Usar última run válida como referência.
4. Após resolução, re-executar `data_collector.py` e depois `model.run` via API.

**Escalation:** Se dados stale por mais de 2 dias úteis sem resolução → P1. Notificar gestor de risco para decisão sobre manter ou zerar posições.

### 18.3 Incidente: Modelo Divergente (Sinais Inconsistentes)

**Severidade:** P2 (Alto) — sinais incorretos podem gerar perdas.

**Sintomas:**
- Score composto muda drasticamente entre runs consecutivas (|Δscore| > 3 desvios-padrão)
- Pesos mudam de sinal em múltiplos instrumentos simultaneamente sem evento macro claro
- Sharpe do backtest cai abruptamente (> 0.3 pontos entre versões)
- SHAP mostra feature dominante inesperada (> 50% de importância em uma única feature)

**Diagnóstico:**
1. Verificar changelog: `curl -s http://localhost:3000/api/trpc/changelog.list` — comparar métricas entre últimas 2 runs
2. Verificar dados de entrada: abrir CSVs em `data/` e verificar se há saltos, NaNs, ou valores fora de escala
3. Verificar SHAP: se uma feature domina > 50%, pode indicar dado corrompido nessa feature
4. Verificar regime: mudança de regime legítima (ex: eleição, crise) vs. espúria (ruído no HMM)
5. Comparar mu por instrumento: `curl -s http://localhost:3000/api/trpc/model.latestRun` — verificar se mu_val está em escala razoável (|mu| < 5% mensal)

**Resolução:**
1. **Se causado por dado corrompido**: corrigir o CSV, re-executar data_collector, re-executar modelo. Documentar no changelog.
2. **Se causado por evento macro legítimo**: validar que o modelo está reagindo corretamente. Regime change é esperado em crises. Documentar a análise.
3. **Se causado por overfitting do ensemble**: verificar se GBM está dominando o ensemble (weight > 80%). Se sim, considerar aumentar `ridge_lambda` ou reduzir profundidade do GBM.
4. **Se causa não identificada**: reverter para última run válida. Manter posições da run anterior. Escalar para análise detalhada.

**Escalation:** Se sinais inconsistentes persistem por 2+ runs consecutivas → P1. Suspender rebalanceamento automático. Gestor de risco decide sobre posições.

### 18.4 Incidente: Drawdown Extremo (> -5% Overlay)

**Severidade:** P1 (Crítico) — perda material em andamento.

**Sintomas:**
- Alerta automático de drawdown disparado (notificação push)
- Dashboard mostra drawdown overlay > -5% no ActionPanel
- Drawdown scaling ativo (posições reduzidas automaticamente)

**Diagnóstico:**
1. Verificar drawdown atual: `curl -s http://localhost:3000/api/trpc/model.latestRun` — campo `overlay_metrics.max_drawdown`
2. Identificar instrumento(s) causador(es): verificar attribution no BacktestPanel
3. Verificar se drawdown scaling está funcionando: posições devem estar reduzidas proporcionalmente
4. Verificar se circuit breaker foi ativado (logs: "circuit breaker triggered")

**Ações Imediatas (< 15 minutos):**
1. Confirmar que o drawdown scaling está ativo e funcionando (posições reduzidas)
2. Verificar se o circuit breaker deveria ter sido ativado (P_riskoff > 70% E P_domestic_stress > 70%)
3. Notificar gestor de risco com: drawdown atual, instrumentos afetados, posições correntes, regime

**Ações de Follow-Up (< 1 hora):**
1. Analisar se o drawdown é causado por evento de mercado (legítimo) ou por erro do modelo
2. Se DD > -7.5%: considerar redução manual adicional além do scaling automático
3. Se DD > -10%: o sistema já terá zerado posições automaticamente. Avaliar se manter zerado ou re-entrar gradualmente.
4. Documentar o evento: data, causa, ações tomadas, resultado

**Critérios de Reentrada após DD > -10%:**
1. Drawdown deve ter recuado para acima de -5% (trailing peak reset)
2. Regime deve ter normalizado (P_carry > 50%)
3. Pelo menos 5 dias úteis desde o pico do drawdown
4. Aprovação do gestor de risco

**Escalation:** DD > -10% → Comitê de investimentos. DD > -15% → Revisão completa do modelo e possível suspensão.

### 18.5 Incidente: Falha na Execução Agendada

**Severidade:** P3 (Médio) — modelo não atualizou, mas posições anteriores permanecem válidas.

**Sintomas:**
- Dashboard mostra timestamp de última atualização > 24h
- Nenhuma notificação push de model run summary
- Logs do servidor mostram erro no cron job

**Diagnóstico:**
1. Verificar logs: `grep "ModelRunner" /home/ubuntu/brlusd-dashboard/.manus-logs/devserver.log | tail -20`
2. Verificar se o servidor está rodando: `curl -s http://localhost:3000/api/trpc/model.latestRun | jq .result.data.json.status`
3. Verificar se há processo Python travado: `ps aux | grep run_model | grep -v grep`

**Resolução:**
1. **Se processo travado**: `kill -9 <pid>` e re-executar via API
2. **Se servidor caiu**: reiniciar com `webdev_restart_server`
3. **Se erro de dependência** (pacote Python faltando): `pip3 install <pacote>` e re-executar
4. **Se erro de memória**: o modelo usa ~2GB RAM. Verificar se há processos concorrentes consumindo memória.

**Escalation:** Se falha persiste por 2+ dias → P2. Posições baseadas em dados stale podem divergir do mercado.

### 18.6 Incidente: Regime Change Inesperado

**Severidade:** P3 (Médio) — requer validação, mas sistema reage automaticamente.

**Sintomas:**
- Alerta de regime change no dashboard
- Notificação push: "Regime Change: carry → riskoff" (ou similar)
- Posições ajustadas automaticamente (limites de regime aplicados)

**Diagnóstico:**
1. Verificar probabilidades de regime: `curl -s http://localhost:3000/api/trpc/model.latestRun | jq .result.data.json.dashboardJson.regime_probabilities`
2. Verificar se há evento macro que justifique a mudança (notícias, dados econômicos)
3. Verificar observáveis do HMM: ΔDXY, VIX, ΔUST10, ΔCDS_BR, commodity returns
4. Comparar com regimes históricos similares no chart de Regime

**Resolução:**
1. **Se regime change legítimo** (evento macro claro): documentar e monitorar. O sistema já ajustou posições automaticamente.
2. **Se regime change espúrio** (sem evento macro): monitorar por 2-3 dias. HMM pode reverter. Se persistir sem fundamento, considerar refit do HMM com dados mais recentes.
3. **Se regime oscila** (flip-flop entre estados): pode indicar que o mercado está em transição. Considerar aumentar `regime_refit_interval` temporariamente.

**Escalation:** Regime change para stress com DD > -3% simultâneo → P2. Notificar gestor de risco.

### 18.7 Incidente: Banco de Dados Inacessível

**Severidade:** P1 (Crítico) — dashboard inoperante, model runs não podem ser salvos.

**Sintomas:**
- Dashboard mostra erro de carregamento
- API retorna erro 500 com "Connection refused" ou "ETIMEDOUT"
- Model run falha na etapa de persistência

**Diagnóstico:**
1. Verificar conectividade: `mysql -h <host> -u <user> -p<pass> -e "SELECT 1"`
2. Verificar se DATABASE_URL está correto no ambiente
3. Verificar se o banco TiDB está online (painel de controle do provedor)

**Resolução:**
1. **Se timeout temporário**: aguardar 5 minutos e re-tentar. TiDB pode ter reiniciado.
2. **Se credenciais expiradas**: atualizar DATABASE_URL via `webdev_request_secrets`
3. **Se banco corrompido**: restaurar do último backup. Contatar suporte do provedor.
4. **Workaround**: o modelo pode rodar e salvar output em `/tmp/model_output.json` mesmo sem banco. Importar manualmente quando o banco voltar.

**Escalation:** Banco offline por > 1 hora → Contatar suporte do provedor de banco de dados.

### 18.8 Matriz de Escalation

| Nível | Quem | Quando | Canal |
|---|---|---|---|
| **L1 — Operador** | Operador do sistema | Primeiro contato, P3/P4 | Dashboard + logs |
| **L2 — Operador Sênior** | Operador sênior / quant | P2 não resolvido em 1h | Notificação push + mensagem |
| **L3 — Gestor de Risco** | Head de risco | P1, DD > -5%, regime stress | Telefone + email |
| **L4 — Comitê** | Comitê de investimentos | DD > -10%, modelo suspenso | Reunião de emergência |

### 18.9 Checklist Pós-Incidente

Após a resolução de qualquer incidente P1 ou P2, o seguinte checklist deve ser completado:

1. Documentar o incidente: data/hora, sintomas, causa raiz, ações tomadas, resultado
2. Verificar se o modelo está operando normalmente: run completa, alertas funcionando, notificações ativas
3. Verificar se as posições estão corretas: comparar com expectativa baseada no score e regime
4. Atualizar o runbook se o incidente revelou cenário não coberto
5. Comunicar stakeholders sobre o incidente e resolução
6. Agendar revisão se o incidente revelou fragilidade sistêmica

---

*Documento gerado automaticamente pelo Macro Risk OS. Última atualização: Fevereiro 2026.*
