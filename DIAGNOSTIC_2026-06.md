# ARC Macro Risk OS — Diagnóstico Técnico-Estratégico

**Data:** 2026-06-19
**Autor:** Revisão de engenharia/quant (auditoria multi-agente, 39 agentes, verificação adversarial)
**Escopo:** Motor quant (Python ~13k LOC) + camadas de serviço TS (portfolio/risco/orquestração) + docs/CI.
**Método:** 7 dimensões auditadas em paralelo; cada achado de severidade alta/crítica foi re-verificado contra o código por um agente cético independente. Resultado bruto: `tasks/wiaumg3f8.output`.

> Nota de segurança (decisão do owner): as API keys hardcoded em código foram mantidas a pedido do owner. Ficam registradas aqui como dívida P0 (`data-layer/quant-7`, `portfolio/quant-3`), sem ação de rotação nesta rodada.

---

## 1. Resumo executivo

O ARC Macro Risk OS é um sistema **sério e ambicioso** de overlay macro Brasil sobre o CDI (FX USDBRL NDF + curva DI front/belly/long + soberano/EMBI + NTN-B), com ensemble Ridge+GBM walk-forward, HMM de regimes em dois níveis, taxa de equilíbrio r\* composta (5 modelos), otimizador mean-variance com shrinkage Ledoit-Wolf, overlays de risco e harness de backtest + stress. A arquitetura é coerente e a ambição é institucional.

**Porém, o conjunto de evidências aponta uma conclusão dura e acionável:**

> **O track record reportado não é confiável, e o "edge" real do overlay é marginal a inexistente na configuração atual.** A causa não é um bug isolado — é uma combinação de (a) look-ahead/leakage difuso que infla métricas de backtest, (b) um desalinhamento de alvo no modelo de alpha que destrói poder preditivo out-of-sample, e (c) ausência de infraestrutura de medição honesta (holdout, deflated Sharpe, testes, reprodutibilidade) que permitiria detectar isso.

Três fatos verificados sustentam essa conclusão:

1. **As métricas documentadas não batem com o output real.** Os relatórios v2.3 anunciam overlay Sharpe **1.42** / retorno **257%** / win rate **39%**; o único artefato que o motor produz (`output_final.json`, v4.3) mostra overlay Sharpe **0.49** / retorno **25.6%** / win rate **57%**. Nenhum número-manchete reconcilia. *(strategy-docs/quant-1 — verificado: crítico)*

2. **O "Total Sharpe 3.83" é o CDI, não a estratégia.** `total_ret = cash_r + overlay_ret`: o overlay rende 2.14% a/a sobre vol 4.38% (Sharpe 0.49); o "total" rende 12.05% sobre **a mesma vol** (Sharpe 2.75). O delta é apenas a perna de caixa CDI. O único componente de skill (overlay) tem Sharpe ~0.5. *(strategy-docs/quant-2 — verificado: alto)*

3. **O IC out-of-sample é ~0/negativo em 5 de 6 instrumentos.** IC live: fx −0.029, front −0.068, belly −0.011, long +0.064, hard −0.038, ntnb −0.002. Hit rates todos < 50% (FX 10.9%). O retorno positivo do overlay vem de **carry/beta** (hard +14.99% de atribuição, belly +7.18%), não dos sinais de ML. *(strategy-docs/quant-3 — verificado: crítico)*

E há o rastro histórico de overfitting: ICs já foram reportados em **0.74–0.76** (implausível em dado mensal sem leakage) e colapsaram para ~0; o Sharpe oscilou 0.39 → 0.73 → 1.61 → 1.94 → 1.42 → 3.92 ao longo de ~30 iterações de tuning re-pontuadas na **mesma** amostra de 129 meses. *(strategy-docs/quant-4 — verificado: alto)*

**Implicação estratégica:** corrigir os vieses de look-ahead vai provavelmente **piorar** o backtest atual antes de melhorá-lo — e isso é o caminho certo. A prioridade nº1 não é "achar mais alpha", é **construir a infraestrutura de medição honesta** para saber se há alpha. Só então faz sentido investir em risk engine e portfolio construction sobre uma base mensurável.

---

## 2. O que o sistema faz (mapa de módulos)

### Motor quant — `server/model/` (Python)

| Arquivo | LOC | Papel |
|---|---|---|
| `macro_risk_os_v2.py` | 4.402 | **Motor de produção.** 9 classes: DataLayer, FeatureEngine, AlphaModels, EnsembleAlphaModels, RegimeModel (HMM), Optimizer, RiskOverlays, ProductionEngine, BacktestHarness, StressTestEngine. |
| `data_collector.py` | 1.656 | Coleta ANBIMA/FRED/FMP/TE/BCB/IPEADATA; merge/proxy/fallback. |
| `feature_selection.py` | 1.199 | DualFeatureSelector (Elastic Net + Boruta + Stability Selection, bootstraps). |
| `composite_equilibrium.py` | 971 | r\* composto: Fiscal, Parity, Market-Implied, State-Space, Regime-switching. |
| `model_engine.py` | 993 | Motor auxiliar (regressão, regime, fair value). |
| `macro_risk_os.py` | 2.086 | **v1 legado** (deprecado, não executado). |
| `run_model.py` | 345 | Entry point do pipeline. |
| `run_fast_backtest.py` | 286 | Backtest rápido (usa API divergente do DataLayer — quebrado). |

### Camada de serviço — `server/` (TypeScript)

`portfolioEngine.ts` (P&L, VaR/stress, sizing) · `portfolioRouter.ts` (trade workflow, MTM) · `marketDataService.ts` (ANBIMA/BCB/Polygon) · `dataSourceHealth.ts` · `pipelineOrchestrator.ts` (orquestra coleta→modelo→persistência) · `modelRunner.ts` (executa Python, fallback S3) · `alertEngine.ts` · `db.ts`/`storage.ts` (Drizzle/MySQL).

### Demais
React 19 + tRPC dashboard (`client/`, fora de escopo desta rodada), 19 migrações Drizzle, GH Actions (CPU + GPU droplet DO), docs (SOP, planos, audit reports).

> **A verificar (owner não confirmou):** o guia descreve o prod (157.230.187.3) rodando **FastAPI + Dagster + Grafana** — nada disso existe neste repo (backend é Express/tRPC/Node). Tratado como arquitetura pretendida até confirmação.

---

## 3. Diagnóstico por tema (achados verificados)

### Tema A — A medição não é confiável (raiz de tudo)

| ID | Severidade | Achado |
|---|---|---|
| strategy/quant-1 | **Crítico** | Métricas dos relatórios ≠ output real (Sharpe 1.42 vs 0.49 etc.); "Run ID 90003" não existe em nenhum artefato. |
| strategy/quant-3 | **Crítico** | IC OOS ~0/negativo em 5/6 instrumentos; retorno vem de carry, não de sinal. |
| strategy/quant-2 | Alto | "Total Sharpe" é dominado pelo CDI; não mede skill. |
| strategy/quant-4 | Alto | Rastro de overfitting (IC 0.74→0; Sharpe 0.39→3.92 em tuning na mesma amostra). |
| tests-1 | **Crítico** | Testes TS de "quality gate" afirmam contra **literais hardcoded**, não contra output do modelo — passam mesmo se o modelo produzir lixo. |
| tests-2 | **Crítico** | Core quant Python tem **zero testes unitários**; os `test_*.py` são scripts de print; pytest nem é dependência. |

### Tema B — Look-ahead / leakage (infla o backtest)

| ID | Severidade | Achado |
|---|---|---|
| data-layer/quant-1 | **Crítico** | **Sem ajuste de vintage/publication-lag.** IPCA, dívida/PIB, Focus, contas nacionais são revisados e divulgados com defasagem; o sistema usa o valor carimbado no mês de referência (que não era conhecido então). É o leakage nº1 de sistemas macro. |
| backtest/quant-1 + data/quant-2 | **Crítico** | **Desalinhamento de alvo:** os alpha models são treinados em (feature_t, retorno_t) **contemporâneo** e depois usados para prever retorno_{t+1}. Isso assume persistência que não existe → IC OOS ~0. Não é leakage de PnL (a contabilidade está correta), é o alvo supervisionado errado. |
| feat-1 + eq-2 | Alto | **Winsorize com quantis de amostra cheia.** `_z_score_rolling` termina em `winsorize()` que usa `s.quantile(0.05/0.95)` sobre a série inteira (2000–2026, incluindo futuro). Todas as ~40 features Z\_ passam por aqui. |
| feat-2 + eq-1/eq-3 | Alto/Crítico | **Bloco de equilíbrio r\* reconstruído full-sample a cada step**, e `update_equilibrium_with_regime` aplica as probs de regime do step atual a **toda a história**, sobrescrevendo features históricas. |
| regime-1 | Crítico→Médio | **HMM usa probabilidades smoothed** (forward-backward, condicionadas ao futuro) em vez de filtered (causais). |
| regime-3 | Alto | Rótulo de estado HMM (state→regime) usa estatísticas full-sample e é instável entre refits. |
| regime-2 | Alto | Entre refits de 12m, as probs de regime ficam congeladas na última linha do último refit. |
| data/quant-3 | Alto | Reconstrução da curva DI **ancorada no valor de hoje** aplicada a toda a história. |
| data/quant-4 + backtest/quant-2 | Alto | PPP/GDPpc/CA/trade anuais **interpolados linearmente** entre âncoras → usa a âncora **futura**. |
| data/quant-5 | Alto | Fallbacks silenciosos de proxy constante para CDS e EMBI. |
| data/quant-6 | Médio | Dívida/PIB reescalada para âncora fixa de 77% (hoje). |

### Tema C — Risk engine, portfolio e paper-trading (frágil/incompleto)

| ID | Severidade | Achado |
|---|---|---|
| portfolio/quant-7 | Médio | **VaR/stress usam vols e correlações hardcoded**, não estimadas dos dados. |
| portfolio/quant-9 | Médio | **MTM das posições é um TODO no-op** — preço atual / P&L não-realizado nunca são gravados. |
| portfolio/quant-5 | Alto | `modelRunner` faz **fallback silencioso para output stale no S3** quando o modelo falha — recomendação live pode ser de um run antigo. |
| portfolio/quant-1/quant-2 | Alto | Acúmulo de CDI diário **hardcoded** (ternário morto 0.1375/0.1375); dois caminhos de P&L usam fontes de CDI inconsistentes. |
| portfolio/quant-10 | Médio | `tradeWorkflow.approve` marca trade como **executado no preço-alvo** imediatamente (sem fills reais/simulados). |
| portfolio/quant-12 | Médio | `extractMarketData` fabrica inputs de mercado com defaults literais silenciosos. |
| portfolio/quant-8 | Médio | `computeStressTests` usa DV01/spreadDV01 com sinal inconsistente. |
| — | — | **Não há kill-switch nem gate explícito de live-trading bloqueado por default** (requisito do owner). |

### Tema D — Reprodutibilidade / CI / ops

| ID | Severidade | Achado |
|---|---|---|
| ci-1 | Alto | **CI nunca roda os testes** — nem vitest nem Python em nenhum workflow. |
| repro-1 | Alto | Deps Python **não pinadas** (`>=`) → output não-reprodutível. |
| repro-2 | Médio | **Sem seed global de RNG**; bootstrap muta o RNG global do NumPy no meio do run. |
| repro-3 | Médio | Sem run ID / git SHA no output; identidade do run é só a data. |
| version-1 / strategy/quant-8 | Médio | **Drift de versão pervasivo**: SOP v3.10, reports v2.3, output v4.3, código v5.x; 5 vs 6 instrumentos; janela de backtest descrita errada (253 vs 129 meses). |
| tests-3 | Alto | `run_fast_backtest.py` e `test_equilibrium.py` chamam APIs divergentes do DataLayer — um caller está quebrado. |
| strategy/quant-9 | Médio | HMM frequentemente falha ("Insufficient data 0 months") por `dropna` global; regime live travado em P_carry 0.998 — não oferece proteção risk-off justamente nas caudas. |
| strategy/quant-10 | Baixo | Benchmark Ibovespa é tudo-zero no output, mas docs o tratam como populado (loader engole erro). |

### Tema E — Segurança (mantido por decisão do owner)
`data-layer/quant-7`, `portfolio/quant-3`: API keys (FRED/TE/FMP) e OAuth ANBIMA hardcoded como defaults em código versionado (`data_collector.py:28-35`, `marketDataService.ts:114-115`, `dataSourceHealth.ts:44-48`) e no `todo.md`. Registrado como dívida P0; sem ação nesta rodada.

---

## 4. Riscos

- **Quantitativo:** o sistema pode estar sendo operado/apresentado com um Sharpe 3–7× superior ao real. Decisões de sizing sobre "Sharpe 3.83" levam a sobre-alocação massiva num overlay de Sharpe ~0.5. O sinal de "Direction (BRL)" do dashboard pode apontar **invertido** (soma de mu de todos instrumentos contradiz a convenção de sinal do FX — `strategy/quant-6`, verificado).
- **Técnico:** corrigir leakage vai derrubar métricas; sem holdout e deflated Sharpe não há como distinguir "corrigi e perdi alpha falso" de "quebrei algo". Daí testes + reprodutibilidade serem pré-requisito.
- **Operacional:** fallback S3 stale + sem validação de freshness + HMM degenerado + benchmark zerado = recomendações live silenciosamente erradas, sem alerta. Sem runbook de rollback/quarentena nem gate de promoção (paper-trading) antes de um modelo virar "produção".

---

## 5. Top-10 melhorias por impacto/esforço

Ordenado por **impacto/esforço** (P = prioridade):

| P | Melhoria | Impacto | Esforço | Tema |
|---|---|---|---|---|
| 1 | **Fundação de medição honesta**: winsorize/z-score causais; holdout travado (últimos 24–36m); deflated Sharpe + PBO; reportar **só overlay** como métrica de skill | Altíssimo | M | A/B |
| 2 | **Reprodutibilidade**: pinar deps, seed global determinístico, run_id + git SHA + 1 string de versão no output | Alto | S | D |
| 3 | **Scaffold de testes do core Python** (pytest) com testes de *regressão de causalidade* (provam que transforms não enxergam o futuro) + smoke do pipeline | Alto | M | A/D |
| 4 | **Corrigir alinhamento de alvo** dos alpha models (treinar em retorno **forward** com purge/embargo correto) e re-medir IC OOS | Altíssimo | M | B |
| 5 | **Point-in-time / publication-lag** nas séries macro (shift por defasagem real de divulgação; interpolação só com âncora passada) | Altíssimo | M-L | B |
| 6 | **HMM causal**: probs filtered (não smoothed); rótulo de estado estável; fit por alinhamento per-série em vez de `dropna` global | Alto | M | B |
| 7 | **Risk engine de verdade**: vols/correlações estimadas (EWMA/Ledoit-Wolf), VaR/ES histórico+paramétrico, exposições (DV01, FX, bruto/líquido), **kill-switch** | Alto | L | C |
| 8 | **Paper-trading auditável** + **gate de live-trading bloqueado por default**: fills simulados, MTM real, audit trail, reconciliação; promoção de modelo exige N meses de paper | Alto | L | C |
| 9 | **Equilíbrio r\* causal**: computar uma vez como série rolling point-in-time; parar de reconstruir full-history a cada step | Alto | L | B |
| 10 | **Integridade de pipeline/ops**: falhar alto (não fallback stale silencioso); validar freshness; CI rodando testes; reconciliar docs↔código↔run via run_id | Médio-Alto | M | C/D |

---

## 6. Arquitetura-alvo (incremental, preserva o que é bom)

```
                ┌─────────────────────────────────────────────┐
                │  DATA LAYER (point-in-time / vintage-aware)  │
                │  ingest → validate → publication-lag shift   │
                │  → versioned snapshot (parquet, as-of)       │
                └───────────────┬─────────────────────────────┘
                                │ as-of(date) → strictly causal
                ┌───────────────▼─────────────────────────────┐
                │  FEATURE STORE (causal transforms, testados) │
                │  z/winsor rolling · carry · BEER · r* rolling │
                └───────────────┬─────────────────────────────┘
                ┌───────────────▼──────────┐   ┌───────────────┐
                │  REGIME (HMM filtered)    │   │ SIGNAL ENGINE │
                │  filtered probs, causal   │──▶│ alpha forward │
                └───────────────┬──────────┘   │ target +purge │
                                │              └───────┬───────┘
                ┌───────────────▼──────────────────────▼───────┐
                │  PORTFOLIO CONSTRUCTION (constraints, caps)    │
                │  risk budgeting · vol target · corr-aware     │
                └───────────────┬──────────────────────────────┘
                ┌───────────────▼──────────────────────────────┐
                │  RISK ENGINE  VaR/ES · DV01/FX/gross-net      │
                │  drawdown · kill-switch · scenario stress     │
                └───────────────┬──────────────────────────────┘
                ┌───────────────▼──────────────────────────────┐
                │  EVALUATION: walk-forward + LOCKED HOLDOUT     │
                │  deflated Sharpe · PBO · perf por regime       │
                └───────────────┬──────────────────────────────┘
                ┌───────────────▼──────────────────────────────┐
                │  PAPER TRADING (default) → audit trail → recon │
                │  LIVE = bloqueado, requer config explícita     │
                └───────────────────────────────────────────────┘
   Transversal: reprodutibilidade (seed, run_id, git SHA, deps pinadas),
   testes (pytest core + vitest serviços + CI), contratos de dados (pydantic).
```

Princípio: **uma única fronteira `as_of(date)`** que garante causalidade, e tudo a montante dela é point-in-time. Hoje a fronteira existe (`loc[:asof_date]`) mas é furada por transforms full-sample a jusante dela.

---

## 7. Plano da 1ª rodada (foco escolhido: backtest integrity · risk+paper · data layer)

Cada item é um commit pequeno, testável, sem risco para o fluxo de produção (não removo fallbacks que o prod depende sem coordenar env vars):

**Batch 1 — Fundação de medição (P1+P2+P3):**
1. `winsorize`/`_z_score_rolling` causais (rolling/expanding quantile) + teste de regressão de causalidade.
2. Seed global determinístico + `requirements.txt` pinado + `run_id`/git SHA/versão única no output.
3. `pytest` no repo + testes: causalidade de transforms, smoke do pipeline, asserção de que métricas do output == métricas reportadas.
4. Módulo de métricas: **deflated Sharpe** + PBO + relatório overlay-only; corrigir o "Direction" invertido.

**Batch 2 — Causalidade de dados/alvo (P4+P5+P6):**
5. Publication-lag/vintage nas séries macro; interpolação causal.
6. Alinhamento de alvo forward dos alpha models + purge/embargo; re-medir IC OOS.
7. HMM filtered + rótulo estável.

**Batch 3 — Risk + paper (P7+P8):**
8. Risk engine com vols estimadas, VaR/ES, exposições, kill-switch.
9. Paper-trading: MTM real, fills simulados, audit trail, gate de live bloqueado por default.

---

## 8. Roadmap 30 / 60 / 90 dias

**30 dias — Confiar no número.** Batches 1–2. Holdout travado, deflated Sharpe, testes+CI, vintage point-in-time, alvo forward. Entregável: um backtest reprodutível e honesto + veredito "há edge?".

**60 dias — Risco e execução-sombra.** Batch 3. Risk engine completo, paper-trading auditável com gate de live, portfolio construction com constraints/risk-budgeting, reconciliação. Entregável: pode-se operar em papel com trilha de auditoria.

**90 dias — Plataforma.** Feature store versionado (parquet as-of), contratos de dados (pydantic), arquitetura de agentes especializados (Macro/Regime/Signal/Risk/Portfolio/CIO) com outputs estruturados e auditáveis, observabilidade (o Grafana/Dagster do guia, se confirmado), expansão cross-asset além de Brasil. Entregável: plataforma de macro trading reprodutível, mensurável e auditável.

---

*Diagnóstico gerado a partir de auditoria multi-agente verificada. Achados completos com evidência linha-a-linha em `tasks/wiaumg3f8.output`.*
