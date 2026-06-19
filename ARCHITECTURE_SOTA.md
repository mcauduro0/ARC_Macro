# ARC Macro 2.0 — Arquitetura de Estado da Arte (Blueprint Build-Ready)

**Data:** 2026-06-19
**Origem:** Síntese de auditoria verificada (39 agentes) + fan-out de design (8 architects + chief-architect/crítico).
**Documentos irmãos:** [DIAGNOSTIC_2026-06.md](DIAGNOSTIC_2026-06.md) (o porquê) · achados brutos em `tasks/wiaumg3f8.output` · design bruto em `tasks/w6tje5x8o.output`.

---

## 0. Escopo & decisões assumidas (confirmadas pelo owner)

| Dimensão | Decisão | Consequência no design |
|---|---|---|
| **Capital/operação** | **Book próprio / family office** | Sem cotistas → compliance CVM/GIPS/investor-reporting vira **opcional/plugável** (não bloqueia), mas **audit trail + model-risk + P&L-explain permanecem obrigatórios**. |
| **Frequência** | **Macro mensal/semanal + camada tática diária** | Backtester e cost model precisam suportar **diário**; dados diários limpos (DI/DOL/curva) com PIT; custos mais finos (half-spread + impacto). |
| **Autonomia** | **Autônomo até a ordem; humano aprova** | Agentes pesquisam, validam, montam portfólio e **geram ordens** de forma autônoma; **gate humano na aprovação de ordem** (paper e live). Holdout e live exigem aprovação humana explícita. |
| **Segurança** | Owner mantém keys atuais (sem rotação) | De-hardcode para env-injection (sem rotação) para destravar containerização; valores nunca em doc/commit novo. |

---

## 1. Os 5 invariantes (make-or-break)

A reconstrução vive ou morre nestes cinco pontos. Tudo o mais é detalhe de execução.

1. **Uma única fronteira causal `as_of(t)`**, implementação única em `arc-data`, consumida *identicamente* por backtest, geração de sinal live, marks de risco/MTM e preços de execução. Canário de CI: *offline/online parity* (snapshot noturno == `as_of(now)`) + *leakage canaries* (IC de label embaralhado ≈ 0; invariância a shift de `as_of`). Se isto for furado ou duplicado, **todo número a jusante volta a ser ficção**.

2. **Corrigir o alinhamento de alvo** (treinar em retorno **forward** com *triple-barrier* + *purge/embargo*) e re-medir o IC OOS honestamente. Este **bug estatístico**, não infra, é a razão do IC ~0 em 5/6 instrumentos. **Se, após correção, o IC deflacionado ainda for ~0, a resposta honesta é "este overlay não tem alpha de sinal"** — e a plataforma deve sobreviver a esse veredito (reduzir tamanho graciosamente, colher carry explicitamente), não ser tunada em volta dele.

3. **Governança global de multiple-testing**: um único `GovernanceLedger` contando **todos** os trials (de humanos **e** agentes) alimentando Deflated Sharpe / PBO, + um *holdout* de uso único com token humano. Sem isso, o loop autônomo de pesquisa **fabrica falsos positivos mais rápido que humanos** (a história 0.39→3.92, agora automatizada).

4. **Um único ponto físico de estrangulamento do live** (default=PAPER + config assinada + aprovação N-de-M atrelada ao hash da config + gate de freshness + kill-switch), com *probe* periódico que verifica que nenhum caminho de código o contorna. Uma má-configuração chegando ao mercado é falha irrecuperável.

5. **Disciplina de sequenciamento**: construir **honestidade de medição** (PIT + leakage tests + reprodutibilidade + holdout) **ANTES** de risk engine, portfolio, agentes ou live. O instinto de "achar mais alpha" deve ser **resistido** até a régua ser confiável.

---

## 2. Decisões de stack decisivas (contradições resolvidas pelo chief-architect)

Os architects divergiram; o integrador resolveu. **Estas são as escolhas canônicas — sem dual-maintenance:**

| Questão | Resolução canônica | Por quê |
|---|---|---|
| **Banco** | **PostgreSQL único** (+ TimescaleDB + pgvector). Migração MySQL→Postgres **uma vez**, na Fase 0. MLflow aponta para o **mesmo** Postgres. | Mata dual-DB; lineage único auditável. (`drizzle` suporta Postgres.) |
| **Orquestração** | **2 engines, fronteiras nítidas, 0 Prefect:** **Dagster** = grafo de *assets* de dados+modelo (lineage PIT); **Temporal** = workflows duráveis de agentes + HITL (aprovações, kill-switch). **LangGraph** = lib *in-process* dentro de activities Temporal, não runtime concorrente. | Dagster vence em lineage de assets; Temporal vence em durabilidade/signals; não competem. |
| **Pricing/DV01** | **UMA biblioteca de pricing, em Python** (`arc-quant/pricing`), **portada uma vez** de `portfolioEngine.ts` com *golden-master tests* bit-a-bit. TS BFF **para de calcular risco** e só renderiza números do Python. | Duas implementações de B3 divergem em sinal/accrual (o audit já achou DV01 com sinal inconsistente). |
| **Feature store** | **Um único `as_of()` em `arc-data`** (DuckDB ASOF join). Nenhum subsistema escreve seu próprio *vintage join*. Custom thin layer, **não Feast** (Feast não tem bitemporal/revisão nativos). | A *parity* offline/online só vale com **um** caminho de código. |
| **Holdout vs agentes** | Token de holdout é recurso **Temporal-gated, contra-assinado por humano**, que o agente **não pode auto-emitir**. Agentes operam só em CPCV/walk-forward. | Agente em loop sobre o holdout o destrói. |
| **Baseline de backtest** | *Golden-master* bug-for-bug é **só harness de migração** (caracterização). O *gate* de CI vira a baseline **corrigida** assim que um fix causal entra; *leakage canaries* viram o gate permanente. | Nunca deixar paridade bug-for-bug bloquear um fix de causalidade. |
| **Deps/env** | **uv** (lockfile hasheado) + seed global + Docker pinado por digest. | Reprodutibilidade bit-a-bit. |
| **Contratos** | **Um JSON Schema = fonte da verdade** → codegen Pydantic v2 (Python) + Zod (TS) + tipos Drizzle, validado em CI. | Mata o drift de shape Python/TS atrás do blob stdout-JSON. |

---

## 3. Arquitetura-alvo (monorepo north-star)

```
arc-macro/                         # monorepo (uv workspace + pnpm workspace, glued by justfile)
├─ packages/                       # PYTHON
│  ├─ arc-contracts/               # JSON Schema → Pydantic v2 (+ codegen Zod/Drizzle)
│  │   schemas: SeriesContract, StrategySpec, TargetPortfolio, RiskReport,
│  │            FillEvent, RunManifest, AgentArtifact
│  ├─ arc-repro/                   # reproducibility.init(): run_id, git SHA, seed, env/vintage/config hash
│  ├─ arc-data/                    # ★ A PLATAFORMA POINT-IN-TIME
│  │   ├─ adapters/                #   refatorados de data_collector.py (BCB SGS/Focus, ANBIMA, FRED/ALFRED, …)
│  │   ├─ store/                   #   raw_observation (append-only Parquet), series_catalog (+license +pub-lag)
│  │   ├─ asof.py                  #   ★ O ÚNICO as_of(t) (DuckDB ASOF) — usado por TODOS
│  │   ├─ contracts/               #   Pandera + Great Expectations
│  │   └─ feature_store/           #   feature_views causais (rolling winsor/z, BEER, r*-rolling)
│  ├─ arc-quant/                   # numerics puros, seeded, testados (sem I/O)
│  │   ├─ pricing/                 #   B3 DI1 PU / NTN-B / FX MTM + DV01/CS01/FX-delta (PORTADO 1x de TS)
│  │   ├─ regime/                  #   MS-Hamilton FILTRADO + BOCPD
│  │   ├─ nowcast/                 #   DFM (DynamicFactorMQ) + U-MIDAS
│  │   ├─ alpha/                   #   Bayesian hierárquico (PyMC) + LGBM monotônico + meta-labeling + factor lib
│  │   ├─ cost/                    #   ★ UM cost model (sqrt-impact + half-spread) compartilhado backtest+paper+TCA
│  │   ├─ risk/                    #   cov (LW+EWMA+DCC), GJR-GARCH, VaR/ES, Euler attr, stress/reverse
│  │   ├─ portfolio/               #   BL + cvxpy/Clarabel + HRP fallback + Kelly fracionado + alocador cross-strategy
│  │   └─ validation/              #   CPCV, purge/embargo, Deflated Sharpe, PBO, leakage canaries
│  ├─ arc-backtest/                # event-driven (cert) + vectorized (research), accounting/cost core comum; GovernanceLedger
│  ├─ arc-execution/               # OMS event-sourced hash-chained, order FSM, paper-fill sim, TCA, recon, live-gate choke
│  ├─ arc-funding/                 # ★ GAP-FILL: margin/colateral/funding CDI, escada de liquidez/capacity
│  ├─ arc-report/                  # ★ GAP-FILL: P&L-explain, attribution, factsheet (opcional p/ book próprio)
│  ├─ arc-agents/                  # Temporal + LangGraph; CIO/Research/Regime/Signal/Risk/Portfolio/Exec
│  │   ├─ tools/                   #   Tool Belt tipado (números por referência, nunca do LLM)
│  │   ├─ memory/                  #   pgvector + BM25, asof-filtered
│  │   └─ evals/                   #   LLM-as-judge + harness de invalidation conditions
│  └─ arc-engine/                  # FastAPI: runs async + SSE, artifact store tipado (substitui subprocess-stdout-JSON)
├─ orchestration/ dagster/ (assets dados+modelo)  temporal/ (agentes + HITL)
├─ mlops/                          # MLflow (Postgres), model_inventory, drift, champion/challenger, regression gate
├─ ts/ apps/web (React kept) · packages/bff (tRPC fino → arc-engine, SEM math) · db (Drizzle v2 Postgres)
├─ governance/ risk-policy.yaml · model-risk register · license registry · DR runbooks
├─ tests/ leakage-canaries · asof-invariance · golden-master · reconciliation · parity
└─ infra/ Terraform (DO droplets/Spaces/Postgres/GPU on-demand) · docker/ (slim-cpu + cuda, pinned)
```

---

## 4. Subsistemas (objetivo · componentes · stack · metodologia)

### 4.1 `arc-data` — Plataforma de dados bitemporal (PIT)
**Objetivo:** fonte única da verdade; toda série consultável "como era conhecida na data t" (publication lag + revisões + snapshots ANBIMA/Focus).
**Modelo:** linha imutável `(series_id, event_time, knowledge_time, value, source, vintage_id, ingest_run_id, source_url, source_hash)`. **Revisão = nova linha** (append-only), nunca update. `knowledge_time = max(publish_ts da fonte, event_time + lag contratado)`. Primitivo único `as_of(asof_ts)` = argmax(knowledge_time ≤ asof) por event_time (DuckDB ASOF JOIN).
**Stack:** Parquet imutável (object storage) + **DuckDB** (engine offline); **Postgres** (catálogo/online/contratos); **Pandera + Great Expectations** (schema/freshness/range/monotonicidade/magnitude-de-revisão). Ingestão orquestrada (Dagster).
**Brasil:** Focus via BCB Olinda (data de publicação = knowledge_time); IPCA/SGS com lag por série; ANBIMA ETTJ como vintages diários (T+1 ~19h BRT) — modelo consome o ETTJ conhecido naquela manhã, nunca o snapshot do mesmo dia. **Mata:** rescale full-sample de dívida/PIB, calibração full-sample de EMBI, DI curve ancorada em hoje, fallback stale silencioso.

### 4.2 `arc-backtest` + `arc-quant/validation` — Pesquisa, backtest & validação (a "régua honesta")
**Componentes:** BitemporalDataStore (replay PIT) · LabelEngine (triple-barrier + horizonte) · **CPCV/PurgedKFold+embargo** · CostModel (compartilhado) · **EventDrivenReplay** (certificação) + **VectorBacktester** (pesquisa, mesmo accounting/cost core) · **StatisticalValidator** (Deflated Sharpe, PBO, IC com HAC/Newey-West) · **GovernanceLedger** (contagem global de trials + tokens de holdout) · ExperimentTracker/RunManifest · NotebookToProduction (papermill, headless em CI).
**Invariante:** resultado vetorizado == event-driven dentro de tolerância (reconciliação). **Diário:** o event-driven replay e o cost model operam em frequência diária para a camada tática.

### 4.3 `arc-quant/{nowcast,regime,alpha}` — Sinal & alpha (o cérebro)
**Nowcast:** DFM mixed-frequency (`statsmodels DynamicFactorMQ`, Kalman **filtrado**) + U-MIDAS para crescimento/inflação/fiscal.
**Regime:** Markov-switching **filtrado** (`MarkovRegression`/Hamilton) + BOCPD (online change-point). Regime é **condicionamento causal**, nunca feature com look-ahead.
**Forecaster:** Bayesian hierárquico (PyMC, *partial pooling* por instrumento/regime) como primário robusto em amostra pequena; `BayesianRidge` como default rápido; **LightGBM com monotone_constraints** + regularização forte como secundário não-linear.
**Convicção:** **meta-labeling** dimensiona aposta; **SignalStacker** (OOF, shrink-to-equal-weight); **EconomicSanityGate** (sinal vs hipótese, SHAP) — toda feature com **hipótese econômica + sinal esperado + modo de falha** documentados. **Honestidade sobre DL:** provavelmente não vale em macro mensal de ~130–250 obs (overfitting); reservar para alta-frequência/alternativos futuros.

### 4.4 `arc-quant/{risk,portfolio}` — Risco & construção de portfólio
**Risk:** covariância **LW+EWMA+DCC** com reparo PSD (Higham); vols **GJR-GARCH** (`arch`); **VaR/ES** paramétrico + histórico full-reval + Monte-Carlo (cópula Student-t, seeded); **component VaR (Euler)**; FactorRiskDecomposer (DXY/UST/VIX/CDS/curva, DV01 ladder, CS01, FX-delta); **StressEngine** (choques Brasil + replays históricos PIT + reverse stress Mahalanobis); **KillSwitch** (FSM: drawdown/VaR/staleness/regime, histerese+cooldown).
**Portfolio:** **Black-Litterman** (prior risk-parity, Ω escalado por IC) + otimizador **cvxpy/Clarabel** com constraints convexas duras + **HRP/HERC** fallback + **Kelly fracionado**. `risk-policy.yaml` validado por Pydantic, regime-condicional, com hash em todo run.

### 4.5 `arc-execution` — Execução, paper trading & OMS
**Componentes:** EventStore **append-only hash-chained** (system of record) · OrderStateMachine · **PositionKeeper + MTM REAL** (DI1 PU reprice + accrual CDI, NTN-B IPCA/cupom, FX carry — substitui o no-op atual) · VenueAdapter · **PaperFillSimulator** (snapshot de arrival, latência lognormal, POV/partial fills, fees) · ExecutionAlgo (TWAP/POV) · **PreTradeRiskGate** · **TCAEngine** (implementation shortfall) · **ReconciliationEngine** (match 3-vias EOD, sign-off, cancel-only-até-reconciliar) · **TradingModeGate + KillSwitch** (default PAPER) · **PromotionPipeline** (gates de paper pré-registrados e congelados).
**Gate de autonomia (decisão do owner):** agentes geram a ordem; **humano aprova a ordem** antes de qualquer execução (paper inclusive). Live = stub de interface até gates existirem; B3 FIX/DMA só atrás do choke point.

### 4.6 `arc-agents` — Arquitetura agêntica (autônoma, persistente, proativa, que aprende)
**Roster (outputs schema'd):** CIO/Orchestrator · Macro Research · Regime · Signal/Strategy · Risk (**veto automático**) · Portfolio · Execution.
**Stack:** **Claude** (Opus p/ CIO/Research/crítica; Haiku p/ extração/roteamento) via Agent SDK, tool-use nativo + structured outputs + prompt caching. **Orquestração:** LangGraph (estado tipado, edges condicionais, HITL interrupts) **sobre Temporal** (durável, retomável, signals de aprovação/kill-switch). **Memória:** Postgres + **pgvector** (artefatos+outcomes estruturados + embeddings), retrieval híbrido asof-filtrado. **Aprendizado:** **LLM-as-judge** com rubricas pré-registradas contra as *invalidation conditions* de cada tese + atribuição quantitativa → re-peso de ensemble e fila de retrain/decommission (**não RL online sobre PnL ruidoso**). **Proatividade:** timers Temporal (pré-COPOM, dia de Focus, EOD) + event bus de anomalia (drawdown, data-health, flip de regime). **Guardrail de ouro:** LLM **nunca** emite número de risco/PnL nem ordem direta — só orquestra, forma tese e dispara ferramentas determinísticas; todo número vem "por referência" do `arc-quant`.

### 4.7 `mlops` + `orchestration` — MLOps, observabilidade & governança
**Reprodutibilidade:** `reproducibility.init()` em todo entrypoint (seed global, PYTHONHASHSEED, BLAS single-thread, manifesto por run). **CI que de fato bloqueia:** ruff+mypy, vitest, pytest (incl. leakage/PBO canaries), **backtest regression gate**. **Tracking:** MLflow self-hosted (Postgres). **Observabilidade:** Prometheus + Grafana + Loki + OTel; monitores de **drift** (PSI/KS nos inputs, IC realizado rolling nos outputs). **Governança (SR 11-7-lite p/ book próprio):** model_inventory + sign-off four-eyes, tiering de risco de modelo, challenger independente. **GPU:** CPU default; droplet GPU on-demand (Terraform auto-destroy) só p/ grid de HMM/GARCH, sequence models, SHAP grande.

### 4.8 `arc-funding` + `arc-report` — Gaps institucionais que viraram requisitos
- **`arc-funding`:** **margem B3** (inicial+variação), linhas de crédito NDF, financiamento NTN-B, **custo de funding do CDI** modelado honestamente (não o ternário hardcoded — é literalmente o artefato "Sharpe 3.83"); **escada de liquidez/capacity** (days-to-liquidate sob stress, concentração vs ADV por tenor DI/NTN-B/NDF — NDF e NTN-B longa são finas, **existencial** para book Brasil).
- **`arc-report`:** **P&L-explain diário** (carry vs roll-down vs spread vs FX vs alpha-de-sinal vs custo vs funding, reconciliando ao centavo) — *é o que pegaria "o retorno vem de carry, não de sinal" em produção*; factsheet/attribution **opcionais** (book próprio).

---

## 5. Gaps institucionais (do crítico) — agora requisitos de primeira classe

1. **Alocação de capital ENTRE estratégias** (strategy-of-strategies): risk-parity entre *sleeves* + caps de capacity; nada hoje aloca o budget de risco entre estratégias certificadas. → `arc-quant/portfolio` (alocador cross-strategy).
2. **Liquidez & capacity** fund-level → `arc-funding`.
3. **Margem/funding/colateral** → `arc-funding`.
4. **P&L-explain** diário reconciliado → `arc-report`.
5. **Survivorship do universo de instrumentos**: contratos DI rolam/deslistam; backtest precisa de **universo PIT** (quais tenores eram líquidos/listados em t), não só dados PIT — senão negocia contratos que não existiam.
6. **Coerência de cost model**: o mesmo objeto em backtester, paper-sim e TCA (3 cópias inflam pesquisa vs paper); calibrar dos fills de paper.
7. **PIT nos MARKS, não só nas features**: VaR, MTM, arrival de TCA e P&L-explain leem marks via `as_of()` com lag — leakage em mark é tão corrosivo quanto em feature.
8. **DR/BCP**: RPO/RTO, Postgres PITR + réplica, WORM cross-region, drill de restore-from-events, runbook de outage de broker (cancel-only).
9. **Model-risk register**, **counterparty/operational risk** (dependência de broker único, blast radius de key comprometida), **SLOs de latência de decisão dos agentes** (COPOM é time-sensitive; circuit breaker p/ trigger-storms).
10. *(diferido p/ book próprio)* compliance CVM/BACEN, investor reporting GIPS, data-licensing enforcement — projetados como **plugáveis** para virar fundo depois sem reescrever.

---

## 6. Sequenciamento (9 fases) → roadmap

A ordem **não é negociável** — cada fase é pré-requisito da seguinte.

| Fase | Bloco | Janela | Entregável |
|---|---|---|---|
| **0** | Fundações: monorepo (uv+pnpm+justfile), **arc-contracts** (JSON Schema→Pydantic/Zod), uv.lock+Docker pinado, seed global, `reproducibility.init()`, **CI rodando pytest+vitest**, migração **MySQL→Postgres** única | 0–30d | Base auditável e reprodutível |
| **1** | **arc-data bitemporal**: raw_observation, series_catalog (+lag +license), `as_of()` único, adapters refatorados, Focus/ALFRED vintage, contratos Pandera/GE, freshness gating | 0–30→30–60d | Dados PIT — fim do leakage de dados |
| **2** | **Régua honesta**: transforms causais, triple-barrier forward labels, CPCV+purge+embargo, Deflated Sharpe+PBO, GovernanceLedger, **leakage canaries como gate de CI**, golden-master do monólito | 30–60d | Veredito honesto "há edge?" |
| **3** | **Estrangular o monólito** (4402 LOC) atrás do `arc-engine` (FastAPI), extraindo módulos 1-a-1 sob golden-master + shadow-diff; **portar pricing B3** 1x (TS→Python) com parity | 30–60→60–90d | Sistema shippable, sem leakage |
| **4** | **Sinal & alpha** na base honesta: DFM/MIDAS, regime filtrado, Bayes+LGBM, meta-labeling, sanity gates | 60–90d | API de sinal tipada `{mu, sigma, gate, regime}` |
| **5** | **Risco + portfolio**: cov blend, GJR-GARCH, BL+cvxpy+HRP, Kelly, VaR/ES+Euler, stress/reverse, **kill-switch**, **alocador cross-strategy**, **margin/funding** | 60–90d | Risk veto + portfolio com constraints |
| **6** | **Execução + paper + OMS**: event-sourced, MTM real, paper-fill sim, TCA, recon, **P&L-explain**, **live-gate choke point** (default OFF), promotion pipeline | 60–90→90d+ | Operável em papel, auditável |
| **7** | **Camada agêntica**: grafo Temporal+LangGraph, números só por ferramenta, memória pgvector asof, LLM-as-judge evals, aprovações humanas de holdout/ordem, triggers COPOM/Focus | 90d+ | Sistema propõe/valida/gere autônomo, gated na ordem |
| **8** | **Wrap institucional**: observabilidade (Dagster/Prometheus/Grafana/Loki/OTel), drift, champion/challenger, model inventory, DR, capacity/liquidez | 90d+ | Plataforma endurecida |

**Mapeamento 30/60/90:** **30d** = Fases 0–2 (confiar no número). **60d** = Fases 3–5 (motor honesto + risco). **90d** = Fase 6 (paper auditável). **90d+** = Fases 7–8 (inteligência agêntica + plataforma).

---

## 7. O que preservar do repo atual (não jogar fora)

Adapters de dados reais e suas cadeias de fallback (ANBIMA OAuth, BCB chunked+retry, prioridade multi-fonte) · convenção de PnL walk-forward correta · BEER OLS rolling causal · Ledoit-Wolf · math de pricing B3 testada em `portfolioEngine.ts` (porta 1x) · config centralizado com limites por regime · dashboard React/tRPC (vira BFF fino) · ideia de cross-validação multi-fonte (mas calibrar PIT). **Estrangular, não reescrever do zero** — o sistema continua rodável a cada passo.

---

## 8. Próximo passo concreto

**Fase 0 + início da Fase 1**, em branch, sem tocar produção:
1. `reproducibility.init()` (seed global, manifesto run_id+git SHA) + `requirements.txt`/`uv.lock` pinado.
2. Scaffold `pytest` + os primeiros **leakage canaries** (winsorize/z-score causais; teste de invariância a `as_of`) — que já provam/medem o leakage do `_z_score_rolling`.
3. CI (GitHub Actions) rodando pytest + vitest (hoje não roda nada).
4. `arc-contracts` mínimo (RunManifest + SeriesContract) como fundação dos contratos tipados.

Cada item é commit pequeno, testável, reversível. A migração MySQL→Postgres e o `as_of()` vêm logo após, coordenando env vars com o owner para não quebrar o prod.

---

*Blueprint gerado por síntese multi-agente verificada. Specs completos por subsistema em `tasks/w6tje5x8o.output`.*
