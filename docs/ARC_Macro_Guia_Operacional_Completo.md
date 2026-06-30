# ARC Macro 2.0 — Guia Operacional Completo

## O Que É o ARC Macro

O ARC Macro é um **sistema quantitativo de overlay sobre CDI** que opera juros e câmbio brasileiros com uma filosofia radicalmente honesta: nenhuma estratégia é considerada válida até sobreviver a um holdout forward pré-registrado de 24 meses. Até lá, tudo é "candidato em accrual" — o sistema se recusa a mostrar Sharpe ou DSR antes do verdict.

O sistema gera **posições mensais** em 3 sleeves independentes, cada um explorando uma tese macro diferente sobre o Brasil. Você, como operador, decide se aceita, rejeita ou modifica cada proposta via Co-Pilot. Suas decisões alimentam o "operator stream" — um track record paralelo ao modelo puro.

---

## Arquitetura: 3 Streams Paralelos

O coração do sistema é a separação em **3 streams independentes por sleeve**:

| Stream | Quem controla | Propósito |
|--------|--------------|-----------|
| **Frozen** | Ninguém (determinístico) | A posição que foi "congelada" no momento do booking — é a ÚNICA entrada para o verdict do holdout. Intocável. |
| **Live** | Modelo automático | O que o modelo propõe hoje (pode divergir do frozen se o modelo foi atualizado). Benchmark de "auto-operate". |
| **Operator** | Você (Co-Pilot) | Suas decisões reais. Seu track record como gestor usando o sistema. |

**Regra fundamental**: o frozen stream nunca pode ser alterado por ninguém — nem por você, nem pelo modelo. Ele existe para garantir que o verdict do holdout seja estatisticamente válido (sem optional stopping, sem cherry-picking).

---

## Os 3 Sleeves: Teses de Investimento

### 1. momentum_front — DI Front (1Y)

**Tese**: Momentum de taxa de juros curta. Quando a curva DI de 1 ano está em tendência (caindo ou subindo), o modelo captura esse momentum.

| Parâmetro | Valor Atual |
|-----------|-------------|
| Proposta | OPERATE |
| Posição live | +1.400 (long DI = receive fixed = aposta em queda de juros curtos) |
| Sized exposure | +0.112 (11.2% do AUM em risco) |
| VaR95 | 3.5% |
| Gate binding | vol_target (a alavancagem é limitada pelo target de vol) |
| Accrual | 18/24 meses — **6 meses para o verdict** |

**Interpretação**: O modelo está **aplicado** (recebendo taxa fixa) na parte curta da curva. Ele acredita que a Selic vai cair ou que o DI 1Y vai comprimir. A posição +1.400 é forte — é o sleeve mais convicto.

**Trade na B3**: Comprar DI1F27 (receive fixed 1Y).

---

### 2. nowcast_long — DI Long (5Y)

**Tese**: Nowcast de atividade econômica aplicado à parte longa da curva. Quando indicadores antecedentes sugerem desaceleração, o modelo toma taxa longa (pay fixed = aposta em alta de juros longos).

| Parâmetro | Valor Atual |
|-----------|-------------|
| Proposta | OPERATE |
| Posição live | -0.600 (short DI = pay fixed = aposta em alta de juros longos) |
| Sized exposure | +0.060 (6% do AUM em risco) |
| VaR95 | 5.5% |
| Gate binding | var_limit (a alavancagem é limitada pelo VaR) |
| Accrual | 14/24 meses — **10 meses para o verdict** |
| Flag | Drift 12% vs frozen (a posição live divergiu do frozen) |

**Interpretação**: O modelo está **tomado** (pagando taxa fixa) na parte longa. Ele acredita que os juros de 5 anos vão subir — possivelmente por pressão fiscal ou expectativa de inflação de longo prazo. A posição é moderada (-0.600).

**Trade na B3**: Vender DI1F31 (pay fixed 5Y).

---

### 3. fiscal_hard — FX Spot (USDBRL)

**Tese**: Stress fiscal como driver do câmbio. Quando o Z-score de stress fiscal está elevado, o modelo compra USD (aposta em desvalorização do BRL).

| Parâmetro | Valor Atual |
|-----------|-------------|
| Proposta | HALT |
| Posição live | 0.000 (flat) |
| Sized exposure | 0.000 |
| VaR95 | 8.2% |
| Gate binding | es_limit (Expected Shortfall estourou o limite) |
| Circuit breakers | drawdown > -5%, vol spike > 2x target |
| Accrual | 10/24 meses — **14 meses para o verdict** |

**Interpretação**: O sleeve está **HALTED** — os circuit breakers dispararam porque o drawdown acumulado excedeu -5% e a volatilidade do câmbio está mais que o dobro do target. O modelo zerou a posição automaticamente por proteção. Não há trade a executar.

**Trade na B3**: Nenhum (flat).

---

## Como Ler a Página COMMAND

A página Command é seu "cockpit" — um resumo executivo de todo o sistema:

| Métrica | Significado |
|---------|-------------|
| **Operating** | Quantos sleeves estão gerando posição ativa (2 = momentum + nowcast) |
| **Halted** | Quantos sleeves foram parados por circuit breaker (1 = fiscal_hard) |
| **Gates active** | Quantos risk gates estão ativos (3/3 = todos limitando alavancagem) |
| **Operator decisions** | Quantas decisões você já tomou no mês corrente (3 = todas tomadas) |
| **Awaiting decision** | Quantas propostas aguardam sua decisão (0 = nada pendente) |
| **Proposals: fresh** | O modelo rodou e as propostas são atuais |
| **0 promoted** | Nenhum sleeve passou pelo verdict ainda — todos em accrual |

O banner amarelo "NOTHING PROMOTED" é **normal** — significa que o sistema está na fase de prova. Nenhum sleeve completou os 24 meses de holdout forward. Isso é honestidade, não falha.

---

## Como Operar o Co-Pilot (Decisões Mensais)

### Workflow Mensal

1. **O modelo roda** (automaticamente, 1x/mês) e gera novas propostas
2. **Você acessa o Co-Pilot** e vê 3 cards — um por sleeve
3. **Para cada sleeve**, você escolhe uma ação:
   - **APPROVE**: aceita a posição proposta (live) como sua
   - **SKIP**: zera a posição no operator stream (não opera)
   - **OVERRIDE**: insere uma posição diferente (você discorda do modelo)
4. **Decisão é imutável** — uma vez commitada, não pode ser alterada para aquele mês

### Quando APPROVE

- O modelo está OPERATE e a posição faz sentido macro
- Os risk gates não estão sinalizando problemas graves
- O drift entre frozen e live é pequeno (< 20%)
- Você não tem informação qualitativa contrária

### Quando SKIP

- Você tem informação que o modelo não captura (evento político, intervenção do BCB)
- O drift entre live e frozen é muito grande (o modelo "mudou de ideia" vs. o que foi registrado)
- Você está desconfortável com o risco agregado do portfólio
- Quer reduzir exposição temporariamente

### Quando OVERRIDE

- Você concorda com a direção mas quer menos/mais tamanho
- Você quer inverter a posição (raro — requer forte convicção)
- O modelo propõe HALT mas você quer operar mesmo assim (cuidado!)

---

## Como Ler a Página RISK

A página Risk mostra **por que** cada sleeve tem o tamanho que tem:

| Gate | Significado | Quando binda |
|------|-------------|--------------|
| **vol_target** | A alavancagem é limitada pelo target de volatilidade | Quando o ativo está com vol normal |
| **var_limit** | O VaR95 mensal atingiu o limite de 5.5% | Quando o ativo está mais volátil que o normal |
| **es_limit** | O Expected Shortfall atingiu 7.5% | Quando há risco de cauda (fat tails) — mais restritivo |

**Fórmula de sizing**: `applied_leverage = min(vol_target, var_limit/VaR_per_unit, es_limit/ES_per_unit)`

O gate mais restritivo vence. Se o ES estourar, a posição é zerada (HALT).

### Flags (alertas)

- **DRIFT**: a posição live divergiu significativamente da frozen (o modelo "mudou de opinião" desde o booking)
- **CIRCUIT**: um circuit breaker disparou (drawdown ou vol spike) — o sleeve é automaticamente zerado

---

## Como Ler a Página MACRO

Esta página mostra o **contexto macroeconômico** que alimenta o modelo. Não é uma recomendação — é o "estado do mundo" como o modelo o vê:

### Composite r* (Taxa Neutra Real)

Valor atual: **4.37% real**, tendência de 6 meses: +0.16. Isso significa que o modelo estima que a taxa de juros real de equilíbrio do Brasil é 4.37%. Se a Selic real está acima disso, há espaço para corte; se está abaixo, há pressão para alta.

### Regime HMM (Hidden Markov Model)

O modelo classifica o ambiente em 5 regimes:

| Regime | Prob. Atual | Significado |
|--------|-------------|-------------|
| **Carry** | 42% (dominante) | Ambiente favorável a carry trade — juros altos, vol baixa, fluxo entrando |
| **Riskoff** | 18% | Aversão a risco global — USD forte, EM fraco |
| **Stress** | 8% | Crise/pânico — correlações quebram, vol explode |
| **Domestic Calm** | 22% | Brasil tranquilo domesticamente |
| **Domestic Stress** | 10% | Stress doméstico (fiscal, político) |

**Regime dominante = Carry**: o modelo vê um ambiente de "colheita" — juros altos com vol controlada. Isso é consistente com a posição do momentum_front (aplicado, apostando que juros vão cair gradualmente).

### State Variables (Z-scores)

| Variável | Z-score | Interpretação |
|----------|---------|---------------|
| Fiscal stress | +0.85 | Acima da média — pressão fiscal moderada |
| Terms of trade | -0.42 | Ligeiramente abaixo — termos de troca não ajudam |
| Dollar (DXY) | -0.91 | Dólar global fraco — positivo para EM |
| Global risk (VIX) | +0.39 | Ligeiramente acima — alguma cautela global |
| CDS Brasil 5Y | -1.31 | Muito abaixo da média — risco-país comprimido (bom) |
| Policy gap | +1.05 | Selic acima do neutro — espaço para corte |
| Real rate diff | +1.48 | Diferencial de juros reais BR-US muito alto — atrai carry |
| Iron ore | +0.04 | Neutro |

### FX Fair Value

Fair = 5.420, Spot = 5.680 → **BRL 4.8% barato vs. fair value**. O modelo vê o real desvalorizado, mas o fiscal_hard está HALTED (vol muito alta para operar).

---

## Como Ler a Página HOLDOUT

O holdout é o **juiz final** do sistema. Cada sleeve precisa acumular 24 meses de retornos forward (começando em Jul/2024) e então o DSR (Deflated Sharpe Ratio) é calculado. Se DSR ≥ 1.00, o sleeve é "promovido" — caso contrário, é descartado.

| Parâmetro | Significado |
|-----------|-------------|
| **n_trials = 36** | O sistema já testou 36 hipóteses ao longo da pesquisa — o DSR é deflacionado por isso |
| **eval_at_n = 24** | O verdict acontece exatamente no mês 24 — sem optional stopping |
| **dsr_min = 1.00** | A barra mínima para promoção (pool usa 0.80 por ter diversificação) |
| **forward_start = 2024-07-01** | Data de corte — só retornos após esta data contam |

**Timeline dos verdicts**:
- momentum_front: Janeiro 2027 (6 meses)
- nowcast_long: Maio 2027 (10 meses)
- fiscal_hard: Setembro 2027 (14 meses)
- pool: Setembro 2027 (14 meses, mas pode ser ~1 ano antes se K_eff alto)

---

## Portfólio Atual e Execução (AUM = R$ 10MM)

### Posições para Julho 2026

| Sleeve | Direção | Contratos | Instrumento | Ação na B3 |
|--------|---------|-----------|-------------|------------|
| momentum_front | Long DI (receive) | **12** | DI1F27 | Comprar 12 contratos |
| nowcast_long | Short DI (pay) | **14** | DI1F31 | Vender 14 contratos |
| fiscal_hard | Flat (HALTED) | 0 | — | Nenhuma ação |

### Perfil de Risco Agregado

O portfólio líquido é um **steepener** — aposta que a curva DI vai inclinar (juros curtos caem mais que longos, ou longos sobem mais que curtos):

- Se a curva **inclinar** (1Y cai, 5Y sobe): ambos os sleeves ganham
- Se a curva **achatar** (1Y sobe, 5Y cai): ambos perdem
- Se a curva se mover em **paralelo**: parcialmente hedgeado (posições opostas em duration)

### Sensibilidade

| Cenário | P&L Estimado |
|---------|-------------|
| DI 1Y cai 25bp, 5Y sobe 10bp (steepening) | +R$ 8,700 |
| Curva paralela -25bp (bull flattening) | +R$ 850 (momentum ganha, nowcast perde) |
| Curva paralela +25bp (bear flattening) | -R$ 850 |
| DI 1Y sobe 25bp, 5Y cai 10bp (flattening) | -R$ 8,700 |

---

## Ciclo Operacional Completo

```
┌─────────────────────────────────────────────────────────────┐
│  DIA 1 DO MÊS (ou quando "proposals: fresh" aparecer)      │
│                                                              │
│  1. Abra arc-macro.com → COMMAND                            │
│     • Verifique: proposals = fresh? Awaiting decision > 0?  │
│                                                              │
│  2. Vá para MACRO                                           │
│     • Leia o regime, r*, state variables                    │
│     • Forme sua visão qualitativa                           │
│                                                              │
│  3. Vá para RISK                                            │
│     • Verifique flags e circuit breakers                    │
│     • Entenda por que cada sleeve tem o tamanho que tem     │
│                                                              │
│  4. Vá para CO-PILOT                                        │
│     • Para cada sleeve: APPROVE / SKIP / OVERRIDE           │
│     • Decisão é IMUTÁVEL — pense antes de clicar            │
│                                                              │
│  5. EXECUTE NA B3                                           │
│     • Converta sized_exposure em contratos (ver fórmula)    │
│     • Execute as ordens no book da B3                       │
│                                                              │
│  6. Monitore durante o mês                                  │
│     • RISK: flags de drift ou circuit                       │
│     • Se circuit disparar mid-month: zere a posição         │
│                                                              │
│  7. Fim do mês: aguarde novas propostas                     │
└─────────────────────────────────────────────────────────────┘
```

---

## Fórmula de Conversão: Sized Exposure → Contratos

```
contratos = sized_exposure × AUM / (DV01_por_contrato × 100)
```

| Instrumento | DV01 aproximado | Multiplicador |
|-------------|----------------|---------------|
| DI1F27 (1Y) | R$ 9.50/bp | 1 contrato = R$ 950 de risco por 100bp |
| DI1F31 (5Y) | R$ 42.00/bp | 1 contrato = R$ 4,200 de risco por 100bp |
| WDO (mini dólar) | USD 10,000/contrato | 1 contrato = USD 10k notional |
| DOL (dólar cheio) | USD 50,000/contrato | 1 contrato = USD 50k notional |

**Exemplo com AUM = R$ 10MM**:
- momentum_front: 0.112 × 10,000,000 / (9.50 × 100) = **12 contratos DI1F27**
- nowcast_long: 0.060 × 10,000,000 / (42.00 × 100) = **14 contratos DI1F31**

---

## Glossário Rápido

| Termo | Definição |
|-------|-----------|
| **Accrual** | Fase de acumulação de meses no holdout forward |
| **Verdict** | Momento em que o holdout "dispara" e decide se o sleeve é promovido ou descartado |
| **DSR** | Deflated Sharpe Ratio — Sharpe ajustado pelo número de hipóteses testadas |
| **Frozen** | Posição congelada no booking — nunca muda, é a base do verdict |
| **Live** | Posição que o modelo propõe hoje (pode divergir do frozen) |
| **Operator** | Sua posição real (resultado das decisões no Co-Pilot) |
| **HALT** | Sleeve parado por circuit breaker — posição zerada automaticamente |
| **Drift** | Divergência entre a posição live e a frozen (modelo "mudou de ideia") |
| **Gate** | Mecanismo de risk que limita a alavancagem (vol_target, var_limit, es_limit) |
| **Sized exposure** | Fração do AUM efetivamente em risco após aplicar todos os gates |
| **Promoted** | Sleeve que passou no verdict e pode operar com capital real sem restrição |

---

## Perguntas Frequentes

**P: O sistema está perdendo dinheiro?**
R: O fiscal_hard está com cum return negativo (-2.8% frozen). Os outros dois estão positivos (momentum +4.2%, nowcast -1.5%). Mas lembre: esses são retornos operacionais, não "track record" — o verdict ainda não disparou.

**P: Por que não posso mudar minha decisão do mês?**
R: Imutabilidade é um princípio de design. Se você pudesse mudar, o operator stream seria contaminado por hindsight bias. A regra força disciplina.

**P: O que acontece quando o verdict disparar?**
R: Se DSR ≥ 1.00, o sleeve é "promovido" — passa a operar com autonomia total (sem necessidade de APPROVE mensal). Se DSR < 1.00, o sleeve é descartado — a tese não tinha edge real.

**P: Posso ignorar o sistema e operar por conta?**
R: Sim, mas suas decisões ficam registradas no operator stream. O sistema não te obriga a nada — ele propõe e você decide. O valor está em ter um framework disciplinado e auditável.

**P: O que é o "pool"?**
R: Uma combinação equal-weight dos 3 sleeves. Se vários sleeves tiverem edge real, o pool pode atingir o verdict antes dos individuais (diversificação reduz a barra necessária: dsr_min = 0.80 vs 1.00).
