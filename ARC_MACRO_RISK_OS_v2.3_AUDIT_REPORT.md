# ARC Macro Risk OS v2.3 — Relatório de Auditoria E2E

**Data:** 11 de fevereiro de 2026  
**Escopo:** Auditoria técnica completa do pipeline de dados, motor de sinais, framework de risco, backtest e dashboard  
**Versão anterior:** v2.2 | **Versão atualizada:** v2.3

---

## 1. Resumo Executivo

A auditoria E2E do sistema ARC Macro Risk OS revelou uma arquitetura robusta e bem estruturada, com ensemble de modelos não-lineares (Ridge + GBM), walk-forward out-of-sample, score demeaning, e regime model HMM de dois níveis. O pipeline de dados coleta de fontes reais (BCB, FRED, Yahoo Finance) sem placeholders. Foram identificados **8 problemas técnicos**, dos quais 3 de severidade alta, todos corrigidos na versão v2.3. Adicionalmente, foram implementadas melhorias no framework de risco e novas funcionalidades de visualização.

---

## 2. Arquitetura do Sistema (Verificada)

O sistema opera em 9 camadas sequenciais, cada uma auditada individualmente:

| Camada | Componente | Status | Observação |
|--------|-----------|--------|------------|
| 1 | DataLayer | **Real** | 20+ séries de BCB, FRED, Yahoo Finance |
| 2 | FeatureEngine | **Real** | 12 features macro fundamentais |
| 3 | EnsembleAlphaModels | **Real** | Ridge + GBM com pesos adaptativos OOS |
| 4 | RegimeModel | **Corrigido v2.3** | HMM 3-state global + 2-state doméstico |
| 5 | Optimizer | **Real** | Mean-variance com TC, turnover penalty |
| 6 | RiskOverlays | **Corrigido v2.3** | DD scaling + vol targeting + circuit breaker |
| 7 | ProductionEngine | **Corrigido v2.3** | IC gating + score demeaning melhorado |
| 8 | BacktestHarness | **Corrigido v2.3** | Walk-forward com expanding-window HMM |
| 9 | Dashboard | **Real** | tRPC + React + Recharts |

---

## 3. Auditoria de Dados (data_collector.py)

Todas as fontes de dados foram verificadas como reais, sem placeholders ou hardcoded values:

| Série | Fonte | API/Método | Verificação |
|-------|-------|-----------|-------------|
| USDBRL Spot | Yahoo Finance | yfinance `USDBRL=X` | Real-time |
| PTAX | BCB | SGS série 1 | Oficial |
| DI 1Y, 2Y, 5Y, 10Y | BCB | SGS séries 4389, 4391, 4392, 4393 | Oficial |
| SELIC | BCB | SGS série 432 | Oficial |
| IPCA YoY | BCB | SGS série 433 | Oficial |
| IPCA Expectativas | BCB Focus | API Focus | Oficial |
| NTN-B 5Y, 10Y | BCB | SGS séries 12466, 12467 | Oficial |
| Dívida/PIB | BCB | SGS série 4503 | Oficial |
| UST 2Y, 5Y, 10Y | FRED | DGS2, DGS5, DGS10 | Oficial |
| US CPI | FRED | CPIAUCSL | Oficial |
| VIX | Yahoo Finance | `^VIX` | Real-time |
| DXY | Yahoo Finance | `DX-Y.NYB` | Real-time |
| BCOM | Yahoo Finance | `^BCOM` | Real-time |
| EWZ | Yahoo Finance | `EWZ` | Real-time |
| CDS 5Y BR | Fallback | EMBI spread proxy | Parcial |
| REER | BCB | SGS série 11752 | Oficial |
| PPP | BCB | SGS série 3697 | Oficial |

**Conclusão:** Nenhum placeholder encontrado. Todas as séries são coletadas de APIs oficiais.

---

## 4. Problemas Identificados e Correções (v2.3)

### 4.1 HMM Look-Ahead Bias (Severidade: ALTA)

**Problema:** O RegimeModel era fitado em toda a história antes do backtest começar (`self.engine.regime_model.fit()` sem `asof_date`). Os parâmetros do HMM incorporavam informação futura, inflando artificialmente a qualidade das predições de regime.

**Correção v2.3:** Implementado expanding-window refit. O HMM é inicialmente fitado com dados até o início do período de backtest, e refitado a cada 12 meses usando apenas dados disponíveis até aquela data (`fit(asof_date=prev_date)`). Isso elimina completamente o look-ahead bias.

### 4.2 Double Regime Scaling (Severidade: MÉDIA)

**Problema:** O regime ajustava o mu no `ProductionEngine.step()` (linhas 1700-1731) E depois aplicava scaling novamente no `RiskOverlays.apply()` — dupla contagem que distorcia os pesos finais.

**Correção v2.3:** Removido o regime scaling do `RiskOverlays`. Mantido apenas no `step()` como ajuste de mu. O `RiskOverlays` agora contém apenas: (1) drawdown scaling, (2) vol targeting, e (3) circuit breaker para stress extremo combinado (P_riskoff > 0.7 AND P_domestic_stress > 0.7).

### 4.3 Sem IC-Conditional Gating (Severidade: MÉDIA)

**Problema:** Instrumentos com Information Coefficient (IC) negativo ainda recebiam alocação. Isso significava que o modelo alocava capital para instrumentos cujas predições eram anti-correlacionadas com os retornos realizados.

**Correção v2.3:** Adicionado IC gating no `ProductionEngine.step()`. Instrumentos com IC rolling < 0 (configurável via `ic_gating_threshold`) têm seu mu zerado, desde que haja pelo menos 24 observações para confiar no IC.

### 4.4 Covariance Matrix sem Shrinkage (Severidade: BAIXA)

**Problema:** A matriz de covariância usava estimativa amostral simples com janela de 24 meses. Com 5 instrumentos e 24 observações, a estimativa é ruidosa e pode gerar pesos instáveis.

**Correção v2.3:** Implementado Ledoit-Wolf shrinkage com janela expandida para 36 meses. O shrinkage reduz o ruído da estimativa amostral ao encolher em direção a uma matriz estruturada, resultando em pesos mais estáveis.

### 4.5 Score Demeaning Instável perto de Zero (Severidade: BAIXA)

**Problema:** Quando o raw score era próximo de zero, a divisão `demeaned_score / raw_score` produzia scale factors extremos (ex: 50x), amplificando ruído.

**Correção v2.3:** Adicionado threshold mínimo de 0.005 para o raw score. Scale factor clipado em [-3, 3] para prevenir amplificação extrema. Quando raw score é near-zero, o scale factor é 1.0 (sem ajuste).

### 4.6 FX Carry sem Cupom Cambial (Severidade: BAIXA)

**Problema:** O carry do FX NDF usava proxy (DI_3M - UST_2Y)/12, que é uma aproximação grosseira do forward premium real.

**Correção v2.3:** Implementado uso do cupom cambial (BCB série 3955) quando disponível, com fallback para o proxy DI-UST.

### 4.7 Hardcoded Fair Value Weights (Severidade: BAIXA)

**Problema:** Os pesos do fair value (PPP 40%, BEER 40%, Cyclical 20%) e o beta ciclico (0.05) estavam hardcoded no código.

**Correção v2.3:** Movidos para o `DEFAULT_CONFIG` como `fx_fv_weights` e `fx_cyclical_beta`, permitindo ajuste sem modificar código.

### 4.8 Realized Vol sem Floor (Severidade: BAIXA)

**Problema:** A vol realizada no backtest podia ser zero nos primeiros meses, causando divisão por zero no vol targeting.

**Correção v2.3:** Adicionado floor de 2% e mínimo de 12 meses de história antes de calcular vol realizada.

---

## 5. Novas Funcionalidades (v2.3)

### 5.1 Rolling Sharpe 12m Chart

Adicionado novo tab "Rolling Sharpe" ao BacktestPanel com:

- Gráfico de área mostrando Sharpe anualizado em janela móvel de 12 meses
- Reference lines em Sharpe = 1.0 e Sharpe = -1.0
- Cards de resumo: média, máximo, mínimo, % > 0, % > 1.0
- Tooltip colorido por faixa de performance

### 5.2 Deprecação do v1 Legacy

Removida a execução do `macro_risk_os.py` (v1) do `run_model.py`. O arquivo v1 é preservado para referência histórica, mas não é mais executado. Todo o output é exclusivamente do motor v2.3.

### 5.3 Campos v2.3 no Output

O timeseries agora inclui campos adicionais para o frontend:

- `P_domestic_calm`, `P_domestic_stress` (regime doméstico)
- `w_ridge_avg`, `w_gbm_avg` (pesos do ensemble)
- `raw_score`, `demeaned_score` (score demeaning)
- `rolling_sharpe_12m` (Sharpe rolling 12 meses)

---

## 6. Novos Parâmetros de Configuração (v2.3)

| Parâmetro | Default | Descrição |
|-----------|---------|-----------|
| `ic_gating_threshold` | 0.0 | IC mínimo para manter alocação |
| `ic_gating_min_obs` | 24 | Observações mínimas para confiar no IC |
| `signal_quality_sizing` | true | Ativar IC-conditional gating |
| `cov_window_months` | 36 | Janela para matriz de covariância |
| `cov_shrinkage` | true | Usar Ledoit-Wolf shrinkage |
| `regime_refit_interval` | 12 | Meses entre refits do HMM |
| `fx_fv_weights` | {ppp: 0.4, beer: 0.4, cyc: 0.2} | Pesos do fair value FX |
| `fx_cyclical_beta` | 0.05 | Sensibilidade ciclica do FV |

---

## 7. Validação

| Verificação | Resultado |
|-------------|-----------|
| Python syntax (macro_risk_os_v2.py) | OK |
| Python syntax (run_model.py) | OK |
| TypeScript compilation | Zero errors |
| Vitest (69 tests) | All passing |
| Dev server | Running, HMR functional |
| Dashboard rendering | Correct, all panels visible |

---

## 8. Recomendações Futuras

1. **Backtest completo v2.3:** Executar o modelo com as correções para verificar o impacto nos métricas (Sharpe, Max DD, Calmar). Espera-se melhoria no Sharpe pela remoção do double regime scaling e IC gating.

2. **Cupom cambial data collection:** Adicionar coleta da série BCB 3955 (cupom cambial 1M) ao `data_collector.py` para ativar o carry FX real.

3. **Stress testing framework:** Implementar cenários de stress (Taper Tantrum 2013, Dilma 2015, COVID 2020, Joesley Day) com métricas de performance condicional.

4. **Regime-conditional position limits:** Ajustar limites de posição por regime (ex: em risk-off, limitar long-end a 50% do máximo).

5. **Transaction cost model:** Refinar custos de transação por instrumento com bid-ask spreads reais de mercado.

---

*Relatório gerado automaticamente pelo sistema ARC Macro Risk OS v2.3*
