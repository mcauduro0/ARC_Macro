"""
BRLUSD Institutional FX Model Engine
=====================================
Implements all 8 blocks:
  1. PPP Structural (absolute + relative)
  2. BEER Fundamental Model
  3. Cyclical Component & Flow
  4. Macro Regime (Markov Switching)
  5. Directional Score
  6. Expected Return
  7. Risk Sizing
  8. Dashboard Outputs
"""

import pandas as pd
import numpy as np
import statsmodels.api as sm
from statsmodels.tsa.regime_switching.markov_regression import MarkovRegression
from scipy import stats
import warnings
import os
import json

warnings.filterwarnings('ignore')

DATA_DIR = "/home/ubuntu/brlusd_model/data"
OUTPUT_DIR = "/home/ubuntu/brlusd_model/output"
os.makedirs(OUTPUT_DIR, exist_ok=True)


def load_series(name):
    """Load a CSV series from data directory"""
    path = os.path.join(DATA_DIR, f"{name}.csv")
    if os.path.exists(path):
        df = pd.read_csv(path, index_col=0, parse_dates=True)
        return df.iloc[:, 0].dropna()
    return pd.Series(dtype=float)


def to_monthly(series, method='last'):
    """Convert daily series to monthly"""
    if method == 'last':
        return series.resample('MS').last().dropna()
    elif method == 'mean':
        return series.resample('MS').mean().dropna()
    return series


def z_score(series, window=120):
    """Rolling z-score normalization"""
    rolling_mean = series.rolling(window=window, min_periods=36).mean()
    rolling_std = series.rolling(window=window, min_periods=36).std()
    return (series - rolling_mean) / rolling_std


# ============================================================
# BLOCK 1: PPP STRUCTURAL
# ============================================================
class PPPModel:
    """PPP Structural Model - absolute and relative"""
    
    def __init__(self):
        self.results = {}
    
    def compute(self):
        print("=" * 60)
        print("BLOCK 1: PPP STRUCTURAL")
        print("=" * 60)
        
        # Load data
        ppp_factor = load_series('PPP_FACTOR')      # World Bank PPP (annual)
        ipca_monthly = load_series('IPCA_MONTHLY')   # IPCA monthly % change
        cpi_us = load_series('CPI_US')               # US CPI level (monthly)
        ptax = load_series('PTAX_SELL')               # PTAX BRL/USD (monthly avg)
        brlusd_daily = load_series('BRLUSD_FRED')     # Daily BRL/USD
        
        # --- 1.1 PPP Absoluta ---
        print("\n1.1 PPP Absoluta (World Bank)")
        # Interpolate annual PPP to monthly
        ppp_monthly = ppp_factor.resample('MS').interpolate(method='linear')
        
        # Get monthly spot
        spot_monthly = to_monthly(brlusd_daily)
        
        # Align
        common = ppp_monthly.index.intersection(spot_monthly.index)
        ppp_abs = ppp_monthly.loc[common]
        spot_abs = spot_monthly.loc[common]
        
        # Misalignment
        mis_ppp_abs = (spot_abs / ppp_abs) - 1
        
        print(f"  PPP abs range: {ppp_abs.min():.2f} to {ppp_abs.max():.2f}")
        print(f"  Current spot: {spot_abs.iloc[-1]:.4f}")
        print(f"  Current PPP abs: {ppp_abs.iloc[-1]:.4f}")
        print(f"  Current misalignment: {mis_ppp_abs.iloc[-1]*100:.1f}%")
        
        # --- 1.2 PPP Relativa Dinâmica ---
        print("\n1.2 PPP Relativa Dinâmica")
        
        # Build IPCA index (cumulative from base)
        ipca_idx = (1 + ipca_monthly / 100).cumprod()
        
        # CPI US is already an index
        cpi_us_monthly = cpi_us.copy()
        
        # Choose base year: 2010-01
        base_date = pd.Timestamp('2010-01-01')
        
        # Get spot at base
        spot_base = spot_monthly.loc[spot_monthly.index >= base_date].iloc[0]
        
        # Get indices at base
        ipca_base = ipca_idx.loc[ipca_idx.index >= base_date].iloc[0]
        cpi_base = cpi_us_monthly.loc[cpi_us_monthly.index >= base_date].iloc[0]
        
        # Compute PPP relative
        common_rel = ipca_idx.index.intersection(cpi_us_monthly.index).intersection(spot_monthly.index)
        common_rel = common_rel[common_rel >= base_date]
        
        ppp_rel = spot_base * (ipca_idx.loc[common_rel] / ipca_base) / (cpi_us_monthly.loc[common_rel] / cpi_base)
        spot_rel = spot_monthly.loc[common_rel]
        
        # Misalignment relative
        mis_ppp_rel = (spot_rel / ppp_rel) - 1
        
        # Z-score
        z_ppp = z_score(mis_ppp_rel, window=60)
        
        print(f"  Base date: {base_date.strftime('%Y-%m')}, Base spot: {spot_base:.4f}")
        print(f"  Current PPP rel: {ppp_rel.iloc[-1]:.4f}")
        print(f"  Current misalignment rel: {mis_ppp_rel.iloc[-1]*100:.1f}%")
        print(f"  Current Z_PPP: {z_ppp.dropna().iloc[-1]:.2f}")
        
        self.results = {
            'ppp_abs': ppp_abs,
            'ppp_rel': ppp_rel,
            'spot_monthly': spot_monthly,
            'mis_ppp_abs': mis_ppp_abs,
            'mis_ppp_rel': mis_ppp_rel,
            'z_ppp': z_ppp,
        }
        
        return self.results


# ============================================================
# BLOCK 2: BEER FUNDAMENTAL MODEL
# ============================================================
class BEERModel:
    """Behavioral Equilibrium Exchange Rate Model"""
    
    def __init__(self):
        self.results = {}
        self.coefficients = {}
    
    def compute(self, spot_monthly=None):
        print("\n" + "=" * 60)
        print("BLOCK 2: BEER FUNDAMENTAL MODEL")
        print("=" * 60)
        
        # Load data
        reer = load_series('REER_BIS')  # BIS REER (monthly)
        tot = load_series('TERMS_OF_TRADE')
        fisc = load_series('DIVIDA_BRUTA_PIB')
        selic = load_series('SELIC_TARGET')
        ust10y = to_monthly(load_series('UST10Y'), 'mean')
        cpi_us = load_series('CPI_US')
        ipca = load_series('IPCA_MONTHLY')
        bop = load_series('BOP_CURRENT_ACCOUNT')
        
        if spot_monthly is None:
            spot_monthly = to_monthly(load_series('BRLUSD_FRED'))
        
        # Convert to monthly where needed
        reer_m = to_monthly(reer, 'last')
        tot_m = to_monthly(tot, 'last')
        fisc_m = to_monthly(fisc, 'last')
        selic_m = to_monthly(selic, 'last')
        
        # --- 2.2 Compute fundamentals ---
        print("\n2.2 Computing fundamentals...")
        
        # Terms of trade (log)
        log_tot = np.log(tot_m)
        
        # Fiscal: debt/GDP
        fiscal = fisc_m
        
        # Real interest rate differential
        # Brazil real rate: SELIC - trailing 12m IPCA
        ipca_12m = ipca.rolling(12).sum()  # trailing 12m inflation
        br_real_rate = selic_m.reindex(ipca_12m.index, method='ffill') - ipca_12m
        
        # US real rate: 10Y - trailing 12m CPI change
        cpi_yoy = cpi_us.pct_change(12) * 100
        us_real_rate = ust10y.reindex(cpi_yoy.index, method='ffill') - cpi_yoy
        
        # Differential
        common_ir = br_real_rate.dropna().index.intersection(us_real_rate.dropna().index)
        rir_diff = br_real_rate.loc[common_ir] - us_real_rate.loc[common_ir]
        
        # NFA proxy: cumulative current account / GDP
        # Use BOP current account as flow proxy
        nfa_proxy = bop.rolling(12).sum()  # 12m rolling sum
        
        # --- 2.3 Econometric specification ---
        print("\n2.3 BEER Econometric estimation...")
        
        # Build panel
        y = np.log(reer_m)
        y.name = 'log_REER'
        
        X_dict = {
            'log_TOT': log_tot,
            'FISCAL': fiscal,
            'RIR_DIFF': rir_diff,
            'NFA_PROXY': nfa_proxy,
        }
        
        # Align all series
        panel = pd.DataFrame({'log_REER': y})
        for name, s in X_dict.items():
            panel[name] = s
        
        panel = panel.dropna()
        print(f"  Panel: {len(panel)} obs from {panel.index.min().strftime('%Y-%m')} to {panel.index.max().strftime('%Y-%m')}")
        
        if len(panel) < 60:
            print("  WARNING: Insufficient data for BEER estimation")
            self.results = {}
            return self.results
        
        # OLS with HAC standard errors
        y_data = panel['log_REER']
        X_data = panel[['log_TOT', 'FISCAL', 'RIR_DIFF', 'NFA_PROXY']]
        X_data = sm.add_constant(X_data)
        
        model = sm.OLS(y_data, X_data)
        results = model.fit(cov_type='HAC', cov_kwds={'maxlags': 12})
        
        print(f"\n  BEER Regression Results:")
        print(f"  R² = {results.rsquared:.4f}")
        print(f"  Adj R² = {results.rsquared_adj:.4f}")
        for var in results.params.index:
            coef = results.params[var]
            pval = results.pvalues[var]
            sig = '***' if pval < 0.01 else '**' if pval < 0.05 else '*' if pval < 0.1 else ''
            print(f"    {var:15s}: {coef:10.4f}  (p={pval:.4f}) {sig}")
        
        self.coefficients = results.params.to_dict()
        
        # --- 2.4 BEER equilibrium ---
        print("\n2.4 BEER Equilibrium Exchange Rate")
        
        # Fitted values = equilibrium REER
        reer_eq = np.exp(results.fittedvalues)
        reer_actual = np.exp(y_data)
        
        # Convert to nominal FX
        spot_aligned = spot_monthly.reindex(panel.index, method='ffill')
        reer_actual_aligned = reer_m.reindex(panel.index, method='ffill')
        
        fx_beer = spot_aligned * (reer_actual_aligned / reer_eq)
        
        # Misalignment
        mis_beer = (spot_aligned / fx_beer) - 1
        
        # Z-score
        z_beer = z_score(mis_beer, window=60)
        
        print(f"  Current REER actual: {reer_actual.iloc[-1]:.2f}")
        print(f"  Current REER equilibrium: {reer_eq.iloc[-1]:.2f}")
        print(f"  Current FX BEER: {fx_beer.iloc[-1]:.4f}")
        print(f"  Current spot: {spot_aligned.iloc[-1]:.4f}")
        print(f"  Current BEER misalignment: {mis_beer.iloc[-1]*100:.1f}%")
        print(f"  Current Z_BEER: {z_beer.dropna().iloc[-1]:.2f}")
        
        self.results = {
            'reer_eq': reer_eq,
            'reer_actual': reer_actual,
            'fx_beer': fx_beer,
            'mis_beer': mis_beer,
            'z_beer': z_beer,
            'beer_regression': results,
            'panel': panel,
        }
        
        return self.results


# ============================================================
# BLOCK 3: CYCLICAL COMPONENT
# ============================================================
class CyclicalModel:
    """Short-term cyclical factors"""
    
    def __init__(self):
        self.results = {}
        self.weights = {}
    
    def compute(self, spot_monthly=None):
        print("\n" + "=" * 60)
        print("BLOCK 3: CYCLICAL COMPONENT")
        print("=" * 60)
        
        if spot_monthly is None:
            spot_monthly = to_monthly(load_series('BRLUSD_FRED'))
        
        # Load factors
        dxy = to_monthly(load_series('DXY'), 'last')
        comm = to_monthly(load_series('BRAZIL_COMM_IDX'), 'last')
        embi = to_monthly(load_series('EMBI_SPREAD'), 'last')
        selic = load_series('SELIC_TARGET')
        ust10y = to_monthly(load_series('UST10Y'), 'mean')
        ipca = load_series('IPCA_MONTHLY')
        cpi_us = load_series('CPI_US')
        bop = load_series('BOP_CURRENT_ACCOUNT')
        
        # Compute real interest rate differential
        ipca_12m = ipca.rolling(12).sum()
        br_real = selic.reindex(ipca_12m.index, method='ffill') - ipca_12m
        cpi_yoy = cpi_us.pct_change(12) * 100
        us_real = ust10y.reindex(cpi_yoy.index, method='ffill') - cpi_yoy
        rir = br_real.reindex(us_real.index) - us_real
        
        # Flow proxy: 12m rolling current account
        flow = bop.rolling(12).sum()
        
        # Z-scores for each factor (60-month rolling)
        print("\n  Computing Z-scores for cyclical factors...")
        z_factors = {}
        
        factors = {
            'DXY': dxy,
            'COMMODITIES': comm,
            'EMBI': embi,
            'RIR': rir,
            'FLOW': flow,
        }
        
        for name, series in factors.items():
            s = series.dropna()
            if len(s) > 36:
                z = z_score(s, window=60)
                z_factors[f'Z_{name}'] = z
                last_valid = z.dropna()
                if len(last_valid) > 0:
                    print(f"    Z_{name}: {len(last_valid)} obs, last = {last_valid.iloc[-1]:.2f}")
        
        # Combine into panel and regress on FX returns to get weights
        print("\n  Calibrating cyclical weights via regression...")
        
        # FX monthly returns
        fx_ret = spot_monthly.pct_change().dropna()
        fx_ret.name = 'FX_RET'
        
        # Build factor panel
        factor_panel = pd.DataFrame(z_factors)
        factor_panel['FX_RET'] = fx_ret
        factor_panel = factor_panel.dropna()
        
        if len(factor_panel) > 60:
            y = factor_panel['FX_RET']
            X = factor_panel.drop('FX_RET', axis=1)
            X = sm.add_constant(X)
            
            reg = sm.OLS(y, X).fit(cov_type='HAC', cov_kwds={'maxlags': 6})
            
            print(f"\n  Cyclical Factor Regression:")
            print(f"  R² = {reg.rsquared:.4f}")
            for var in reg.params.index:
                if var != 'const':
                    coef = reg.params[var]
                    pval = reg.pvalues[var]
                    sig = '***' if pval < 0.01 else '**' if pval < 0.05 else '*' if pval < 0.1 else ''
                    print(f"    {var:20s}: {coef:10.6f}  (p={pval:.4f}) {sig}")
            
            # Use absolute t-stats as weights
            t_stats = reg.tvalues.drop('const').abs()
            raw_weights = t_stats / t_stats.sum()
            self.weights = raw_weights.to_dict()
        else:
            # Default weights
            self.weights = {
                'Z_DXY': 0.30,
                'Z_COMMODITIES': 0.25,
                'Z_EMBI': 0.20,
                'Z_RIR': 0.15,
                'Z_FLOW': 0.10,
            }
        
        print(f"\n  Final cyclical weights:")
        for k, v in self.weights.items():
            print(f"    {k}: {v:.3f}")
        
        # Compute composite Z_CYCLE
        z_cycle = pd.Series(0.0, index=factor_panel.index, dtype=float)
        for name, w in self.weights.items():
            if name in factor_panel.columns:
                z_cycle += factor_panel[name] * w
        
        z_cycle.name = 'Z_CYCLE'
        
        last_valid = z_cycle.dropna()
        if len(last_valid) > 0:
            print(f"\n  Z_CYCLE: last = {last_valid.iloc[-1]:.2f}")
        
        self.results = {
            'z_factors': z_factors,
            'z_cycle': z_cycle,
            'factor_panel': factor_panel,
            'weights': self.weights,
        }
        
        return self.results


# ============================================================
# BLOCK 4: MACRO REGIME (MARKOV SWITCHING)
# ============================================================
class RegimeModel:
    """Markov Switching Regime Model"""
    
    def __init__(self):
        self.results = {}
    
    def compute(self, z_cycle, spot_monthly=None):
        print("\n" + "=" * 60)
        print("BLOCK 4: MACRO REGIME (MARKOV SWITCHING)")
        print("=" * 60)
        
        if spot_monthly is None:
            spot_monthly = to_monthly(load_series('BRLUSD_FRED'))
        
        # FX returns
        fx_ret = spot_monthly.pct_change().dropna() * 100  # in percent
        
        # Align with z_cycle
        common = fx_ret.index.intersection(z_cycle.dropna().index)
        fx_ret_aligned = fx_ret.loc[common]
        z_cycle_aligned = z_cycle.loc[common]
        
        print(f"\n  Data for regime model: {len(fx_ret_aligned)} obs")
        
        # Markov Switching with 3 regimes
        print("\n  Estimating 3-regime Markov Switching model...")
        
        try:
            # Prepare data
            endog = fx_ret_aligned.values
            exog = sm.add_constant(z_cycle_aligned.values)
            
            ms_model = MarkovRegression(
                endog,
                k_regimes=3,
                exog=exog,
                switching_variance=True,
            )
            ms_results = ms_model.fit(maxiter=500, em_iter=200)
            
            print(f"\n  Markov Switching Results:")
            print(f"  Log-likelihood: {ms_results.llf:.2f}")
            
            # Regime parameters
            for i in range(3):
                print(f"\n  Regime {i}:")
                print(f"    Intercept: {ms_results.params[f'const[{i}]']:.4f}")
                print(f"    Z_CYCLE coef: {ms_results.params[f'x1[{i}]']:.4f}")
                print(f"    Sigma: {ms_results.params[f'sigma2[{i}]']:.4f}")
            
            # Smoothed probabilities
            smoothed_probs = pd.DataFrame(
                ms_results.smoothed_marginal_probabilities,
                index=common,
                columns=['P_Regime0', 'P_Regime1', 'P_Regime2']
            )
            
            # Identify regimes by volatility
            sigmas = [ms_results.params[f'sigma2[{i}]'] for i in range(3)]
            regime_order = np.argsort(sigmas)  # low vol to high vol
            
            # Rename: 0=Carry, 1=RiskOff, 2=Stress
            regime_names = {regime_order[0]: 'Carry', regime_order[1]: 'RiskOff', regime_order[2]: 'Stress'}
            
            print(f"\n  Regime identification (by volatility):")
            for idx, name in regime_names.items():
                print(f"    Regime {idx} -> {name} (sigma²={sigmas[idx]:.4f})")
            
            # Current regime probabilities
            print(f"\n  Current regime probabilities:")
            for i in range(3):
                name = regime_names.get(i, f'Regime{i}')
                prob = smoothed_probs.iloc[-1, i]
                print(f"    {name}: {prob:.1%}")
            
            # Determine dominant regime
            dominant = smoothed_probs.iloc[-1].idxmax()
            dominant_idx = int(dominant.replace('P_Regime', ''))
            dominant_name = regime_names.get(dominant_idx, 'Unknown')
            
            print(f"\n  Dominant regime: {dominant_name} ({smoothed_probs.iloc[-1, dominant_idx]:.1%})")
            
            # Lambda weights based on regime
            lambda_weights = {
                'Carry': 0.60,     # High structural weight in carry
                'RiskOff': 0.30,   # Low structural weight in risk-off
                'Stress': 0.20,    # Very low structural weight in stress
            }
            
            # Compute time-varying lambda
            lambda_t = pd.Series(0.0, index=smoothed_probs.index)
            for i in range(3):
                name = regime_names.get(i, f'Regime{i}')
                lam = lambda_weights.get(name, 0.4)
                lambda_t += smoothed_probs.iloc[:, i] * lam
            
            print(f"  Current lambda (structural weight): {lambda_t.iloc[-1]:.2f}")
            
            self.results = {
                'ms_results': ms_results,
                'smoothed_probs': smoothed_probs,
                'regime_names': regime_names,
                'lambda_t': lambda_t,
                'dominant_regime': dominant_name,
                'regime_sigmas': dict(zip(range(3), sigmas)),
            }
            
        except Exception as e:
            print(f"\n  Markov Switching FAILED: {e}")
            print("  Falling back to 2-regime model...")
            
            try:
                ms_model = MarkovRegression(
                    endog,
                    k_regimes=2,
                    exog=exog,
                    switching_variance=True,
                )
                ms_results = ms_model.fit(maxiter=500, em_iter=200)
                
                smoothed_probs = pd.DataFrame(
                    ms_results.smoothed_marginal_probabilities,
                    index=common,
                    columns=['P_Regime0', 'P_Regime1']
                )
                
                sigmas = [ms_results.params[f'sigma2[{i}]'] for i in range(2)]
                regime_order = np.argsort(sigmas)
                regime_names = {regime_order[0]: 'Carry', regime_order[1]: 'RiskOff'}
                
                print(f"\n  2-Regime Model Results:")
                for i in range(2):
                    name = regime_names.get(i, f'Regime{i}')
                    print(f"    {name}: sigma²={sigmas[i]:.4f}, prob={smoothed_probs.iloc[-1, i]:.1%}")
                
                lambda_weights = {'Carry': 0.60, 'RiskOff': 0.30}
                lambda_t = pd.Series(0.0, index=smoothed_probs.index)
                for i in range(2):
                    name = regime_names.get(i, f'Regime{i}')
                    lam = lambda_weights.get(name, 0.4)
                    lambda_t += smoothed_probs.iloc[:, i] * lam
                
                dominant_idx = smoothed_probs.iloc[-1].values.argmax()
                dominant_name = regime_names.get(dominant_idx, 'Unknown')
                
                self.results = {
                    'ms_results': ms_results,
                    'smoothed_probs': smoothed_probs,
                    'regime_names': regime_names,
                    'lambda_t': lambda_t,
                    'dominant_regime': dominant_name,
                    'regime_sigmas': dict(zip(range(2), sigmas)),
                }
                
            except Exception as e2:
                print(f"\n  2-Regime also FAILED: {e2}")
                print("  Using static regime weights")
                
                lambda_t = pd.Series(0.45, index=z_cycle.dropna().index)
                
                self.results = {
                    'smoothed_probs': pd.DataFrame({'P_Carry': 0.5, 'P_RiskOff': 0.5}, index=z_cycle.dropna().index),
                    'regime_names': {0: 'Carry', 1: 'RiskOff'},
                    'lambda_t': lambda_t,
                    'dominant_regime': 'Neutral',
                    'regime_sigmas': {},
                }
        
        return self.results


# ============================================================
# BLOCK 5: DIRECTIONAL SCORE
# ============================================================
class DirectionalScore:
    """Integrated directional score"""
    
    def __init__(self):
        self.results = {}
    
    def compute(self, z_ppp, z_beer, z_cycle, lambda_t):
        print("\n" + "=" * 60)
        print("BLOCK 5: DIRECTIONAL SCORE")
        print("=" * 60)
        
        # Structural score: 50% PPP + 50% BEER
        common = z_ppp.dropna().index.intersection(z_beer.dropna().index)
        score_struct = 0.5 * z_ppp.loc[common] + 0.5 * z_beer.loc[common]
        
        # Total score with regime-dependent weights
        common_all = common.intersection(z_cycle.dropna().index).intersection(lambda_t.dropna().index)
        
        score_total = (
            lambda_t.loc[common_all] * score_struct.loc[common_all] +
            (1 - lambda_t.loc[common_all]) * z_cycle.loc[common_all]
        )
        
        print(f"\n  Score components (latest):")
        print(f"    Z_PPP:          {z_ppp.dropna().iloc[-1]:.2f}")
        print(f"    Z_BEER:         {z_beer.dropna().iloc[-1]:.2f}")
        print(f"    Score_struct:    {score_struct.iloc[-1]:.2f}")
        print(f"    Z_CYCLE:        {z_cycle.dropna().iloc[-1]:.2f}")
        print(f"    Lambda:         {lambda_t.iloc[-1]:.2f}")
        print(f"    Score_total:    {score_total.iloc[-1]:.2f}")
        
        # Interpretation
        st = score_total.iloc[-1]
        if st > 1:
            interp = "BRL estruturalmente e ciclicamente DEPRECIADO. Probabilidade maior de apreciação."
        elif st > 0.5:
            interp = "BRL moderadamente depreciado. Viés de apreciação."
        elif st > -0.5:
            interp = "BRL próximo do equilíbrio. Sem sinal direcional forte."
        elif st > -1:
            interp = "BRL moderadamente sobrevalorizado. Viés de depreciação."
        else:
            interp = "BRL SOBREVALORIZADO. Probabilidade maior de depreciação."
        
        print(f"\n  Interpretação: {interp}")
        
        self.results = {
            'score_struct': score_struct,
            'score_total': score_total,
            'interpretation': interp,
        }
        
        return self.results


# ============================================================
# BLOCK 6: EXPECTED RETURN
# ============================================================
class ExpectedReturn:
    """Convert score to expected return"""
    
    def __init__(self):
        self.results = {}
    
    def compute(self, score_total, spot_monthly=None):
        print("\n" + "=" * 60)
        print("BLOCK 6: EXPECTED RETURN")
        print("=" * 60)
        
        if spot_monthly is None:
            spot_monthly = to_monthly(load_series('BRLUSD_FRED'))
        
        # Forward returns
        fx_ret_3m = spot_monthly.pct_change(3).shift(-3)  # 3-month forward return
        fx_ret_6m = spot_monthly.pct_change(6).shift(-6)  # 6-month forward return
        
        # Align
        common = score_total.dropna().index.intersection(fx_ret_6m.dropna().index)
        
        if len(common) < 36:
            print("  Insufficient data for return regression")
            self.results = {}
            return self.results
        
        # 6-month regression
        y_6m = fx_ret_6m.loc[common]
        X_6m = sm.add_constant(score_total.loc[common])
        
        reg_6m = sm.OLS(y_6m, X_6m).fit(cov_type='HAC', cov_kwds={'maxlags': 6})
        
        print(f"\n  6-Month Forward Return Regression:")
        print(f"  R² = {reg_6m.rsquared:.4f}")
        print(f"  Alpha: {reg_6m.params.iloc[0]:.4f} (p={reg_6m.pvalues.iloc[0]:.4f})")
        print(f"  Delta: {reg_6m.params.iloc[1]:.4f} (p={reg_6m.pvalues.iloc[1]:.4f})")
        
        # 3-month regression
        common_3m = score_total.dropna().index.intersection(fx_ret_3m.dropna().index)
        y_3m = fx_ret_3m.loc[common_3m]
        X_3m = sm.add_constant(score_total.loc[common_3m])
        
        reg_3m = sm.OLS(y_3m, X_3m).fit(cov_type='HAC', cov_kwds={'maxlags': 3})
        
        print(f"\n  3-Month Forward Return Regression:")
        print(f"  R² = {reg_3m.rsquared:.4f}")
        print(f"  Alpha: {reg_3m.params.iloc[0]:.4f} (p={reg_3m.pvalues.iloc[0]:.4f})")
        print(f"  Delta: {reg_3m.params.iloc[1]:.4f} (p={reg_3m.pvalues.iloc[1]:.4f})")
        
        # Current expected returns
        current_score = score_total.iloc[-1]
        exp_ret_3m = reg_3m.params.iloc[0] + reg_3m.params.iloc[1] * current_score
        exp_ret_6m = reg_6m.params.iloc[0] + reg_6m.params.iloc[1] * current_score
        
        print(f"\n  Current Score: {current_score:.2f}")
        print(f"  Expected Return 3m: {exp_ret_3m*100:.2f}%")
        print(f"  Expected Return 6m: {exp_ret_6m*100:.2f}%")
        
        self.results = {
            'reg_3m': reg_3m,
            'reg_6m': reg_6m,
            'exp_ret_3m': exp_ret_3m,
            'exp_ret_6m': exp_ret_6m,
            'delta_3m': reg_3m.params.iloc[1],
            'delta_6m': reg_6m.params.iloc[1],
        }
        
        return self.results


# ============================================================
# BLOCK 7: RISK SIZING
# ============================================================
class RiskSizing:
    """Position sizing based on expected return and volatility"""
    
    def __init__(self, vol_target=0.10, max_position=2.0):
        self.vol_target = vol_target
        self.max_position = max_position
        self.results = {}
    
    def compute(self, exp_ret_3m, exp_ret_6m, spot_monthly=None):
        print("\n" + "=" * 60)
        print("BLOCK 7: RISK SIZING")
        print("=" * 60)
        
        if spot_monthly is None:
            spot_monthly = to_monthly(load_series('BRLUSD_FRED'))
        
        # Daily returns for vol estimation
        brlusd_daily = load_series('BRLUSD_FRED')
        daily_ret = brlusd_daily.pct_change().dropna()
        
        # Rolling 60-day annualized vol
        vol_60d = daily_ret.rolling(60).std() * np.sqrt(252)
        current_vol = vol_60d.iloc[-1]
        
        print(f"\n  Current 60d annualized vol: {current_vol*100:.1f}%")
        print(f"  Vol target: {self.vol_target*100:.1f}%")
        
        # Kelly-fractional sizing
        # Full Kelly: w = mu / sigma^2
        # Half Kelly: w = 0.5 * mu / sigma^2
        
        # Annualize expected returns
        exp_ret_6m_ann = exp_ret_6m * 2  # rough annualization
        exp_ret_3m_ann = exp_ret_3m * 4
        
        # Half-Kelly
        kelly_6m = 0.5 * exp_ret_6m_ann / (current_vol ** 2) if current_vol > 0 else 0
        kelly_3m = 0.5 * exp_ret_3m_ann / (current_vol ** 2) if current_vol > 0 else 0
        
        # Target vol sizing
        tv_6m = (exp_ret_6m_ann / current_vol) * (self.vol_target / current_vol) if current_vol > 0 else 0
        tv_3m = (exp_ret_3m_ann / current_vol) * (self.vol_target / current_vol) if current_vol > 0 else 0
        
        # Simple sizing: Expected return / vol * risk adjustment
        simple_6m = exp_ret_6m_ann / current_vol if current_vol > 0 else 0
        simple_3m = exp_ret_3m_ann / current_vol if current_vol > 0 else 0
        
        # Cap positions
        kelly_6m = np.clip(kelly_6m, -self.max_position, self.max_position)
        kelly_3m = np.clip(kelly_3m, -self.max_position, self.max_position)
        simple_6m = np.clip(simple_6m, -self.max_position, self.max_position)
        simple_3m = np.clip(simple_3m, -self.max_position, self.max_position)
        
        print(f"\n  Position Sizing (6m horizon):")
        print(f"    Half-Kelly:    {kelly_6m:+.2f}x")
        print(f"    Sharpe-based:  {simple_6m:+.2f}x")
        print(f"    Max position:  ±{self.max_position:.1f}x")
        
        print(f"\n  Position Sizing (3m horizon):")
        print(f"    Half-Kelly:    {kelly_3m:+.2f}x")
        print(f"    Sharpe-based:  {simple_3m:+.2f}x")
        
        # Recommended position (average of methods)
        rec_6m = (kelly_6m + simple_6m) / 2
        rec_3m = (kelly_3m + simple_3m) / 2
        
        print(f"\n  Recommended position:")
        print(f"    3m: {rec_3m:+.2f}x")
        print(f"    6m: {rec_6m:+.2f}x")
        
        # Direction interpretation
        if rec_6m > 0.1:
            direction = "LONG BRL (SHORT USD)"
        elif rec_6m < -0.1:
            direction = "SHORT BRL (LONG USD)"
        else:
            direction = "NEUTRAL"
        
        print(f"    Direction: {direction}")
        
        # Historical vol series
        vol_monthly = to_monthly(vol_60d, 'last')
        
        self.results = {
            'current_vol': current_vol,
            'vol_monthly': vol_monthly,
            'kelly_6m': kelly_6m,
            'kelly_3m': kelly_3m,
            'simple_6m': simple_6m,
            'simple_3m': simple_3m,
            'recommended_6m': rec_6m,
            'recommended_3m': rec_3m,
            'direction': direction,
        }
        
        return self.results


# ============================================================
# MAIN MODEL RUNNER
# ============================================================
def run_full_model():
    """Run the complete BRLUSD model"""
    print("=" * 60)
    print("BRLUSD INSTITUTIONAL FX MODEL")
    print(f"Run date: {pd.Timestamp.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 60)
    
    # Spot data
    spot_monthly = to_monthly(load_series('BRLUSD_FRED'))
    
    # Block 1: PPP
    ppp = PPPModel()
    ppp_results = ppp.compute()
    
    # Block 2: BEER
    beer = BEERModel()
    beer_results = beer.compute(spot_monthly)
    
    # Block 3: Cyclical
    cyclical = CyclicalModel()
    cyc_results = cyclical.compute(spot_monthly)
    
    # Block 4: Regime
    regime = RegimeModel()
    reg_results = regime.compute(cyc_results['z_cycle'], spot_monthly)
    
    # Block 5: Directional Score
    scorer = DirectionalScore()
    score_results = scorer.compute(
        ppp_results['z_ppp'],
        beer_results['z_beer'],
        cyc_results['z_cycle'],
        reg_results['lambda_t']
    )
    
    # Block 6: Expected Return
    exp_ret = ExpectedReturn()
    ret_results = exp_ret.compute(score_results['score_total'], spot_monthly)
    
    # Block 7: Risk Sizing
    sizer = RiskSizing(vol_target=0.10, max_position=2.0)
    size_results = sizer.compute(
        ret_results.get('exp_ret_3m', 0),
        ret_results.get('exp_ret_6m', 0),
        spot_monthly
    )
    
    # ============================================================
    # COMPILE DASHBOARD OUTPUT
    # ============================================================
    print("\n" + "=" * 60)
    print("BLOCK 8: DASHBOARD OUTPUT SUMMARY")
    print("=" * 60)
    
    current_spot = spot_monthly.iloc[-1]
    
    dashboard = {
        'run_date': pd.Timestamp.now().strftime('%Y-%m-%d'),
        'current_spot': round(current_spot, 4),
        
        # PPP
        'ppp_abs_fair_value': round(ppp_results['ppp_abs'].iloc[-1], 4),
        'ppp_rel_fair_value': round(ppp_results['ppp_rel'].iloc[-1], 4),
        'ppp_abs_misalignment_pct': round(ppp_results['mis_ppp_abs'].iloc[-1] * 100, 1),
        'ppp_rel_misalignment_pct': round(ppp_results['mis_ppp_rel'].iloc[-1] * 100, 1),
        'z_ppp': round(ppp_results['z_ppp'].dropna().iloc[-1], 2),
        
        # BEER
        'beer_fair_value': round(beer_results['fx_beer'].iloc[-1], 4),
        'beer_misalignment_pct': round(beer_results['mis_beer'].iloc[-1] * 100, 1),
        'z_beer': round(beer_results['z_beer'].dropna().iloc[-1], 2),
        
        # Cyclical
        'z_cycle': round(cyc_results['z_cycle'].iloc[-1], 2),
        'cyclical_weights': cyclical.weights,
        
        # Regime
        'dominant_regime': reg_results['dominant_regime'],
        'regime_probs': {reg_results['regime_names'].get(i, f'R{i}'): round(float(reg_results['smoothed_probs'].iloc[-1, i]), 3) for i in range(len(reg_results['smoothed_probs'].columns))},
        'lambda_structural': round(float(reg_results['lambda_t'].iloc[-1]), 2),
        
        # Score
        'score_structural': round(float(score_results['score_struct'].iloc[-1]), 2),
        'score_total': round(float(score_results['score_total'].iloc[-1]), 2),
        'interpretation': score_results['interpretation'],
        
        # Expected Return
        'expected_return_3m_pct': round(ret_results.get('exp_ret_3m', 0) * 100, 2),
        'expected_return_6m_pct': round(ret_results.get('exp_ret_6m', 0) * 100, 2),
        
        # Risk Sizing
        'current_vol_ann_pct': round(size_results['current_vol'] * 100, 1),
        'recommended_position_3m': round(size_results['recommended_3m'], 2),
        'recommended_position_6m': round(size_results['recommended_6m'], 2),
        'direction': size_results['direction'],
    }
    
    # Print summary
    print(f"\n  {'='*50}")
    print(f"  BRLUSD MODEL SUMMARY")
    print(f"  {'='*50}")
    print(f"  Spot BRL/USD:           {dashboard['current_spot']}")
    print(f"  PPP Abs Fair Value:     {dashboard['ppp_abs_fair_value']}")
    print(f"  PPP Rel Fair Value:     {dashboard['ppp_rel_fair_value']}")
    print(f"  BEER Fair Value:        {dashboard['beer_fair_value']}")
    print(f"  PPP Misalignment:       {dashboard['ppp_abs_misalignment_pct']:+.1f}%")
    print(f"  BEER Misalignment:      {dashboard['beer_misalignment_pct']:+.1f}%")
    print(f"  Z_PPP:                  {dashboard['z_ppp']:+.2f}")
    print(f"  Z_BEER:                 {dashboard['z_beer']:+.2f}")
    print(f"  Z_CYCLE:                {dashboard['z_cycle']:+.2f}")
    print(f"  Dominant Regime:        {dashboard['dominant_regime']}")
    print(f"  Lambda (struct weight): {dashboard['lambda_structural']}")
    print(f"  Score Structural:       {dashboard['score_structural']:+.2f}")
    print(f"  Score Total:            {dashboard['score_total']:+.2f}")
    print(f"  Expected Return 3m:     {dashboard['expected_return_3m_pct']:+.2f}%")
    print(f"  Expected Return 6m:     {dashboard['expected_return_6m_pct']:+.2f}%")
    print(f"  Vol Anualizada:         {dashboard['current_vol_ann_pct']:.1f}%")
    print(f"  Posição Recomendada 6m: {dashboard['recommended_position_6m']:+.2f}x")
    print(f"  Direção:                {dashboard['direction']}")
    print(f"  Interpretação:          {dashboard['interpretation']}")
    
    # Save dashboard JSON
    with open(os.path.join(OUTPUT_DIR, 'dashboard.json'), 'w') as f:
        json.dump(dashboard, f, indent=2, default=str)
    
    # Save time series for charts
    ts_output = pd.DataFrame({
        'spot': spot_monthly,
        'ppp_abs': ppp_results['ppp_abs'],
        'ppp_rel': ppp_results['ppp_rel'],
        'fx_beer': beer_results['fx_beer'],
        'mis_ppp_abs': ppp_results['mis_ppp_abs'],
        'mis_beer': beer_results['mis_beer'],
        'z_ppp': ppp_results['z_ppp'],
        'z_beer': beer_results['z_beer'],
        'z_cycle': cyc_results['z_cycle'],
        'score_struct': score_results['score_struct'],
        'score_total': score_results['score_total'],
    })
    ts_output.to_csv(os.path.join(OUTPUT_DIR, 'model_timeseries.csv'))
    
    # Save regime probabilities
    reg_results['smoothed_probs'].to_csv(os.path.join(OUTPUT_DIR, 'regime_probs.csv'))
    
    # Save volatility
    if 'vol_monthly' in size_results:
        size_results['vol_monthly'].to_csv(os.path.join(OUTPUT_DIR, 'volatility.csv'))
    
    # Save cyclical factors
    pd.DataFrame(cyc_results['z_factors']).to_csv(os.path.join(OUTPUT_DIR, 'cyclical_factors.csv'))
    
    print(f"\n  All outputs saved to {OUTPUT_DIR}")
    
    return dashboard, {
        'ppp': ppp_results,
        'beer': beer_results,
        'cyclical': cyc_results,
        'regime': reg_results,
        'score': score_results,
        'expected_return': ret_results,
        'sizing': size_results,
    }


if __name__ == '__main__':
    dashboard, all_results = run_full_model()
