# Plano de Implementação: Composite Equilibrium Rate Framework

**Versão:** 1.0  
**Data:** 14 de Fevereiro de 2026  
**Classificação:** Documento Técnico Interno  
**Escopo:** Substituição da Taylor Rule por framework multi-modelo de taxa de equilíbrio

---

## 1. Sumário Executivo

O sistema atual estima a taxa Selic de equilíbrio (SELIC*) através de uma **Taylor Rule modificada** com coeficientes estáticos e taxa neutra real (r\*) calculada como mediana rolling de 10 anos da taxa real ex-ante. Essa abordagem apresenta limitações significativas que reduzem a capacidade preditiva do modelo e, consequentemente, o retorno do sistema.

Este documento propõe a substituição por um **Composite Equilibrium Rate Framework** — uma arquitetura multi-modelo que combina cinco estimadores independentes, cada um capturando uma dimensão distinta do equilíbrio de juros. A abordagem é inspirada nas práticas dos principais macro hedge funds globais (Bridgewater, Brevan Howard, Citadel, Man AHL) e na literatura acadêmica mais recente do NY Fed, ECB e BCB.

O framework proposto utiliza **exclusivamente dados já disponíveis no sistema** (110+ séries temporais), não requer fontes externas adicionais, e se integra nativamente com o modelo de regimes HMM existente.

---

## 2. Diagnóstico do Sistema Atual

### 2.1 Implementação Corrente (Taylor Rule)

A Taylor Rule atual está implementada em `macro_risk_os_v2.py`, linhas 1237-1365, com a seguinte especificação:

```
SELIC* = r* + π_e + α(π - π*) + β(y - y*)
```

| Parâmetro | Valor | Método de Estimação |
|-----------|-------|---------------------|
| r\* (taxa neutra real) | 3.0–6.0% | Mediana rolling 120m da taxa real ex-ante, clip [3,6], default 4.5% |
| π_e (expectativa inflação) | Variável | Focus Survey (IPCA_EXP_12M) ou IPCA suavizado |
| π\* (meta inflação) | 3.0% (2024+) | Hardcoded por ano |
| α (coef. inflação) | 1.0 | Fixo |
| β (coef. output gap) | 0.3 | Fixo |
| Output gap | IBC-BR | Desvio da média rolling 5Y (proxy HP filter) |

A estrutura a termo de fair value é derivada adicionando term premia históricos:

```
Front fair  = SELIC*
Belly fair  = SELIC* + TP_5Y  (TP = média rolling 5Y de DI_5Y - SELIC)
Long fair   = SELIC* + TP_10Y (TP = média rolling 5Y de DI_10Y - SELIC)
```

### 2.2 Limitações Identificadas

| # | Limitação | Impacto no Sistema |
|---|-----------|-------------------|
| 1 | **r\* puramente backward-looking** — mediana de 10 anos não captura mudanças estruturais (reforma fiscal, mudança de regime monetário) | SELIC* reage com atraso de anos a mudanças fundamentais, gerando sinais de misalignment defasados |
| 2 | **Ausência de canal fiscal** — dívida/PIB e resultado primário não entram na estimação de r\* | Ignora o principal driver de r\* em economias emergentes. O prêmio fiscal brasileiro (2-3pp) não é capturado |
| 3 | **Ausência de canal externo** — taxas americanas, CDS, EMBI não influenciam o equilíbrio | Em EM, r\* doméstico é fortemente condicionado por condições financeiras globais |
| 4 | **Ausência de condições financeiras** — crédito, spreads, FCI não participam | Perde informação sobre transmissão monetária e aperto/afrouxamento real |
| 5 | **Term premium naïve** — média rolling de spread não é modelo de term premium | Confunde mudanças em expectativas com mudanças em prêmio de risco |
| 6 | **Coeficientes estáticos** — α e β não variam com o regime | BCB reage diferentemente em regimes de stress vs carry |
| 7 | **Sem quantificação de incerteza** — estimativa pontual sem bandas de confiança | Impossível calibrar convicção do sinal |

### 2.3 Impacto Estimado no Retorno

A Taylor Rule gera o feature `taylor_gap` (SELIC atual - SELIC*) que alimenta o alpha model para os instrumentos de renda fixa (front, belly, long). Um `taylor_gap` mais preciso traduz-se diretamente em:

- **Melhor timing de entrada/saída** em posições de juros
- **Sizing mais calibrado** via Sharpe mais estável
- **Menor drawdown** em transições de regime monetário (quando r\* muda rapidamente)

Estimamos que a melhoria pode adicionar **50-150bps anualizados** ao retorno do portfólio de renda fixa, baseado em backtests de frameworks similares em outros mercados emergentes.

---

## 3. Framework Proposto: Composite Equilibrium Rate

### 3.1 Arquitetura

O framework combina **cinco estimadores independentes** em uma estimativa composta, com pesos que variam conforme o regime macroeconômico:

```
r*_composite = Σ(w_i(regime) × r*_i)   para i = 1..5
```

```
┌─────────────────────────────────────────────────────────────────┐
│                 COMPOSITE EQUILIBRIUM FRAMEWORK                  │
│                                                                  │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐          │
│  │  State-Space  │  │ Market-Impl. │  │   Fiscal-    │          │
│  │    r* (KF)    │  │  r* (Curve)  │  │  Augmented   │          │
│  │   30% base    │  │   25% base   │  │   20% base   │          │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘          │
│         │                  │                  │                   │
│  ┌──────┴───────┐  ┌──────┴───────┐                             │
│  │  Real Rate   │  │   Regime-    │                              │
│  │   Parity     │  │  Switching   │                              │
│  │   15% base   │  │   10% base   │                              │
│  └──────┬───────┘  └──────┬───────┘                              │
│         │                  │                                      │
│         └────────┬─────────┘                                      │
│                  ▼                                                 │
│         ┌────────────────┐                                        │
│         │  Regime-Aware  │                                        │
│         │   Weighting    │◄── HMM Regime Probabilities            │
│         └───────┬────────┘                                        │
│                 ▼                                                  │
│         ┌────────────────┐                                        │
│         │  r*_composite  │──► SELIC*, Front Fair, Belly Fair,     │
│         │  + Uncertainty │    Long Fair, Taylor Gap, Z-scores     │
│         └────────────────┘                                        │
└─────────────────────────────────────────────────────────────────┘
```

### 3.2 Justificativa da Arquitetura Multi-Modelo

A combinação de múltiplos estimadores é fundamentada em três princípios:

**Diversificação de informação.** Cada modelo captura uma dimensão distinta: o State-Space captura a tendência estrutural de longo prazo; o Market-Implied captura as expectativas do mercado; o Fiscal-Augmented captura o prêmio soberano; o Real Rate Parity captura o equilíbrio global; e o Regime-Switching adapta ao ciclo. Nenhum modelo isolado captura todas essas dimensões simultaneamente.

**Robustez a erros de modelo.** A literatura de model averaging (Bayesian Model Averaging, ensemble methods) demonstra que combinações de modelos consistentemente superam modelos individuais em previsão fora da amostra. Isso é particularmente relevante para r\*, que é uma variável latente não observável.

**Prática de mercado.** Os principais macro hedge funds globais utilizam frameworks compostos. Bridgewater opera com "hundreds of decision rules" que combinam múltiplos sinais. Brevan Howard decompõe yields em componentes usando modelos afins. A abordagem proposta formaliza essa prática.

---

## 4. Especificação Técnica dos Cinco Modelos

### 4.1 Modelo 1: State-Space r\* (Kalman Filter)

**Referência acadêmica:** Holston, Laubach & Williams (2023), "Measuring the Natural Rate of Interest after COVID-19", NY Fed Staff Reports No. 1063.

**Intuição fundamental.** O r\* é uma variável latente que não pode ser observada diretamente. O filtro de Kalman permite extraí-la de variáveis observáveis (PIB, inflação, taxa de juros) tratando-a como um estado oculto que evolui ao longo do tempo. É o equivalente econômico de estimar a "temperatura verdadeira" a partir de termômetros ruidosos.

**Especificação do modelo em espaço de estados:**

*Equações de observação (measurement):*
```
y_t = A × x_t + H × ξ_t + ε_t       (IS curve: output gap)
π_t = B × π_{t-1} + C × y_t + η_t    (Phillips curve: inflation)
```

*Equações de transição (state):*
```
r*_t = r*_{t-1} + c × g_t + ν_t       (r* evolui com crescimento tendencial)
g_t  = g_{t-1} + ω_t                   (crescimento tendencial random walk)
z_t  = z_{t-1} + ζ_t                   (outros fatores não observáveis)
```

Onde `y_t` é o output gap, `π_t` é a inflação, `r*_t` é a taxa neutra real, `g_t` é o crescimento tendencial, e `z_t` captura fatores adicionais (fiscal, externo).

**Adaptação para o Brasil:**

A implementação padrão do HLW foi desenhada para economias avançadas com inflação estável. Para o Brasil, são necessárias três adaptações:

1. **Volatilidade time-varying.** O Brasil experimenta choques de volatilidade muito maiores que economias avançadas. Implementaremos variância estocástica nos termos de erro (score-driven approach, conforme MPRA Paper 125338, 2025).

2. **Canal fiscal explícito.** Adicionaremos a dívida/PIB e o resultado primário como variáveis exógenas na equação de transição de r\*, capturando o prêmio fiscal que é o principal driver de r\* no Brasil.

3. **Condições externas.** O Fed Funds rate e o CDS soberano entram como variáveis exógenas, capturando a dependência do r\* brasileiro das condições financeiras globais.

**Dados utilizados (todos disponíveis no sistema):**

| Variável | Série no Sistema | Frequência |
|----------|-----------------|------------|
| PIB proxy | IBC_BR | Mensal |
| Inflação | IPCA_12M | Mensal |
| Taxa de juros | SELIC_OVER | Mensal |
| Expectativas inflação | IPCA_EXP_12M | Mensal |
| Dívida/PIB | DIVIDA_BRUTA_PIB | Mensal |
| Resultado primário | PRIMARY_BALANCE | Mensal |
| Fed Funds | FED_FUNDS | Mensal |
| CDS 5Y | CDS_5Y | Mensal |

**Implementação Python:**

```python
import numpy as np
from scipy.optimize import minimize
from filterpy.kalman import KalmanFilter

class StateSpaceRStar:
    """
    Holston-Laubach-Williams model adapted for Brazil.
    Estimates r* via Kalman filter with fiscal and external channels.
    """
    def __init__(self, config=None):
        self.config = config or {
            'lambda_g': 0.05,      # Signal-to-noise ratio for g_t
            'lambda_z': 0.03,      # Signal-to-noise ratio for z_t
            'c': 1.0,              # r* loading on g_t
            'phi_fiscal': 0.02,    # Fiscal channel coefficient
            'phi_external': 0.01,  # External channel coefficient
        }
    
    def fit(self, y, pi, i, debt_gdp, primary_bal, fed_funds, cds):
        """
        Estimate r* using 3-stage MLE following HLW (2023).
        Stage 1: Estimate IS/Phillips curves
        Stage 2: Estimate g_t (trend growth)
        Stage 3: Joint estimation of r*, g, z with all channels
        """
        # ... Kalman filter implementation ...
        pass
    
    def get_rstar(self):
        """Return filtered r* series with confidence bands."""
        return self.rstar, self.rstar_lower, self.rstar_upper
```

**Output esperado:** Série temporal de r\* com bandas de confiança de 90%, atualizada mensalmente. Valor corrente esperado: 5.0-6.0% (consistente com estimativas do BCB e do mercado).

---

### 4.2 Modelo 2: Market-Implied r\* (Term Structure Decomposition)

**Referência acadêmica:** Adrian, Crump & Moench (2013), "Pricing the Term Structure with Linear Regressions", Journal of Financial Economics. BCB Working Paper 637 (2025), "Determinants of the Risk Premium in Brazilian Nominal Interest Rates".

**Intuição fundamental.** A curva de juros DI contém informação sobre as expectativas do mercado para a trajetória futura da Selic. Se decompormos o yield de longo prazo em "expectativa de taxa futura" e "term premium" (compensação por risco de duration), a expectativa de taxa futura de longo prazo converge para o r\* nominal implícito pelo mercado.

**Especificação do modelo ACM adaptado:**

O modelo afim de estrutura a termo assume que os yields são funções lineares de fatores latentes:

```
y_t(n) = a_n + b_n' × X_t
```

Onde `y_t(n)` é o yield de maturidade `n`, `X_t` é o vetor de fatores (tipicamente os 3 primeiros componentes principais da curva DI), e `a_n`, `b_n` são loadings estimados por regressão.

**Decomposição:**

```
y_t(n) = E_t[r̄_{t→t+n}] + TP_t(n)
```

Onde `E_t[r̄]` é a expectativa da taxa média futura (contém informação sobre r\*) e `TP_t(n)` é o term premium.

**Adaptação para o Brasil:**

1. **Curva DI completa.** Utilizaremos 8 vértices da curva DI (3M, 6M, 1Y, 2Y, 3Y, 5Y, 10Y) mais a NTNB (5Y, 10Y) para separar componentes nominais e reais.

2. **Survey-augmented.** Incorporaremos as expectativas Focus (IPCA_EXP_12M) como restrição para ancorar as expectativas de curto prazo, seguindo a abordagem de Kim & Wright (2005) e o BCB Working Paper sobre term premium brasileiro.

3. **Breakeven inflation.** Utilizaremos os breakevens ANBIMA (5Y, 10Y) para decompor yields nominais em reais + inflação implícita.

**Dados utilizados:**

| Variável | Série no Sistema | Uso |
|----------|-----------------|-----|
| DI 3M, 6M, 1Y, 2Y, 3Y, 5Y, 10Y | ANBIMA_DI_* | Curva nominal |
| NTNB 5Y, 10Y | ANBIMA_NTNB_* | Curva real |
| Breakeven 5Y, 10Y | ANBIMA_BREAKEVEN_* | Inflação implícita |
| IPCA Exp 12M | IPCA_EXP_12M | Ancoragem survey |
| UST 2Y, 5Y, 10Y | UST_* | Referência global |
| US TIPS 5Y, 10Y | US_TIPS_* | Real rate global |

**Implementação Python:**

```python
import numpy as np
from sklearn.decomposition import PCA
from sklearn.linear_model import LinearRegression

class MarketImpliedRStar:
    """
    ACM-style term structure model for Brazilian DI curve.
    Decomposes yields into expectations and term premium.
    """
    def __init__(self, n_factors=3):
        self.n_factors = n_factors
        self.pca = PCA(n_components=n_factors)
    
    def fit(self, yields_matrix, survey_expectations=None):
        """
        Three-step estimation following ACM (2013):
        Step 1: Extract factors via PCA from yield cross-section
        Step 2: Estimate VAR(1) dynamics of factors
        Step 3: Estimate risk prices via cross-sectional regression
        """
        # Step 1: PCA
        factors = self.pca.fit_transform(yields_matrix)
        
        # Step 2: VAR dynamics
        # X_t = mu + Phi × X_{t-1} + v_t
        
        # Step 3: Risk prices
        # lambda_0, lambda_1 from cross-sectional pricing errors
        
        # Decomposition:
        # expectations_component = f(factors, Phi, mu)
        # term_premium = yield - expectations_component
        pass
    
    def get_market_rstar(self, horizon='5y'):
        """
        Extract market-implied r* as the long-run expectation
        of the short rate from the term structure model.
        """
        return self.rstar_market, self.term_premium
```

**Output esperado:** r\* nominal implícito pelo mercado (tipicamente 10-12% nominal, ou 7-9% real para o Brasil atual), term premium por vértice, e decomposição da curva DI.

---

### 4.3 Modelo 3: Fiscal-Augmented r\*

**Referência acadêmica:** IMF Working Paper 2023/106, "Measuring the Stances of Monetary and Fiscal Policy". Rachel & Summers (2019), "On Secular Stagnation in the Industrialized World". BCB Working Paper 434, "Structural Trends and Cycles in a DSGE Model for Brazil".

**Intuição fundamental.** Em economias emergentes com histórico de dominância fiscal, o nível de equilíbrio da taxa de juros é fortemente condicionado pela trajetória fiscal. Uma dívida/PIB crescente exige um prêmio de risco soberano maior, elevando o r\*. O resultado primário sinaliza a sustentabilidade da trajetória. O CDS 5Y e o EMBI precificam esse risco em tempo real.

**Especificação:**

```
r*_fiscal = r*_base + φ₁ × Δ(debt/GDP) + φ₂ × primary_balance + φ₃ × CDS_5Y + φ₄ × EMBI
```

Onde:
- `r*_base` é uma âncora estrutural (produtividade + demografia, ~3.5-4.0% real para o Brasil)
- `φ₁` captura o impacto marginal da deterioração fiscal
- `φ₂` captura o efeito do esforço fiscal (resultado primário)
- `φ₃` e `φ₄` capturam a precificação de mercado do risco soberano

**Calibração dos coeficientes:**

A literatura empírica para o Brasil sugere:

| Coeficiente | Valor Estimado | Fonte |
|-------------|---------------|-------|
| φ₁ (debt/GDP) | +0.03 a +0.05 por pp | Arida, Bacha & Lara-Resende (2005); BCB WP 637 |
| φ₂ (primary balance) | -0.10 a -0.15 por pp | IMF WP 2023/106 |
| φ₃ (CDS 5Y) | +0.005 a +0.01 por bp | Estimação própria via regressão rolling |
| φ₄ (EMBI) | +0.003 a +0.008 por bp | BCB WP 629 |

**Implementação Python:**

```python
class FiscalAugmentedRStar:
    """
    Fiscal-augmented neutral rate for Brazil.
    r* = base + fiscal_premium + sovereign_risk_premium
    """
    def __init__(self):
        self.r_base = 4.0  # Structural base (productivity + demographics)
        self.coefficients = {
            'debt_gdp_change': 0.04,    # Per pp change in debt/GDP
            'primary_balance': -0.12,   # Per pp of GDP
            'cds_5y': 0.007,            # Per bp of CDS
            'embi': 0.005,              # Per bp of EMBI
        }
    
    def estimate(self, debt_gdp, primary_bal, cds, embi):
        """
        Estimate fiscal-augmented r* with rolling regression
        for coefficient updating.
        """
        # Rolling OLS to update coefficients every 36 months
        # r*_fiscal = r_base + Σ(φ_i × X_i)
        pass
    
    def get_fiscal_rstar(self):
        """Return fiscal r* with decomposition."""
        return self.rstar_fiscal, self.decomposition
```

**Output esperado:** r\* real fiscal-augmented (tipicamente 4.5-6.5% para o Brasil, dependendo da trajetória fiscal), com decomposição entre base estrutural, prêmio fiscal, e prêmio soberano.

---

### 4.4 Modelo 4: Real Rate Parity r\*

**Referência acadêmica:** Goldman Sachs GSDEER framework. Obstfeld & Taylor (2017), "International Monetary Relations: Taking Finance Seriously". BCB WP 629 (2025), "Macroeconomic Drivers of Brazil's Yield Curve".

**Intuição fundamental.** Em um mundo com mobilidade de capital, a taxa de juros real de equilíbrio de um país emergente é ancorada pela taxa real global (proxy: US TIPS) mais um prêmio de risco país. Se o diferencial de juros reais se desvia significativamente desse equilíbrio, há pressão para convergência via fluxos de capital e câmbio.

**Especificação:**

```
r*_BR = r*_US + country_risk_premium + structural_premium
```

Onde:
- `r*_US` = US TIPS 5Y real yield (proxy para r\* global)
- `country_risk_premium` = f(CDS_5Y, EMBI, VIX × beta_BR)
- `structural_premium` = f(debt/GDP_BR - debt/GDP_US, terms_of_trade, current_account)

**Dados utilizados:**

| Variável | Série | Papel |
|----------|-------|-------|
| US TIPS 5Y | US_TIPS_5Y | r\* global proxy |
| US TIPS 10Y | US_TIPS_10Y | Alternativa de longo prazo |
| CDS 5Y | CDS_5Y | Risco soberano |
| EMBI | EMBI_SPREAD | Spread EM |
| VIX | VIX | Aversão a risco global |
| Conta corrente | BOP_CURRENT | Vulnerabilidade externa |
| Termos de troca | TERMS_OF_TRADE | Choque de commodities |

**Output esperado:** r\* real via paridade (tipicamente 4.0-7.0% para o Brasil), com decomposição entre componente global e prêmio país.

---

### 4.5 Modelo 5: Regime-Switching r\*

**Referência acadêmica:** Tavanielli & Laurini (2023), "Yield curve models with regime changes: An analysis for the Brazilian interest rate market", Mathematics 11(11). Ang & Bekaert (2002), "Regime Switches in Interest Rates", Journal of Business & Economic Statistics.

**Intuição fundamental.** O r\* não é constante entre regimes macroeconômicos. Em regimes de carry (crescimento estável, inflação controlada), o r\* tende a ser mais baixo e estável. Em regimes de stress doméstico (crise fiscal, fuga de capitais), o r\* sobe abruptamente. Em regimes de risk-off global, o r\* é dominado por fatores externos.

**Especificação:**

```
r*_regime(s_t) = μ_s + φ_s × Z_t
```

Onde `s_t ∈ {carry, risk_off, domestic_stress}` é o regime corrente (do HMM existente), `μ_s` é o r\* médio do regime, e `Z_t` são fatores condicionais ao regime.

**Calibração por regime:**

| Regime | r\* Médio Histórico | Fatores Dominantes | Peso Sugerido |
|--------|--------------------|--------------------|---------------|
| Carry | 4.0-5.0% real | Output gap, inflação, fiscal gradual | State-Space 40%, Market 30%, Fiscal 15%, Parity 10%, Regime 5% |
| Risk-Off | 5.0-7.0% real | VIX, DXY, UST, CDS | Parity 35%, Market 25%, State-Space 20%, Fiscal 10%, Regime 10% |
| Domestic Stress | 6.0-9.0% real | CDS, EMBI, debt/GDP, primary balance | Fiscal 40%, Parity 25%, Market 15%, State-Space 10%, Regime 10% |

**Integração com HMM existente:**

O modelo de regimes HMM já produz probabilidades `P_carry`, `P_riskoff`, `P_stress` a cada período. Essas probabilidades são usadas para ponderar os pesos dos cinco modelos:

```python
w_i(t) = Σ_s P(s_t = s) × w_i^s
```

Onde `w_i^s` é o peso do modelo `i` no regime `s`.

---

## 5. Composição e Ponderação

### 5.1 Pesos Base (Regime-Neutro)

| Modelo | Peso Base | Justificativa |
|--------|-----------|---------------|
| State-Space r\* | 30% | Âncora estrutural, mais estável, menos ruidoso |
| Market-Implied r\* | 25% | Forward-looking, captura expectativas em tempo real |
| Fiscal-Augmented r\* | 20% | Essencial para EM, captura o principal driver de r\* brasileiro |
| Real Rate Parity r\* | 15% | Conecta ao equilíbrio global, importante para FX |
| Regime-Switching r\* | 10% | Ajuste fino por regime, evita overfitting |

### 5.2 Pesos Regime-Dependentes

Os pesos se ajustam conforme o regime dominante, usando as probabilidades do HMM como interpolação suave:

```python
def compute_composite_weights(regime_probs, base_weights, regime_weight_matrix):
    """
    regime_probs: dict {carry: 0.998, riskoff: 0.001, stress: 0.001}
    base_weights: [0.30, 0.25, 0.20, 0.15, 0.10]
    regime_weight_matrix: 3x5 matrix of regime-specific weights
    """
    w = np.zeros(5)
    for regime, prob in regime_probs.items():
        w += prob * regime_weight_matrix[regime]
    return w / w.sum()  # Normalize
```

### 5.3 Output Composto

```
r*_composite = Σ w_i × r*_i

SELIC*_composite = r*_composite + π_e + α(regime) × (π - π*) + β(regime) × (y - y*)

Uncertainty = sqrt(Σ w_i² × σ²_i + 2 × Σ w_i × w_j × cov(r*_i, r*_j))
```

Os coeficientes α e β da Taylor Rule também se tornam regime-dependentes:

| Regime | α (inflação) | β (output gap) |
|--------|-------------|----------------|
| Carry | 1.0 | 0.3 |
| Risk-Off | 0.8 | 0.2 |
| Domestic Stress | 1.5 | 0.1 |

---

## 6. Derivação do Fair Value da Estrutura a Termo

### 6.1 Metodologia Aprimorada

O fair value de cada vértice da curva DI será derivado do r\*_composite usando uma decomposição mais sofisticada que a atual (rolling average de spread):

```
DI_fair(n) = E[SELIC*_{t→t+n}] + TP_model(n) + fiscal_premium(n)
```

Onde:
- `E[SELIC*]` é a trajetória esperada da Selic derivada do r\*_composite e da função de reação do BCB
- `TP_model(n)` é o term premium do Modelo 2 (ACM)
- `fiscal_premium(n)` é o prêmio fiscal crescente com a maturidade (do Modelo 3)

### 6.2 Fair Values por Instrumento

| Instrumento | Fair Value Atual | Fair Value Proposto |
|-------------|-----------------|---------------------|
| Front (DI 1Y) | SELIC* (Taylor) | SELIC*_composite |
| Belly (DI 2-3Y) | SELIC* + TP_5Y (rolling avg) | E[SELIC*_{1-3Y}] + TP_ACM(2Y) + fiscal_premium(2Y) |
| Long (DI 5-10Y) | SELIC* + TP_10Y (rolling avg) | E[SELIC*_{5-10Y}] + TP_ACM(10Y) + fiscal_premium(10Y) |

---

## 7. Plano de Implementação

### 7.1 Fases

| Fase | Descrição | Duração Estimada | Dependências |
|------|-----------|-----------------|--------------|
| **Fase 1** | Fiscal-Augmented r\* | 1 sessão | Nenhuma — usa dados já disponíveis |
| **Fase 2** | Real Rate Parity r\* | 1 sessão | Nenhuma — paralelo à Fase 1 |
| **Fase 3** | Market-Implied r\* (ACM) | 2 sessões | Nenhuma — mais complexo, PCA + VAR |
| **Fase 4** | State-Space r\* (Kalman) | 2 sessões | Nenhuma — mais complexo, MLE + KF |
| **Fase 5** | Regime-Switching + Composição | 1 sessão | Fases 1-4 concluídas |
| **Fase 6** | Integração no FeatureEngine | 1 sessão | Fase 5 concluída |
| **Fase 7** | Backtest comparativo | 1 sessão | Fase 6 concluída |
| **Fase 8** | Dashboard UI (novo painel) | 1 sessão | Fase 7 concluída |

### 7.2 Fase 1: Fiscal-Augmented r\* (Prioridade Alta)

**Justificativa para começar aqui:** É o modelo com maior impacto marginal sobre o sistema atual, pois captura o canal fiscal que está completamente ausente. Também é o mais simples de implementar.

**Tarefas:**
1. Criar classe `FiscalAugmentedRStar` em `macro_risk_os_v2.py`
2. Carregar DIVIDA_BRUTA_PIB, PRIMARY_BALANCE, CDS_5Y, EMBI_SPREAD
3. Estimar coeficientes via rolling OLS (janela 60m)
4. Gerar série r\*_fiscal com decomposição
5. Adicionar como feature: `fiscal_rstar`, `fiscal_premium`, `Z_fiscal_rstar_gap`
6. Testes unitários

### 7.3 Fase 2: Real Rate Parity r\*

**Tarefas:**
1. Criar classe `RealRateParityRStar`
2. Carregar US_TIPS_5Y, CDS_5Y, EMBI, VIX, BOP_CURRENT, TERMS_OF_TRADE
3. Estimar country risk premium via regressão
4. Gerar série r\*_parity com decomposição global vs país
5. Adicionar features: `parity_rstar`, `country_risk_premium`, `Z_parity_gap`
6. Testes unitários

### 7.4 Fase 3: Market-Implied r\* (ACM)

**Tarefas:**
1. Criar classe `MarketImpliedRStar`
2. Construir matriz de yields DI (3M a 10Y, 8 vértices)
3. Extrair 3 fatores via PCA (level, slope, curvature)
4. Estimar VAR(1) dos fatores
5. Estimar risk prices via cross-sectional regression
6. Decompor yields em expectativas + term premium
7. Extrair r\* implícito como expectativa de longo prazo da taxa curta
8. Adicionar features: `market_rstar`, `term_premium_1y`, `term_premium_5y`, `term_premium_10y`
9. Testes unitários

### 7.5 Fase 4: State-Space r\* (Kalman Filter)

**Tarefas:**
1. Instalar `filterpy` ou implementar Kalman filter nativo
2. Criar classe `StateSpaceRStar`
3. Implementar 3-stage MLE (IS curve → trend growth → joint estimation)
4. Adicionar canal fiscal (debt/GDP, primary balance) e externo (Fed Funds, CDS)
5. Gerar r\* com bandas de confiança (90%)
6. Adicionar features: `ss_rstar`, `ss_rstar_lower`, `ss_rstar_upper`, `trend_growth`
7. Testes unitários

### 7.6 Fase 5: Composição + Regime-Switching

**Tarefas:**
1. Criar classe `CompositeEquilibriumRate`
2. Implementar regime-dependent weighting usando probabilidades HMM
3. Calcular r\*_composite com incerteza
4. Derivar SELIC\*_composite com coeficientes regime-dependentes
5. Derivar fair values da estrutura a termo (front, belly, long)
6. Substituir `_build_taylor_rule` por `_build_composite_equilibrium`
7. Manter Taylor Rule como fallback (se dados insuficientes para modelos avançados)
8. Testes unitários e de integração

### 7.7 Fase 6: Integração no FeatureEngine

**Tarefas:**
1. Substituir features `taylor_selic_star` e `taylor_gap` por versões compostas
2. Adicionar novas features: `composite_rstar`, `composite_selic_star`, `composite_gap`, `Z_composite_gap`
3. Adicionar features de decomposição: `fiscal_premium`, `term_premium_acm`, `country_risk_premium`
4. Atualizar alpha model para usar novas features
5. Atualizar dashboard output com novos campos
6. Testes de regressão

### 7.8 Fase 7: Backtest Comparativo

**Tarefas:**
1. Rodar backtest completo com Taylor Rule (baseline)
2. Rodar backtest completo com Composite Framework
3. Comparar métricas: Sharpe, max DD, hit rate, information ratio
4. Análise de atribuição: qual modelo contribui mais em cada regime
5. Sensitivity analysis: variação de pesos
6. Documentar resultados

### 7.9 Fase 8: Dashboard UI

**Tarefas:**
1. Criar novo painel "Equilibrium Rate" no dashboard
2. Mostrar r\*_composite com decomposição por modelo
3. Gráfico de séries temporais dos 5 r\* individuais
4. Gráfico de pesos regime-dependentes ao longo do tempo
5. Decomposição da curva DI: expectativas vs term premium vs fiscal premium
6. Bandas de confiança do r\*
7. Comparação Taylor Rule vs Composite (backtest)

---

## 8. Métricas de Sucesso

### 8.1 Critérios Quantitativos

| Métrica | Baseline (Taylor) | Target (Composite) | Método de Avaliação |
|---------|-------------------|--------------------|--------------------|
| Sharpe do portfólio de renda fixa | Atual | +0.15 a +0.30 | Backtest OOS 2020-2026 |
| Max Drawdown renda fixa | Atual | -10% a -20% redução | Backtest OOS |
| RMSE de previsão SELIC 6m | A medir | -20% a -30% | Rolling forecast |
| Hit rate direcional SELIC | A medir | +5pp a +10pp | Rolling forecast |
| Correlação r\* vs NTNB 5Y real yield | A medir | > 0.7 | Contemporânea |

### 8.2 Critérios Qualitativos

- O r\* composto deve reagir a eventos fiscais (PEC, reforma tributária) em 1-2 meses, não 1-2 anos
- O r\* deve subir durante crises de confiança fiscal (Joesley Day, PEC dos Precatórios) e cair durante consolidação fiscal
- O term premium ACM deve ser positivo na maior parte do tempo e subir em períodos de incerteza
- A decomposição deve ser interpretável e útil para o gestor

---

## 9. Riscos e Mitigações

| Risco | Probabilidade | Impacto | Mitigação |
|-------|--------------|---------|-----------|
| Overfitting dos modelos individuais | Média | Alto | Validação OOS rigorosa, regularização, cross-validation temporal |
| Instabilidade do Kalman filter no início da amostra | Alta | Médio | Usar 36m de warm-up, fallback para Taylor Rule |
| Dados faltantes em séries fiscais | Baixa | Médio | Interpolação + fallback para modelos que não usam fiscal |
| Complexidade computacional excessiva | Baixa | Baixo | Otimização numérica, caching de resultados intermediários |
| Regime-switching weights instáveis | Média | Médio | Smoothing exponencial dos pesos, floor de 5% por modelo |

---

## 10. Comparação com Práticas de Mercado

| Aspecto | Taylor Rule (Atual) | Composite Framework (Proposto) | Top Macro Funds |
|---------|--------------------|-----------------------------|-----------------|
| Número de modelos | 1 | 5 | 3-10+ |
| Canal fiscal | Ausente | Explícito (Modelo 3) | Sempre presente |
| Canal externo | Ausente | Explícito (Modelo 4) | Sempre presente |
| Market-implied | Ausente | ACM decomposition (Modelo 2) | Padrão da indústria |
| Regime-awareness | Ausente | HMM-integrated (Modelo 5) | Bridgewater "four box", Man AHL |
| Incerteza | Ausente | Bandas de confiança | Distribuição completa |
| Frequência de atualização | Mensal | Mensal (pode ser diária) | Diária a intraday |
| Adaptação a EM | Parcial (α, β ajustados) | Completa (fiscal, soberano, externo) | Customizada por país |

---

## 11. Referências Bibliográficas

1. Holston, K., Laubach, T., & Williams, J. C. (2023). "Measuring the Natural Rate of Interest after COVID-19." *Federal Reserve Bank of New York Staff Reports*, No. 1063.

2. Adrian, T., Crump, R. K., & Moench, E. (2013). "Pricing the Term Structure with Linear Regressions." *Journal of Financial Economics*, 110(1), 110-138.

3. Araujo, G. S., Vicente, J. V. M., & Piazza, W. (2025). "Macroeconomic Drivers of Brazil's Yield Curve." *BCB Working Paper Series*, No. 629.

4. Araujo, G. S. (2025). "Determinants of the Risk Premium in Brazilian Nominal Interest Rates." *BCB Working Paper Series*, No. 637.

5. IMF (2023). "Measuring the Stances of Monetary and Fiscal Policy." *IMF Working Paper*, WP/2023/106.

6. Tavanielli, R. & Laurini, M. (2023). "Yield Curve Models with Regime Changes: An Analysis for the Brazilian Interest Rate Market." *Mathematics*, 11(11), 2549.

7. Rachel, L. & Summers, L. H. (2019). "On Secular Stagnation in the Industrialized World." *Brookings Papers on Economic Activity*, Spring.

8. Obstfeld, M. & Taylor, A. M. (2017). "International Monetary Relations: Taking Finance Seriously." *Journal of Economic Perspectives*, 31(3), 3-28.

9. Kim, D. H. & Wright, J. H. (2005). "An Arbitrage-Free Three-Factor Term Structure Model and the Recent Behavior of Long-Term Yields and Distant-Horizon Forward Rates." *Federal Reserve Board Finance and Economics Discussion Series*, 2005-33.

10. Ang, A. & Bekaert, G. (2002). "Regime Switches in Interest Rates." *Journal of Business & Economic Statistics*, 20(2), 163-182.

---

## 12. Conclusão

O Composite Equilibrium Rate Framework representa uma evolução significativa em relação à Taylor Rule atual, alinhando o sistema com as melhores práticas dos macro hedge funds globais. A abordagem multi-modelo captura dimensões do equilíbrio de juros que estão completamente ausentes no sistema atual — particularmente o canal fiscal, o canal externo, e a informação forward-looking da curva de juros.

A implementação é viável com os dados já disponíveis no sistema (110+ séries), não requer fontes externas adicionais, e se integra nativamente com o modelo de regimes HMM existente. O impacto estimado é de +50-150bps anualizados no retorno do portfólio de renda fixa, com redução de drawdown em transições de regime monetário.

A recomendação é iniciar pela **Fase 1 (Fiscal-Augmented r\*)** por ter o maior impacto marginal e a menor complexidade de implementação, seguida pela **Fase 2 (Real Rate Parity)** e depois pelos modelos mais sofisticados (ACM e Kalman Filter).

---

*Documento preparado como parte do Macro Risk OS v3.10.5. Sujeito a revisão conforme resultados de backtest.*
