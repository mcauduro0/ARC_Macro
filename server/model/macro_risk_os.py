"""
MACRO RISK OS
=============
Module: FX + Rates + Sovereign Integration Engine

Generates daily:
- Expected return for: FX (BRLUSD), Juros front/belly/long, NTN-B, Soberano hard currency
- Decomposition by common factors
- Optimal sizing by marginal risk (DV01, delta, spread DV01)
- Explicit control of: macro regime, factor limits, target vol

Architecture:
1. Data loading & preprocessing
2. Unified state variables (X1-X7) with rolling 5Y Z-scores
3. Expected return models per asset class
4. 3-state Markov Switching regime
5. Cross-asset fair value
6. Sizing engine (Sharpe, Kelly, factor limits)
7. Risk aggregation (covariance, stress tests)
8. Dashboard output
"""

import sys
import os
import json
import pandas as pd
import numpy as np
import statsmodels.api as sm
from statsmodels.tsa.regime_switching.markov_regression import MarkovRegression
from scipy import stats
import warnings
warnings.filterwarnings('ignore')

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")
os.makedirs(OUTPUT_DIR, exist_ok=True)


def log(msg):
    print(msg, file=sys.stderr)


# ============================================================
# UTILITIES
# ============================================================

def load_series(name):
    """Load a CSV series from data directory"""
    path = os.path.join(DATA_DIR, f"{name}.csv")
    if os.path.exists(path):
        df = pd.read_csv(path, index_col=0, parse_dates=True)
        return df.iloc[:, 0].dropna()
    return pd.Series(dtype=float)


def to_monthly(series, method='last'):
    """Convert daily series to monthly"""
    if len(series) == 0:
        return series
    if method == 'last':
        return series.resample('MS').last().dropna()
    elif method == 'mean':
        return series.resample('MS').mean().dropna()
    return series


def winsorize(series, lower=0.05, upper=0.95):
    """Winsorize series at 5%-95% to control outliers"""
    if len(series) < 10:
        return series
    lo = series.quantile(lower)
    hi = series.quantile(upper)
    return series.clip(lo, hi)


def z_score_rolling(series, window=60, min_periods=36):
    """Rolling Z-score with 5-year window (60 months)"""
    if len(series) < min_periods:
        return pd.Series(np.nan, index=series.index)
    rolling_mean = series.rolling(window=window, min_periods=min_periods).mean()
    rolling_std = series.rolling(window=window, min_periods=min_periods).std()
    z = (series - rolling_mean) / rolling_std
    return winsorize(z, 0.05, 0.95)


def safe_div(a, b, default=0):
    """Safe division"""
    return a / b if b != 0 else default


# ============================================================
# 1. DATA LOADING & PREPROCESSING
# ============================================================

class DataLoader:
    """Load and preprocess all market and macro data into monthly frequency"""
    
    def __init__(self):
        self.data = {}
    
    def load_all(self):
        log("=" * 60)
        log("MACRO RISK OS: Loading Data")
        log("=" * 60)
        
        # --- market_fx ---
        brlusd = load_series('USDBRL')
        if len(brlusd) == 0:
            brlusd = load_series('BRLUSD_YF')
        if len(brlusd) == 0:
            brlusd = load_series('PTAX')
        self.data['spot_brlusd'] = to_monthly(brlusd)
        self.data['spot_brlusd_daily'] = brlusd
        
        dxy = load_series('DXY_YF')
        if len(dxy) == 0:
            dxy = load_series('DXY')
        if len(dxy) == 0:
            dxy = load_series('DXY_FRED')
        self.data['dxy'] = to_monthly(dxy)
        
        # FX forwards proxy via cupom cambial
        self.data['fx_cupom_1m'] = load_series('FX_CUPOM_1M')
        self.data['fx_cupom_3m'] = load_series('FX_CUPOM_3M')
        self.data['fx_cupom_12m'] = load_series('FX_CUPOM_12M')
        
        # FX vol
        fx_vol = load_series('FX_VOL_BRL')
        if len(fx_vol) == 0:
            # Compute realized vol from daily returns as proxy
            if len(brlusd) > 60:
                daily_ret = np.log(brlusd / brlusd.shift(1)).dropna()
                fx_vol = daily_ret.rolling(21).std() * np.sqrt(252) * 100
        self.data['fx_vol_1m'] = to_monthly(fx_vol) if len(fx_vol) > 0 else pd.Series(dtype=float)
        
        # --- market_rates_local (yields in % a.a.) ---
        # DI yield curve from Trading Economics (CORRECT YIELDS)
        di_1y = load_series('DI_1Y')  # Trading Economics GEBR1Y:IND
        if len(di_1y) == 0:
            di_1y = load_series('DI_YIELD_1Y')  # BCB 4189 fallback
        if len(di_1y) == 0:
            di_1y = load_series('SELIC_OVER')  # Last resort
        self.data['di_1y'] = di_1y
        
        di_2y = load_series('DI_2Y')  # Trading Economics GEBR2Y:IND
        if len(di_2y) == 0:
            di_2y = load_series('DI_YIELD_2Y_IPEA')
        self.data['di_2y'] = di_2y
        
        di_3y = load_series('DI_3Y')  # Trading Economics GEBR3Y:IND
        self.data['di_3y'] = di_3y
        
        di_5y = load_series('DI_5Y')  # Trading Economics GEBR5Y:IND
        if len(di_5y) == 0:
            di_5y = load_series('DI_YIELD_5Y_IPEA')
        self.data['di_5y'] = di_5y
        
        di_10y = load_series('DI_10Y')  # Trading Economics GEBR10Y:IND
        if len(di_10y) == 0:
            di_10y = di_5y  # Fallback to 5Y if 10Y unavailable
        self.data['di_10y'] = di_10y
        
        # NTN-B real yields
        ntnb_5y = load_series('NTNB_YIELD_5Y_IPEA')
        if len(ntnb_5y) == 0:
            ntnb_5y = load_series('NTNB_5Y')
        self.data['ntnb_5y'] = ntnb_5y
        
        ntnb_10y = load_series('NTNB_YIELD_10Y_IPEA')
        if len(ntnb_10y) == 0:
            ntnb_10y = load_series('NTNB_10Y')
        self.data['ntnb_10y'] = ntnb_10y
        
        # DI short tenors
        di_3m = load_series('DI_3M')  # Trading Economics GEBR3M:IND
        self.data['di_3m'] = di_3m
        di_6m = load_series('DI_6M')  # Trading Economics GEBR6M:IND
        self.data['di_6m'] = di_6m
        
        # SELIC
        selic = load_series('SELIC_META')
        if len(selic) == 0:
            selic = load_series('SELIC_TARGET')
        self.data['selic_target'] = selic
        
        # --- market_rates_us ---
        self.data['ust_2y'] = load_series('UST_2Y')
        self.data['ust_5y'] = load_series('UST_5Y')
        self.data['ust_10y'] = load_series('UST_10Y')
        self.data['ust_30y'] = load_series('UST_30Y')
        fed = load_series('FED_FUNDS')
        if len(fed) == 0:
            fed = load_series('FED_FUNDS_EFFECTIVE')
        self.data['fed_funds'] = fed
        self.data['us_tips_5y'] = load_series('US_TIPS_5Y')
        self.data['us_tips_10y'] = load_series('US_TIPS_10Y')
        
        # --- market_credit ---
        embi = load_series('EMBI_SPREAD')
        if len(embi) == 0:
            embi = load_series('EMBI_PLUS')
        if len(embi) == 0:
            embi = load_series('EMBI_PLUS_IPEA')
        if len(embi) == 0:
            embi = load_series('EMBI_PLUS_RISCO')
        self.data['embi_spread'] = embi
        cds = load_series('CDS_5Y')
        if len(cds) == 0:
            cds = load_series('CDS_5Y_BCB')
        if len(cds) == 0:
            cds = load_series('CDS_5Y_BRAZIL')
        self.data['cds_5y'] = cds
        
        # --- macro_local ---
        self.data['ipca_monthly'] = load_series('IPCA_MONTHLY')
        self.data['ipca_exp_12m'] = load_series('IPCA_EXP_12M')
        if len(self.data['ipca_exp_12m']) == 0:
            self.data['ipca_exp_12m'] = load_series('IPCA_EXP_FOCUS')
        self.data['debt_gdp'] = load_series('DIVIDA_BRUTA_PIB')
        ca = load_series('BOP_CURRENT')
        if len(ca) == 0:
            ca = load_series('BOP_CURRENT_ACCOUNT')
        self.data['current_account'] = ca
        self.data['terms_of_trade'] = load_series('TERMS_OF_TRADE')
        self.data['comm_idx'] = load_series('BRAZIL_COMM_IDX')
        self.data['primary_balance'] = load_series('PRIMARY_BALANCE')
        self.data['ibc_br'] = load_series('IBC_BR')
        
        # --- macro_global ---
        self.data['cpi_us'] = load_series('CPI_US')
        self.data['us_breakeven_10y'] = load_series('US_BREAKEVEN_10Y')
        vix = load_series('VIX')
        if len(vix) == 0:
            vix = load_series('VIX_YF')
        self.data['vix'] = vix
        self.data['nfci'] = load_series('NFCI')
        fci = load_series('FCI_STLFSI')
        if len(fci) == 0:
            fci = load_series('NFCI')
        self.data['fci'] = fci
        us_exp = load_series('US_CPI_EXP')
        if len(us_exp) == 0:
            us_exp = load_series('US_CPI_EXP_MICHIGAN')
        self.data['us_cpi_exp'] = us_exp
        
        # --- structural ---
        self.data['ppp_factor'] = load_series('PPP_FACTOR')
        reer = load_series('REER_BIS')
        if len(reer) == 0:
            reer = load_series('REER')
        self.data['reer'] = reer
        
        # Convert all to monthly where needed
        for key in list(self.data.keys()):
            s = self.data[key]
            if len(s) > 0 and key != 'spot_brlusd_daily':
                freq = pd.infer_freq(s.index[:20]) if len(s) >= 20 else None
                if freq and freq.startswith('B') or freq == 'D':
                    self.data[key] = to_monthly(s)
        
        # Compute derived series
        self._compute_derived()
        
        log(f"\n[DATA] Loaded {sum(1 for v in self.data.values() if len(v) > 0)} series")
        return self.data
    
    def _validate_scales(self):
        """Validate and fix data scales - ensure yields are in % a.a."""
        log('\n  Validating data scales...')
        
        # DI yields should be in range 2-50% for Brazil
        for key in ['di_1y', 'di_2y', 'di_3y', 'di_5y', 'di_10y']:
            s = self.data.get(key, pd.Series(dtype=float))
            if len(s) > 0:
                median = s.median()
                if median > 1000:  # Likely PU (preço unitário), not yield
                    log(f'  [FIX] {key}: median={median:.0f} -> likely PU, skipping (not yield)')
                    self.data[key] = pd.Series(dtype=float)  # Clear bad data
                elif median > 50:  # Might be in bps
                    log(f'  [FIX] {key}: median={median:.2f} -> converting from bps to %')
                    self.data[key] = s / 100
                else:
                    log(f'  [OK] {key}: median={median:.2f}% (valid yield range)')
        
        # NTN-B yields should be in range 2-15%
        for key in ['ntnb_5y', 'ntnb_10y']:
            s = self.data.get(key, pd.Series(dtype=float))
            if len(s) > 0:
                median = s.median()
                if median > 100:  # Likely PU
                    log(f'  [FIX] {key}: median={median:.0f} -> likely PU, skipping')
                    self.data[key] = pd.Series(dtype=float)
                else:
                    log(f'  [OK] {key}: median={median:.2f}% (valid yield range)')
        
        # EMBI spread should be in bps (100-1000 typical)
        embi = self.data.get('embi_spread', pd.Series(dtype=float))
        if len(embi) > 0:
            median = embi.median()
            if median > 5000:  # Likely cumulative index, not spread
                log(f'  [FIX] embi_spread: median={median:.0f} -> likely cumulative index')
                # Try to compute spread from changes or use as-is with normalization
                # For now, compute daily changes as proxy
                embi_diff = embi.diff().dropna()
                if embi_diff.std() < 100:  # Reasonable daily change
                    self.data['embi_spread'] = embi_diff.cumsum() + 200  # Rebase
                    log(f'  [FIX] Rebased EMBI from cumulative index')
                else:
                    self.data['embi_spread'] = pd.Series(dtype=float)
            elif median < 10:  # Might be in % instead of bps
                log(f'  [FIX] embi_spread: median={median:.2f} -> converting from % to bps')
                self.data['embi_spread'] = embi * 100
            else:
                log(f'  [OK] embi_spread: median={median:.0f} bps')
        
        # SELIC should be in % a.a. (2-15% typical)
        selic = self.data.get('selic_target', pd.Series(dtype=float))
        if len(selic) > 0:
            median = selic.median()
            if median < 0.5:  # Likely daily rate
                log(f'  [FIX] selic_target: median={median:.4f} -> converting daily to annual')
                self.data['selic_target'] = ((1 + selic / 100) ** 252 - 1) * 100
            else:
                log(f'  [OK] selic_target: median={median:.2f}%')
    
    def _compute_derived(self):
        """Compute derived series: IPCA YoY, breakevens, output gap, etc."""
        
        # IPCA YoY from monthly changes
        ipca_m = self.data['ipca_monthly']
        if len(ipca_m) > 12:
            ipca_idx = (1 + ipca_m / 100).cumprod()
            self.data['ipca_yoy'] = (ipca_idx / ipca_idx.shift(12) - 1) * 100
        else:
            self.data['ipca_yoy'] = pd.Series(dtype=float)
        
        # US CPI YoY
        cpi = self.data['cpi_us']
        if len(cpi) > 12:
            cpi_m = to_monthly(cpi)
            self.data['us_cpi_yoy'] = (cpi_m / cpi_m.shift(12) - 1) * 100
        else:
            self.data['us_cpi_yoy'] = pd.Series(dtype=float)
        
        # Validate and fix data scales
        self._validate_scales()
        
        # Breakeven inflation = DI nominal - NTN-B real (only if both in % a.a.)
        di5 = self.data['di_5y']
        ntnb5 = self.data['ntnb_5y']
        if len(di5) > 0 and len(ntnb5) > 0:
            # Only compute breakeven if both are in reasonable yield range (0-50%)
            if di5.median() < 50 and ntnb5.median() < 50:
                common = di5.index.intersection(ntnb5.index)
                self.data['breakeven_5y'] = di5.loc[common] - ntnb5.loc[common]
            else:
                log('  [WARN] Skipping breakeven_5y: data not in yield % format')
                self.data['breakeven_5y'] = pd.Series(dtype=float)
        else:
            self.data['breakeven_5y'] = pd.Series(dtype=float)
        
        di10 = self.data['di_10y']
        ntnb10 = self.data['ntnb_10y']
        if len(di10) > 0 and len(ntnb10) > 0:
            if di10.median() < 50 and ntnb10.median() < 50:
                common = di10.index.intersection(ntnb10.index)
                self.data['breakeven_10y'] = di10.loc[common] - ntnb10.loc[common]
            else:
                log('  [WARN] Skipping breakeven_10y: data not in yield % format')
                self.data['breakeven_10y'] = pd.Series(dtype=float)
        else:
            self.data['breakeven_10y'] = pd.Series(dtype=float)
        
        # Output gap proxy from IBC-Br (HP filter)
        ibc = self.data['ibc_br']
        if len(ibc) > 36:
            try:
                ibc_log = np.log(ibc.dropna())
                cycle, trend = sm.tsa.filters.hpfilter(ibc_log, lamb=14400)
                self.data['output_gap'] = cycle * 100  # in percentage
            except:
                self.data['output_gap'] = pd.Series(dtype=float)
        else:
            self.data['output_gap'] = pd.Series(dtype=float)
        
        # US real rate = UST 10Y - US breakeven 10Y
        ust10 = self.data['ust_10y']
        us_be = self.data['us_breakeven_10y']
        if len(ust10) > 0 and len(us_be) > 0:
            ust10_m = to_monthly(ust10)
            us_be_m = to_monthly(us_be)
            common = ust10_m.index.intersection(us_be_m.index)
            self.data['us_real_rate'] = ust10_m.loc[common] - us_be_m.loc[common]
        else:
            self.data['us_real_rate'] = pd.Series(dtype=float)
        
        # Financial conditions index (prefer NFCI, fallback to STLFSI)
        if len(self.data['nfci']) > 0:
            self.data['fci_combined'] = self.data['nfci']
        elif len(self.data['fci']) > 0:
            self.data['fci_combined'] = self.data['fci']
        else:
            self.data['fci_combined'] = pd.Series(dtype=float)


# ============================================================
# 2. UNIFIED STATE VARIABLES
# ============================================================

class StateVariables:
    """Compute unified state vector X_t with rolling 5Y Z-scores"""
    
    def __init__(self, data):
        self.data = data
        self.states = {}
        self.z_states = {}
    
    def compute(self):
        log("\n" + "=" * 60)
        log("STATE VARIABLES: Computing X1-X7")
        log("=" * 60)
        
        # X1: diferencial_real = (DI_1y - IPCA_exp) - (UST_2y - US_CPI_exp)
        di1y = self.data.get('di_1y', pd.Series(dtype=float))
        ipca_exp = self.data.get('ipca_exp_12m', pd.Series(dtype=float))
        ust2y = self.data.get('ust_2y', pd.Series(dtype=float))
        us_cpi_exp = self.data.get('us_cpi_exp', pd.Series(dtype=float))
        
        if len(di1y) > 0 and len(ipca_exp) > 0:
            di1y_m = to_monthly(di1y) if pd.infer_freq(di1y.index[:10]) not in [None, 'MS'] else di1y
            ipca_exp_m = to_monthly(ipca_exp) if len(ipca_exp) > 0 else ipca_exp
            common = di1y_m.index.intersection(ipca_exp_m.index)
            br_real = di1y_m.loc[common] - ipca_exp_m.loc[common]
            
            if len(ust2y) > 0 and len(us_cpi_exp) > 0:
                ust2y_m = to_monthly(ust2y)
                us_exp_m = to_monthly(us_cpi_exp)
                common2 = br_real.index.intersection(ust2y_m.index).intersection(us_exp_m.index)
                us_real = ust2y_m.loc[common2] - us_exp_m.loc[common2]
                self.states['X1_diferencial_real'] = br_real.loc[common2] - us_real
            else:
                # Fallback: use BR real rate alone
                self.states['X1_diferencial_real'] = br_real
        else:
            self.states['X1_diferencial_real'] = pd.Series(dtype=float)
        
        # X2: surpresa_inflacao = IPCA_yoy - IPCA_exp_12m
        ipca_yoy = self.data.get('ipca_yoy', pd.Series(dtype=float))
        if len(ipca_yoy) > 0 and len(ipca_exp) > 0:
            ipca_exp_m = to_monthly(ipca_exp)
            common = ipca_yoy.index.intersection(ipca_exp_m.index)
            self.states['X2_surpresa_inflacao'] = ipca_yoy.loc[common] - ipca_exp_m.loc[common]
        else:
            self.states['X2_surpresa_inflacao'] = pd.Series(dtype=float)
        
        # X3: fiscal_risk = zscore(debt_gdp) + zscore(cds_5y)
        debt = self.data.get('debt_gdp', pd.Series(dtype=float))
        cds = self.data.get('cds_5y', pd.Series(dtype=float))
        embi = self.data.get('embi_spread', pd.Series(dtype=float))
        
        if len(debt) > 0:
            z_debt = z_score_rolling(to_monthly(debt))
            if len(cds) > 0:
                z_cds = z_score_rolling(to_monthly(cds))
                common = z_debt.index.intersection(z_cds.index)
                self.states['X3_fiscal_risk'] = (z_debt.loc[common] + z_cds.loc[common]) / 2
            elif len(embi) > 0:
                z_embi = z_score_rolling(to_monthly(embi))
                common = z_debt.index.intersection(z_embi.index)
                self.states['X3_fiscal_risk'] = (z_debt.loc[common] + z_embi.loc[common]) / 2
            else:
                self.states['X3_fiscal_risk'] = z_debt
        else:
            self.states['X3_fiscal_risk'] = pd.Series(dtype=float)
        
        # X4: termos_de_troca
        tot = self.data.get('terms_of_trade', pd.Series(dtype=float))
        if len(tot) > 0:
            self.states['X4_termos_de_troca'] = to_monthly(tot)
        else:
            comm = self.data.get('comm_idx', pd.Series(dtype=float))
            self.states['X4_termos_de_troca'] = to_monthly(comm) if len(comm) > 0 else pd.Series(dtype=float)
        
        # X5: dolar_global
        dxy = self.data.get('dxy', pd.Series(dtype=float))
        self.states['X5_dolar_global'] = dxy if len(dxy) > 0 else pd.Series(dtype=float)
        
        # X6: risk_global = zscore(VIX) or FCI
        vix = self.data.get('vix', pd.Series(dtype=float))
        fci = self.data.get('fci_combined', pd.Series(dtype=float))
        if len(vix) > 0:
            self.states['X6_risk_global'] = to_monthly(vix)
        elif len(fci) > 0:
            self.states['X6_risk_global'] = to_monthly(fci)
        else:
            self.states['X6_risk_global'] = pd.Series(dtype=float)
        
        # X7: hiato (output gap)
        gap = self.data.get('output_gap', pd.Series(dtype=float))
        self.states['X7_hiato'] = gap if len(gap) > 0 else pd.Series(dtype=float)
        
        # Compute Z-scores (rolling 5Y = 60 months)
        log("\nComputing rolling 5Y Z-scores with winsorization [5%-95%]:")
        for key, series in self.states.items():
            if len(series) > 36:
                z = z_score_rolling(series, window=60, min_periods=36)
                self.z_states[f'Z_{key}'] = z
                last_val = z.dropna().iloc[-1] if len(z.dropna()) > 0 else np.nan
                log(f"  {key}: {len(z.dropna())} pts, latest Z = {last_val:.3f}")
            else:
                self.z_states[f'Z_{key}'] = pd.Series(dtype=float)
                log(f"  {key}: insufficient data")
        
        return self.states, self.z_states


# ============================================================
# 3. EXPECTED RETURN MODELS
# ============================================================

class ExpectedReturnModels:
    """
    Estimate expected returns for each asset class using rolling regressions
    on unified state variables.
    """
    
    def __init__(self, data, z_states):
        self.data = data
        self.z_states = z_states
        self.models = {}
        self.expected_returns = {}
    
    def compute(self):
        log("\n" + "=" * 60)
        log("EXPECTED RETURN MODELS")
        log("=" * 60)
        
        spot = self.data.get('spot_brlusd', pd.Series(dtype=float))
        
        # Build forward returns for each asset class
        self._compute_fx_model(spot)
        self._compute_front_model()
        self._compute_long_model()
        self._compute_hard_model()
        
        return self.models, self.expected_returns
    
    def _build_factor_matrix(self, factor_names, target_index):
        """Build aligned factor matrix for regression"""
        factors = {}
        for name in factor_names:
            z_key = f'Z_{name}'
            if z_key in self.z_states and len(self.z_states[z_key]) > 0:
                factors[name] = self.z_states[z_key]
        
        if not factors:
            return None
        
        df = pd.DataFrame(factors)
        df = df.reindex(target_index).dropna()
        return df
    
    def _run_rolling_regression(self, y, X, name, horizon_months=6):
        """Run OLS regression and compute expected return"""
        if len(y) < 36 or X is None or len(X) < 36:
            log(f"  [{name}] Insufficient data for regression")
            return None, None
        
        # Align
        common = y.index.intersection(X.index)
        y_aligned = winsorize(y.loc[common].dropna())
        X_aligned = X.loc[y_aligned.index]
        
        # Drop any remaining NaN
        mask = X_aligned.notna().all(axis=1) & y_aligned.notna()
        y_clean = y_aligned[mask]
        X_clean = X_aligned[mask]
        
        if len(y_clean) < 36:
            log(f"  [{name}] Insufficient clean data: {len(y_clean)} points")
            return None, None
        
        # Winsorize all columns
        for col in X_clean.columns:
            X_clean[col] = winsorize(X_clean[col])
        
        # OLS regression
        X_const = sm.add_constant(X_clean)
        try:
            model = sm.OLS(y_clean, X_const).fit()
            
            # Current expected return
            latest_X = X_clean.iloc[-1:]
            latest_X_const = sm.add_constant(latest_X, has_constant='add')
            expected_ret = float(model.predict(latest_X_const).iloc[0])
            
            log(f"  [{name}] R²={model.rsquared:.4f}, N={len(y_clean)}, E[r]={expected_ret*100:.2f}%")
            for i, var in enumerate(X_clean.columns):
                coef = model.params.iloc[i+1]
                pval = model.pvalues.iloc[i+1]
                log(f"    {var}: β={coef:.4f}, p={pval:.3f}")
            
            return model, expected_ret
        except Exception as e:
            log(f"  [{name}] Regression failed: {e}")
            return None, None
    
    def _compute_fx_model(self, spot):
        """FX expected return model"""
        log("\n4.1 FX Expected Return Model")
        
        if len(spot) < 36:
            log("  Insufficient spot data")
            return
        
        # Forward returns: 3m and 6m
        for horizon, h_months in [('3m', 3), ('6m', 6)]:
            fwd_ret = (spot.shift(-h_months) / spot - 1).dropna()
            
            factors = self._build_factor_matrix(
                ['X1_diferencial_real', 'X3_fiscal_risk', 'X4_termos_de_troca',
                 'X5_dolar_global', 'X6_risk_global'],
                fwd_ret.index
            )
            
            model, exp_ret = self._run_rolling_regression(
                fwd_ret, factors, f'FX_{horizon}', h_months
            )
            
            if model is not None:
                self.models[f'fx_{horizon}'] = {
                    'regression': model,
                    'r_squared': model.rsquared,
                    'coefficients': dict(zip(model.params.index, model.params.values)),
                    'pvalues': dict(zip(model.pvalues.index, model.pvalues.values)),
                }
                self.expected_returns[f'fx_{horizon}'] = exp_ret
    
    def _compute_front_model(self):
        """Front-end local rates expected return model"""
        log("\n4.2 Front-End Local Rates Model")
        
        di1y = self.data.get('di_1y', pd.Series(dtype=float))
        if len(di1y) < 36:
            log("  Insufficient DI 1Y data")
            return
        
        di1y_m = to_monthly(di1y)
        
        # Forward return: change in yield (negative = rates fall = bond gains)
        for horizon, h_months in [('3m', 3), ('6m', 6)]:
            yield_change = -(di1y_m.shift(-h_months) - di1y_m).dropna() / 100  # Convert to return proxy
            
            factors = self._build_factor_matrix(
                ['X2_surpresa_inflacao', 'X7_hiato', 'X1_diferencial_real', 'X3_fiscal_risk'],
                yield_change.index
            )
            
            model, exp_ret = self._run_rolling_regression(
                yield_change, factors, f'Front_{horizon}', h_months
            )
            
            if model is not None:
                self.models[f'front_{horizon}'] = {
                    'regression': model,
                    'r_squared': model.rsquared,
                    'coefficients': dict(zip(model.params.index, model.params.values)),
                    'pvalues': dict(zip(model.pvalues.index, model.pvalues.values)),
                }
                self.expected_returns[f'front_{horizon}'] = exp_ret
    
    def _compute_long_model(self):
        """Long-end local rates expected return model"""
        log("\n4.3 Long-End Local Rates Model")
        
        di10y = self.data.get('di_10y', pd.Series(dtype=float))
        if len(di10y) < 36:
            # Fallback to 5Y
            di10y = self.data.get('di_5y', pd.Series(dtype=float))
        if len(di10y) < 36:
            log("  Insufficient long-end data")
            return
        
        di_long_m = to_monthly(di10y)
        
        # Use breakeven as additional factor
        be_key = 'breakeven_5y' if len(self.data.get('breakeven_5y', pd.Series(dtype=float))) > 0 else None
        
        for horizon, h_months in [('3m', 3), ('6m', 6)]:
            yield_change = -(di_long_m.shift(-h_months) - di_long_m).dropna() / 100
            
            factor_names = ['X3_fiscal_risk', 'X5_dolar_global', 'X6_risk_global']
            
            factors = self._build_factor_matrix(factor_names, yield_change.index)
            
            # Add breakeven Z-score if available
            if be_key and len(self.data[be_key]) > 36:
                be_z = z_score_rolling(to_monthly(self.data[be_key]))
                if factors is not None and len(be_z.dropna()) > 0:
                    factors['Z_breakeven'] = be_z.reindex(factors.index)
                    factors = factors.dropna()
            
            model, exp_ret = self._run_rolling_regression(
                yield_change, factors, f'Long_{horizon}', h_months
            )
            
            if model is not None:
                self.models[f'long_{horizon}'] = {
                    'regression': model,
                    'r_squared': model.rsquared,
                    'coefficients': dict(zip(model.params.index, model.params.values)),
                    'pvalues': dict(zip(model.pvalues.index, model.pvalues.values)),
                }
                self.expected_returns[f'long_{horizon}'] = exp_ret
    
    def _compute_hard_model(self):
        """Hard currency sovereign expected return model"""
        log("\n4.4 Hard Currency Sovereign Model")
        
        embi = self.data.get('embi_spread', pd.Series(dtype=float))
        if len(embi) < 36:
            log("  Insufficient EMBI data")
            return
        
        embi_m = to_monthly(embi)
        
        for horizon, h_months in [('3m', 3), ('6m', 6)]:
            # Spread compression = positive return
            spread_change = -(embi_m.shift(-h_months) - embi_m).dropna() / 10000  # bps to return proxy
            
            # Z-score of EMBI level
            z_embi = z_score_rolling(embi_m)
            
            factor_names = ['X6_risk_global', 'X3_fiscal_risk']
            factors = self._build_factor_matrix(factor_names, spread_change.index)
            
            if factors is not None and len(z_embi.dropna()) > 0:
                factors['Z_embi_level'] = z_embi.reindex(factors.index)
                
                # Add UST 10Y Z-score
                ust10 = self.data.get('ust_10y', pd.Series(dtype=float))
                if len(ust10) > 36:
                    z_ust = z_score_rolling(to_monthly(ust10))
                    factors['Z_ust_10y'] = z_ust.reindex(factors.index)
                
                factors = factors.dropna()
            
            model, exp_ret = self._run_rolling_regression(
                spread_change, factors, f'Hard_{horizon}', h_months
            )
            
            if model is not None:
                self.models[f'hard_{horizon}'] = {
                    'regression': model,
                    'r_squared': model.rsquared,
                    'coefficients': dict(zip(model.params.index, model.params.values)),
                    'pvalues': dict(zip(model.pvalues.index, model.pvalues.values)),
                }
                self.expected_returns[f'hard_{horizon}'] = exp_ret


# ============================================================
# 4. REGIME MODEL (3-STATE MARKOV SWITCHING)
# ============================================================

class RegimeModel3State:
    """
    3-state Markov Switching model:
    - Regime 1: Carry Benigno (low vol, positive carry)
    - Regime 2: Risk Off Global (high vol, negative returns)
    - Regime 3: Stress Doméstico (fiscal/political crisis)
    """
    
    def __init__(self, data, z_states):
        self.data = data
        self.z_states = z_states
        self.regime_probs = None
        self.current_regime = None
        self.ms_model = None
    
    def compute(self):
        log("\n" + "=" * 60)
        log("REGIME MODEL: 3-State Markov Switching")
        log("=" * 60)
        
        spot = self.data.get('spot_brlusd', pd.Series(dtype=float))
        di10y = self.data.get('di_10y', self.data.get('di_5y', pd.Series(dtype=float)))
        
        if len(spot) < 60:
            log("  Insufficient data for regime model")
            return self._fallback_regime()
        
        # Target variable: combined FX + long-end return (as per spec)
        fx_ret = np.log(spot / spot.shift(1)).dropna() * 100
        
        if len(di10y) > 0:
            di_m = to_monthly(di10y)
            di_chg = di_m.diff().dropna()
            common = fx_ret.index.intersection(di_chg.index)
            if len(common) > 60:
                # Combined: FX depreciation + yield increase = stress
                combined = fx_ret.loc[common] + di_chg.loc[common] * 0.5
                combined = winsorize(combined, 0.02, 0.98)
            else:
                combined = winsorize(fx_ret, 0.02, 0.98)
        else:
            combined = winsorize(fx_ret, 0.02, 0.98)
        
        combined = combined.dropna()
        
        # Try 3-state first, fall back to 2-state
        for n_regimes in [3, 2]:
            try:
                log(f"\n  Fitting {n_regimes}-state Markov Switching...")
                ms = MarkovRegression(
                    combined,
                    k_regimes=n_regimes,
                    trend='c',
                    switching_variance=True
                )
                ms_fit = ms.fit(maxiter=200, disp=False)
                self.ms_model = ms_fit
                
                # Extract regime probabilities
                probs = ms_fit.smoothed_marginal_probabilities
                
                # Identify regimes by volatility
                regime_vols = {}
                for i in range(n_regimes):
                    try:
                        sigma2 = ms_fit.params.get(f'sigma2[{i}]', ms_fit.params.iloc[-(n_regimes-i)])
                        regime_vols[i] = float(sigma2)
                    except:
                        regime_vols[i] = float(i)
                
                # Sort by volatility: lowest vol = Carry, highest = Stress
                sorted_regimes = sorted(regime_vols.keys(), key=lambda x: regime_vols[x])
                
                if n_regimes == 3:
                    regime_names = {
                        sorted_regimes[0]: 'Carry',
                        sorted_regimes[1]: 'RiskOff',
                        sorted_regimes[2]: 'StressDom',
                    }
                else:
                    regime_names = {
                        sorted_regimes[0]: 'Carry',
                        sorted_regimes[1]: 'RiskOff',
                    }
                
                # Build probability dataframe
                prob_df = pd.DataFrame(index=combined.index)
                for i in range(n_regimes):
                    name = regime_names.get(i, f'Regime{i}')
                    prob_df[f'P_{name}'] = probs[i].values if hasattr(probs[i], 'values') else probs.iloc[:, i].values
                
                self.regime_probs = prob_df
                
                # Current regime
                latest_probs = prob_df.iloc[-1]
                self.current_regime = latest_probs.idxmax().replace('P_', '')
                
                log(f"  Success! {n_regimes} regimes identified:")
                for i in range(n_regimes):
                    name = regime_names.get(i, f'Regime{i}')
                    vol = np.sqrt(regime_vols[i]) if regime_vols[i] > 0 else 0
                    latest_p = latest_probs.get(f'P_{name}', 0)
                    log(f"    {name}: σ={vol:.3f}, P(current)={latest_p:.1%}")
                
                log(f"  Current regime: {self.current_regime}")
                log(f"  Log-likelihood: {ms_fit.llf:.2f}, AIC: {ms_fit.aic:.1f}")
                
                return {
                    'regime_probs': self.regime_probs,
                    'current_regime': self.current_regime,
                    'regime_names': regime_names,
                    'regime_vols': regime_vols,
                    'n_regimes': n_regimes,
                    'ms_model': ms_fit,
                }
            
            except Exception as e:
                log(f"  {n_regimes}-state failed: {e}")
                continue
        
        return self._fallback_regime()
    
    def _fallback_regime(self):
        """Fallback: use VIX-based regime classification"""
        log("  Using VIX-based fallback regime classification")
        
        vix = self.data.get('vix', pd.Series(dtype=float))
        embi = self.data.get('embi_spread', pd.Series(dtype=float))
        
        if len(vix) > 0:
            vix_m = to_monthly(vix)
            z_vix = z_score_rolling(vix_m)
            
            prob_df = pd.DataFrame(index=z_vix.dropna().index)
            # Simple threshold-based
            prob_df['P_Carry'] = (z_vix < 0).astype(float) * 0.7 + 0.15
            prob_df['P_RiskOff'] = (z_vix >= 0).astype(float) * 0.5 + 0.15
            prob_df['P_StressDom'] = 0.15
            
            # Normalize
            row_sum = prob_df.sum(axis=1)
            prob_df = prob_df.div(row_sum, axis=0)
            
            self.regime_probs = prob_df
            self.current_regime = prob_df.iloc[-1].idxmax().replace('P_', '')
        else:
            self.regime_probs = pd.DataFrame()
            self.current_regime = 'Neutral'
        
        return {
            'regime_probs': self.regime_probs,
            'current_regime': self.current_regime,
            'regime_names': {0: 'Carry', 1: 'RiskOff', 2: 'StressDom'},
            'regime_vols': {},
            'n_regimes': 3,
            'ms_model': None,
        }


# ============================================================
# 5. CROSS-ASSET FAIR VALUE
# ============================================================

class FairValueEngine:
    """Compute fair values for FX and rates"""
    
    def __init__(self, data, z_states):
        self.data = data
        self.z_states = z_states
        self.fair_values = {}
    
    def compute(self):
        log("\n" + "=" * 60)
        log("FAIR VALUE ENGINE")
        log("=" * 60)
        
        self._fx_fair_value()
        self._rates_fair_value()
        
        return self.fair_values
    
    def _fx_fair_value(self):
        """FX fair value in 3 layers: PPP, BEER, Cyclical"""
        log("\n6.1 FX Fair Value (3-layer)")
        
        spot = self.data.get('spot_brlusd', pd.Series(dtype=float))
        
        # Layer 1: PPP
        ppp = self.data.get('ppp_factor', pd.Series(dtype=float))
        if len(ppp) > 0:
            ppp_monthly = ppp.resample('MS').interpolate(method='linear')
            ppp_fair = ppp_monthly.reindex(spot.index, method='ffill')
        else:
            ppp_fair = spot * np.nan
        
        # Layer 2: BEER (from existing model - use regression-based)
        # Simple BEER: spot adjusted by fundamentals
        beer_fair = self._compute_beer_fair(spot)
        
        # Layer 3: Cyclical (short-term mean reversion)
        cycl_fair = spot.rolling(12).mean()  # 12-month moving average
        
        # Weighted average: 0.4 PPP + 0.3 BEER + 0.3 Cyclical
        common = spot.index
        fx_fair = pd.Series(np.nan, index=common)
        
        for idx in common:
            vals = []
            weights = []
            if idx in ppp_fair.index and not np.isnan(ppp_fair.get(idx, np.nan)):
                vals.append(ppp_fair[idx])
                weights.append(0.4)
            if idx in beer_fair.index and not np.isnan(beer_fair.get(idx, np.nan)):
                vals.append(beer_fair[idx])
                weights.append(0.3)
            if idx in cycl_fair.index and not np.isnan(cycl_fair.get(idx, np.nan)):
                vals.append(cycl_fair[idx])
                weights.append(0.3)
            
            if vals:
                w = np.array(weights)
                w = w / w.sum()
                fx_fair[idx] = np.average(vals, weights=w)
        
        fx_fair = fx_fair.dropna()
        
        # Misalignment
        mis_fx = (spot.reindex(fx_fair.index) / fx_fair - 1)
        
        self.fair_values['fx'] = {
            'fair_value': fx_fair,
            'ppp_fair': ppp_fair,
            'beer_fair': beer_fair,
            'cycl_fair': cycl_fair,
            'misalignment': mis_fx,
        }
        
        if len(fx_fair.dropna()) > 0:
            latest = fx_fair.dropna().iloc[-1]
            latest_spot = spot.iloc[-1]
            latest_mis = mis_fx.dropna().iloc[-1] if len(mis_fx.dropna()) > 0 else 0
            log(f"  FX Fair Value: {latest:.4f} (spot={latest_spot:.4f}, mis={latest_mis*100:.1f}%)")
    
    def _compute_beer_fair(self, spot):
        """BEER fair value via regression on fundamentals"""
        # Use terms of trade, real differential, fiscal risk
        tot = self.data.get('terms_of_trade', pd.Series(dtype=float))
        embi = self.data.get('embi_spread', pd.Series(dtype=float))
        
        if len(tot) > 36 and len(spot) > 36:
            df = pd.DataFrame({
                'spot': np.log(to_monthly(spot)),
                'tot': to_monthly(tot),
            })
            if len(embi) > 0:
                df['embi'] = to_monthly(embi)
            
            df = df.dropna()
            if len(df) > 36:
                y = df['spot']
                X = sm.add_constant(df.drop('spot', axis=1))
                try:
                    model = sm.OLS(y, X).fit()
                    fitted = np.exp(model.fittedvalues)
                    return fitted
                except:
                    pass
        
        return spot.rolling(24).mean()  # Fallback: 2Y MA
    
    def _rates_fair_value(self):
        """Rates fair value: expected policy path + term premium"""
        log("\n6.2 Rates Fair Value")
        
        selic = self.data.get('selic_target', pd.Series(dtype=float))
        di1y = self.data.get('di_1y', pd.Series(dtype=float))
        di10y = self.data.get('di_10y', self.data.get('di_5y', pd.Series(dtype=float)))
        
        if len(selic) > 0 and len(di1y) > 0:
            selic_m = to_monthly(selic)
            di1y_m = to_monthly(di1y)
            
            # Front-end fair: SELIC + expected path adjustment
            # Simple: SELIC + rolling mean of (DI1Y - SELIC) as policy premium
            common = selic_m.index.intersection(di1y_m.index)
            policy_premium = (di1y_m.loc[common] - selic_m.loc[common])
            avg_premium = policy_premium.rolling(12).mean()
            front_fair = selic_m.loc[common] + avg_premium
            
            self.fair_values['front'] = {
                'fair_value': front_fair.dropna(),
                'policy_premium': policy_premium,
            }
            
            if len(front_fair.dropna()) > 0:
                log(f"  Front fair: {front_fair.dropna().iloc[-1]:.2f}% (SELIC={selic_m.iloc[-1]:.2f}%)")
        
        if len(di10y) > 0 and len(selic) > 0:
            di10_m = to_monthly(di10y)
            selic_m = to_monthly(selic)
            common = di10_m.index.intersection(selic_m.index)
            
            # Term premium proxy: long - short
            term_premium = di10_m.loc[common] - selic_m.loc[common]
            avg_tp = term_premium.rolling(24).mean()
            long_fair = selic_m.loc[common] + avg_tp
            
            self.fair_values['long'] = {
                'fair_value': long_fair.dropna(),
                'term_premium': term_premium,
            }
            
            if len(long_fair.dropna()) > 0:
                latest_tp = term_premium.iloc[-1]
                log(f"  Long fair: {long_fair.dropna().iloc[-1]:.2f}% (term premium={latest_tp:.2f}%)")


# ============================================================
# 6. SIZING ENGINE
# ============================================================

class SizingEngine:
    """
    Optimal sizing by marginal risk:
    - FX: delta * vol
    - Front/Long: DV01 * yield vol
    - Hard: spread DV01 * spread vol
    """
    
    def __init__(self, data, expected_returns, regime_info, vol_target=0.10, max_position=2.0):
        self.data = data
        self.expected_returns = expected_returns
        self.regime_info = regime_info
        self.vol_target = vol_target
        self.max_position = max_position
        self.positions = {}
    
    def compute(self):
        log("\n" + "=" * 60)
        log("SIZING ENGINE")
        log("=" * 60)
        
        # Compute risk units for each asset
        risk_units = self._compute_risk_units()
        
        # Compute Sharpe estimates
        sharpes = {}
        for asset in ['fx', 'front', 'long', 'hard']:
            er_key = f'{asset}_6m'
            if er_key in self.expected_returns and self.expected_returns[er_key] is not None:
                er = self.expected_returns[er_key]
                ru = risk_units.get(asset, 0.15)
                if ru > 0:
                    sharpes[asset] = er / ru * np.sqrt(2)  # Annualize from 6m
                else:
                    sharpes[asset] = 0
        
        log(f"\n  Sharpe estimates:")
        for asset, sharpe in sharpes.items():
            log(f"    {asset}: {sharpe:.3f}")
        
        # Regime adjustment
        regime = self.regime_info.get('current_regime', 'Neutral')
        regime_multiplier = {
            'Carry': 1.2,
            'RiskOff': 0.5,
            'StressDom': 0.3,
            'Neutral': 0.8,
        }.get(regime, 0.8)
        
        log(f"\n  Regime: {regime} (multiplier={regime_multiplier:.1f})")
        
        # Compute raw weights (fractional Kelly with k=0.25)
        k = 0.25  # Conservative Kelly fraction
        raw_weights = {}
        for asset, sharpe in sharpes.items():
            er = self.expected_returns.get(f'{asset}_6m', 0) or 0
            ru = risk_units.get(asset, 0.15)
            variance = ru ** 2
            if variance > 0:
                raw_w = (er / variance) * k * regime_multiplier
            else:
                raw_w = 0
            raw_weights[asset] = np.clip(raw_w, -self.max_position, self.max_position)
        
        # Apply factor limits
        final_weights = self._apply_factor_limits(raw_weights)
        
        # Scale to target vol
        final_weights = self._scale_to_target_vol(final_weights, risk_units)
        
        # Build positions output
        for asset in ['fx', 'front', 'long', 'hard']:
            w = final_weights.get(asset, 0)
            er_3m = self.expected_returns.get(f'{asset}_3m', None)
            er_6m = self.expected_returns.get(f'{asset}_6m', None)
            ru = risk_units.get(asset, 0)
            sharpe = sharpes.get(asset, 0)
            
            direction = "LONG" if w > 0.05 else ("SHORT" if w < -0.05 else "NEUTRAL")
            
            self.positions[asset] = {
                'direction': direction,
                'weight': round(float(w), 4),
                'expected_return_3m': round(float(er_3m * 100), 2) if er_3m else None,
                'expected_return_6m': round(float(er_6m * 100), 2) if er_6m else None,
                'sharpe': round(float(sharpe), 3),
                'risk_unit': round(float(ru), 4),
                'risk_contribution': round(float(abs(w) * ru), 4),
            }
            er_6m_str = f"{er_6m*100:.2f}%" if er_6m is not None else 'N/A'
            log(f"\n  {asset.upper()}: {direction} (w={w:.3f}, E[r_6m]={er_6m_str}, Sharpe={sharpe:.3f})")
        
        return self.positions
    
    def _compute_risk_units(self):
        """Compute risk units for each asset class"""
        risk_units = {}
        
        # FX: annualized vol
        spot = self.data.get('spot_brlusd', pd.Series(dtype=float))
        if len(spot) > 60:
            daily_ret = np.log(spot / spot.shift(1)).dropna()
            fx_vol = daily_ret.rolling(63).std().iloc[-1] * np.sqrt(252)
            risk_units['fx'] = float(fx_vol) if not np.isnan(fx_vol) else 0.15
        else:
            risk_units['fx'] = 0.15
        
        # Front: DV01 proxy * yield vol
        di1y = self.data.get('di_1y', pd.Series(dtype=float))
        if len(di1y) > 60:
            di_m = to_monthly(di1y)
            yield_vol = di_m.diff().dropna().rolling(12).std().iloc[-1] / 100
            dv01_front = 1.0  # ~1 year duration
            risk_units['front'] = float(dv01_front * yield_vol) if not np.isnan(yield_vol) else 0.05
        else:
            risk_units['front'] = 0.05
        
        # Long: DV01 * yield vol
        di10y = self.data.get('di_10y', self.data.get('di_5y', pd.Series(dtype=float)))
        if len(di10y) > 60:
            di_m = to_monthly(di10y)
            yield_vol = di_m.diff().dropna().rolling(12).std().iloc[-1] / 100
            dv01_long = 7.0  # ~7 year duration for 10Y
            risk_units['long'] = float(dv01_long * yield_vol) if not np.isnan(yield_vol) else 0.10
        else:
            risk_units['long'] = 0.10
        
        # Hard: spread DV01 * spread vol
        embi = self.data.get('embi_spread', pd.Series(dtype=float))
        if len(embi) > 60:
            embi_m = to_monthly(embi)
            spread_vol = embi_m.diff().dropna().rolling(12).std().iloc[-1] / 10000
            spread_dv01 = 5.0  # ~5 year spread duration
            risk_units['hard'] = float(spread_dv01 * spread_vol) if not np.isnan(spread_vol) else 0.08
        else:
            risk_units['hard'] = 0.08
        
        log(f"\n  Risk units: {', '.join(f'{k}={v:.4f}' for k, v in risk_units.items())}")
        return risk_units
    
    def _apply_factor_limits(self, weights):
        """Apply factor exposure limits"""
        # Factor betas (simplified)
        factor_betas = {
            'dolar_global': {'fx': 0.7, 'front': 0.1, 'long': 0.3, 'hard': 0.5},
            'risk_off': {'fx': 0.6, 'front': 0.2, 'long': 0.4, 'hard': 0.7},
            'fiscal': {'fx': 0.4, 'front': 0.3, 'long': 0.6, 'hard': 0.5},
        }
        
        limits = {'dolar_global': 1.5, 'risk_off': 1.5, 'fiscal': 1.0}
        
        adjusted = dict(weights)
        
        for factor, betas in factor_betas.items():
            exposure = sum(adjusted.get(asset, 0) * beta for asset, beta in betas.items())
            limit = limits[factor]
            
            if abs(exposure) > limit:
                scale = limit / abs(exposure)
                for asset in adjusted:
                    if betas.get(asset, 0) > 0.3:  # Only scale high-beta assets
                        adjusted[asset] *= scale
                log(f"  Factor limit hit: {factor} ({exposure:.2f} > {limit}), scaling down")
        
        return adjusted
    
    def _scale_to_target_vol(self, weights, risk_units):
        """Scale portfolio to target volatility"""
        # Simple: sum of risk contributions
        total_risk = sum(abs(weights.get(a, 0)) * risk_units.get(a, 0) for a in weights)
        
        if total_risk > self.vol_target and total_risk > 0:
            scale = self.vol_target / total_risk
            return {a: w * scale for a, w in weights.items()}
        
        return weights


# ============================================================
# 7. RISK AGGREGATION
# ============================================================

class RiskAggregation:
    """
    Portfolio risk aggregation:
    - Rolling covariance matrix
    - Portfolio vol
    - Historical stress tests
    """
    
    def __init__(self, data, positions):
        self.data = data
        self.positions = positions
        self.risk_metrics = {}
    
    def compute(self):
        log("\n" + "=" * 60)
        log("RISK AGGREGATION")
        log("=" * 60)
        
        # Build return series for covariance
        returns = self._build_return_series()
        
        if returns is not None and len(returns) > 24:
            # Rolling 2Y covariance
            cov_matrix = returns.iloc[-24:].cov()
            
            # Portfolio vol - align weights with available columns
            asset_order = ['fx', 'front', 'long', 'hard']
            available = [a for a in asset_order if a in cov_matrix.columns]
            weights = np.array([
                self.positions.get(a, {}).get('weight', 0) for a in available
            ])
            cov_sub = cov_matrix.loc[available, available].values
            
            port_var = weights @ cov_sub @ weights
            port_vol = np.sqrt(max(port_var, 0)) * np.sqrt(12)  # Annualize from monthly
            
            self.risk_metrics['portfolio_vol'] = round(float(port_vol), 4)
            self.risk_metrics['correlation_matrix'] = returns.iloc[-24:].corr().round(3).to_dict()
            
            log(f"\n  Portfolio vol (annualized): {port_vol*100:.2f}%")
            log(f"  Correlation matrix:")
            corr = returns.iloc[-24:].corr()
            for col in corr.columns:
                log(f"    {col}: {corr[col].to_dict()}")
        
        # Stress tests
        self._run_stress_tests()
        
        return self.risk_metrics
    
    def _build_return_series(self):
        """Build monthly return series for each asset"""
        spot = self.data.get('spot_brlusd', pd.Series(dtype=float))
        di1y = self.data.get('di_1y', pd.Series(dtype=float))
        di10y = self.data.get('di_10y', self.data.get('di_5y', pd.Series(dtype=float)))
        embi = self.data.get('embi_spread', pd.Series(dtype=float))
        
        returns = {}
        
        if len(spot) > 24:
            spot_m = to_monthly(spot)
            returns['fx'] = np.log(spot_m / spot_m.shift(1))
        
        if len(di1y) > 24:
            di_m = to_monthly(di1y)
            returns['front'] = -di_m.diff() / 100  # Yield fall = positive return
        
        if len(di10y) > 24:
            di_m = to_monthly(di10y)
            returns['long'] = -di_m.diff() / 100 * 7  # Duration-adjusted
        
        if len(embi) > 24:
            embi_m = to_monthly(embi)
            returns['hard'] = -embi_m.diff() / 10000 * 5  # Spread DV01 adjusted
        
        if returns:
            df = pd.DataFrame(returns).dropna()
            return df
        return None
    
    def _run_stress_tests(self):
        """Run historical stress test scenarios"""
        log("\n  Stress Tests:")
        
        scenarios = {
            '2013_Taper': ('2013-05-01', '2013-09-30'),
            '2015_BR_Fiscal': ('2015-06-01', '2015-12-31'),
            '2020_Covid': ('2020-02-01', '2020-04-30'),
            '2022_Inflation': ('2022-01-01', '2022-06-30'),
        }
        
        returns = self._build_return_series()
        stress_results = {}
        
        if returns is not None:
            weights = {
                'fx': self.positions.get('fx', {}).get('weight', 0),
                'front': self.positions.get('front', {}).get('weight', 0),
                'long': self.positions.get('long', {}).get('weight', 0),
                'hard': self.positions.get('hard', {}).get('weight', 0),
            }
            
            for scenario_name, (start, end) in scenarios.items():
                try:
                    period = returns.loc[start:end]
                    if len(period) > 0:
                        # Per-asset returns during stress
                        asset_returns = {}
                        for asset in ['fx', 'front', 'long', 'hard']:
                            if asset in period.columns:
                                asset_ret = float(period[asset].sum())
                                asset_returns[asset] = round(asset_ret * 100, 2)
                        
                        # Portfolio return during stress
                        port_ret = sum(
                            period.get(asset, pd.Series(0, index=period.index)).sum() * w
                            for asset, w in weights.items()
                            if asset in period.columns
                        )
                        
                        # Max drawdown during period
                        cum_ret = sum(
                            (period.get(asset, pd.Series(0, index=period.index)).cumsum()) * w
                            for asset, w in weights.items()
                            if asset in period.columns
                        )
                        if hasattr(cum_ret, 'min'):
                            max_dd = float(cum_ret.min())
                        else:
                            max_dd = float(port_ret)
                        
                        stress_results[scenario_name] = {
                            'total_return': round(float(port_ret) * 100, 2),
                            'max_drawdown': round(float(max_dd) * 100, 2),
                            'months': len(period),
                            'asset_returns': asset_returns,
                            'start': start,
                            'end': end,
                        }
                        log(f"    {scenario_name}: return={port_ret*100:.2f}%, max_dd={max_dd*100:.2f}%")
                        for a, r in asset_returns.items():
                            log(f"      {a}: {r:.2f}%")
                except Exception as e:
                    log(f"    {scenario_name}: FAILED ({e})")
        
        # Add current drawdown from peak
        if returns is not None and len(returns) > 0:
            try:
                weights_arr = {
                    'fx': self.positions.get('fx', {}).get('weight', 0),
                    'front': self.positions.get('front', {}).get('weight', 0),
                    'long': self.positions.get('long', {}).get('weight', 0),
                    'hard': self.positions.get('hard', {}).get('weight', 0),
                }
                port_cum = sum(
                    returns.get(a, pd.Series(0, index=returns.index)).cumsum() * w
                    for a, w in weights_arr.items()
                    if a in returns.columns
                )
                if hasattr(port_cum, 'max'):
                    peak = port_cum.cummax()
                    dd = port_cum - peak
                    current_dd = float(dd.iloc[-1])
                    max_dd_hist = float(dd.min())
                    self.risk_metrics['current_drawdown'] = round(current_dd * 100, 2)
                    self.risk_metrics['max_drawdown_historical'] = round(max_dd_hist * 100, 2)
                    log(f"\n  Current drawdown: {current_dd*100:.2f}%")
                    log(f"  Max historical drawdown: {max_dd_hist*100:.2f}%")
            except Exception as e:
                log(f"  Drawdown calc failed: {e}")
        
        self.risk_metrics['stress_tests'] = stress_results


# ============================================================
# 8. MAIN ORCHESTRATOR
# ============================================================

def run_macro_risk_os():
    """Run the complete Macro Risk OS engine"""
    log("\n" + "=" * 60)
    log("MACRO RISK OS - STARTING")
    log("=" * 60)
    
    # 1. Load data
    loader = DataLoader()
    data = loader.load_all()
    
    # 2. Compute state variables
    sv = StateVariables(data)
    states, z_states = sv.compute()
    
    # 3. Expected return models
    erm = ExpectedReturnModels(data, z_states)
    models, expected_returns = erm.compute()
    
    # 4. Regime model
    rm = RegimeModel3State(data, z_states)
    regime_info = rm.compute()
    
    # 5. Fair value engine
    fve = FairValueEngine(data, z_states)
    fair_values = fve.compute()
    
    # 6. Sizing engine
    se = SizingEngine(data, expected_returns, regime_info)
    positions = se.compute()
    
    # 7. Risk aggregation
    ra = RiskAggregation(data, positions)
    risk_metrics = ra.compute()
    
    # 8. Build dashboard output
    dashboard = _build_dashboard(data, states, z_states, models, expected_returns,
                                  regime_info, fair_values, positions, risk_metrics)
    
    log("\n" + "=" * 60)
    log("MACRO RISK OS - COMPLETE")
    log("=" * 60)
    
    return dashboard


def _build_dashboard(data, states, z_states, models, expected_returns,
                     regime_info, fair_values, positions, risk_metrics):
    """Build the final dashboard JSON output"""
    
    spot = data.get('spot_brlusd', pd.Series(dtype=float))
    current_spot = float(spot.iloc[-1]) if len(spot) > 0 else 0
    
    # State variables summary
    state_summary = {}
    for key, z_series in z_states.items():
        if len(z_series.dropna()) > 0:
            state_summary[key] = round(float(z_series.dropna().iloc[-1]), 3)
    
    # FX fair value
    fx_fv = fair_values.get('fx', {})
    fx_fair = fx_fv.get('fair_value', pd.Series(dtype=float))
    fx_mis = fx_fv.get('misalignment', pd.Series(dtype=float))
    
    # Model details per asset
    model_details = {}
    for key, m in models.items():
        model_details[key] = {
            'r_squared': round(m['r_squared'], 4),
            'coefficients': {k: round(float(v), 4) for k, v in m['coefficients'].items()},
            'pvalues': {k: round(float(v), 4) for k, v in m['pvalues'].items()},
        }
    
    # Regime info
    regime_probs = regime_info.get('regime_probs', pd.DataFrame())
    current_regime = regime_info.get('current_regime', 'Neutral')
    
    regime_current = {}
    if len(regime_probs) > 0:
        latest = regime_probs.iloc[-1]
        for col in regime_probs.columns:
            regime_current[col] = round(float(latest[col]), 4)
    
    # Compute overall score
    total_er = sum(
        (positions.get(a, {}).get('expected_return_6m', 0) or 0) * abs(positions.get(a, {}).get('weight', 0))
        for a in ['fx', 'front', 'long', 'hard']
    )
    
    # Direction
    fx_w = positions.get('fx', {}).get('weight', 0)
    if fx_w > 0.05:
        direction = "LONG BRL (SHORT USD)"
    elif fx_w < -0.05:
        direction = "SHORT BRL (LONG USD)"
    else:
        direction = "NEUTRAL"
    
    dashboard = {
        'run_date': pd.Timestamp.now().strftime('%Y-%m-%d'),
        'current_spot': round(current_spot, 4),
        'direction': direction,
        'current_regime': current_regime,
        'regime_probabilities': regime_current,
        
        # State variables
        'state_variables': state_summary,
        
        # FX block
        'fx_fair_value': round(float(fx_fair.dropna().iloc[-1]), 4) if len(fx_fair.dropna()) > 0 else None,
        'fx_misalignment': round(float(fx_mis.dropna().iloc[-1]) * 100, 2) if len(fx_mis.dropna()) > 0 else None,
        'ppp_fair': round(float(fx_fv.get('ppp_fair', pd.Series(dtype=float)).dropna().iloc[-1]), 4) if len(fx_fv.get('ppp_fair', pd.Series(dtype=float)).dropna()) > 0 else None,
        'beer_fair': round(float(fx_fv.get('beer_fair', pd.Series(dtype=float)).dropna().iloc[-1]), 4) if len(fx_fv.get('beer_fair', pd.Series(dtype=float)).dropna()) > 0 else None,
        
        # Rates block
        'front_fair': round(float(fair_values.get('front', {}).get('fair_value', pd.Series(dtype=float)).dropna().iloc[-1]), 2) if len(fair_values.get('front', {}).get('fair_value', pd.Series(dtype=float)).dropna()) > 0 else None,
        'long_fair': round(float(fair_values.get('long', {}).get('fair_value', pd.Series(dtype=float)).dropna().iloc[-1]), 2) if len(fair_values.get('long', {}).get('fair_value', pd.Series(dtype=float)).dropna()) > 0 else None,
        'term_premium': round(float(fair_values.get('long', {}).get('term_premium', pd.Series(dtype=float)).dropna().iloc[-1]), 2) if len(fair_values.get('long', {}).get('term_premium', pd.Series(dtype=float)).dropna()) > 0 else None,
        
        # Current rates
        'selic_target': round(float(data.get('selic_target', pd.Series(dtype=float)).iloc[-1]), 2) if len(data.get('selic_target', pd.Series(dtype=float))) > 0 else None,
        'di_1y': round(float(data.get('di_1y', pd.Series(dtype=float)).iloc[-1]), 2) if len(data.get('di_1y', pd.Series(dtype=float))) > 0 else None,
        'di_5y': round(float(data.get('di_5y', pd.Series(dtype=float)).iloc[-1]), 2) if len(data.get('di_5y', pd.Series(dtype=float))) > 0 else None,
        'di_3m': round(float(data.get('di_3m', pd.Series(dtype=float)).iloc[-1]), 2) if len(data.get('di_3m', pd.Series(dtype=float))) > 0 else None,
        'di_6m': round(float(data.get('di_6m', pd.Series(dtype=float)).iloc[-1]), 2) if len(data.get('di_6m', pd.Series(dtype=float))) > 0 else None,
        'di_10y': round(float(data.get('di_10y', pd.Series(dtype=float)).iloc[-1]), 2) if len(data.get('di_10y', pd.Series(dtype=float))) > 0 else None,
        'ntnb_5y': round(float(data.get('ntnb_5y', pd.Series(dtype=float)).iloc[-1]), 2) if len(data.get('ntnb_5y', pd.Series(dtype=float))) > 0 else None,
        'ntnb_10y': round(float(data.get('ntnb_10y', pd.Series(dtype=float)).iloc[-1]), 2) if len(data.get('ntnb_10y', pd.Series(dtype=float))) > 0 else None,
        'breakeven_5y': round(float(data.get('breakeven_5y', pd.Series(dtype=float)).iloc[-1]), 2) if len(data.get('breakeven_5y', pd.Series(dtype=float))) > 0 else None,
        'breakeven_10y': round(float(data.get('breakeven_10y', pd.Series(dtype=float)).iloc[-1]), 2) if len(data.get('breakeven_10y', pd.Series(dtype=float))) > 0 else None,
        'ust_2y': round(float(data.get('ust_2y', pd.Series(dtype=float)).iloc[-1]), 2) if len(data.get('ust_2y', pd.Series(dtype=float))) > 0 else None,
        'ust_5y': round(float(data.get('ust_5y', pd.Series(dtype=float)).iloc[-1]), 2) if len(data.get('ust_5y', pd.Series(dtype=float))) > 0 else None,
        'ust_10y': round(float(data.get('ust_10y', pd.Series(dtype=float)).iloc[-1]), 2) if len(data.get('ust_10y', pd.Series(dtype=float))) > 0 else None,
        'embi_spread': round(float(data.get('embi_spread', pd.Series(dtype=float)).iloc[-1]), 0) if len(data.get('embi_spread', pd.Series(dtype=float))) > 0 else None,
        'cds_5y': round(float(data.get('cds_5y', pd.Series(dtype=float)).iloc[-1]), 0) if len(data.get('cds_5y', pd.Series(dtype=float))) > 0 else None,
        'vix': round(float(data.get('vix', pd.Series(dtype=float)).iloc[-1]), 2) if len(data.get('vix', pd.Series(dtype=float))) > 0 else None,
        'dxy': round(float(data.get('dxy', pd.Series(dtype=float)).iloc[-1]), 2) if len(data.get('dxy', pd.Series(dtype=float))) > 0 else None,
        
        # Positions
        'positions': positions,
        
        # Model details
        'model_details': model_details,
        
        # Risk
        'risk_metrics': risk_metrics,
        
        # Score
        'score_total': round(total_er, 2),
    }
    
    # Build timeseries for charts
    timeseries = _build_timeseries(data, fair_values, z_states)
    regime_ts = _build_regime_timeseries(regime_info)
    state_ts = _build_state_timeseries(z_states)
    
    return {
        'dashboard': dashboard,
        'timeseries': timeseries,
        'regime': regime_ts,
        'state_variables_ts': state_ts,
    }


def _build_timeseries(data, fair_values, z_states):
    """Build timeseries for charts"""
    spot = data.get('spot_brlusd', pd.Series(dtype=float))
    fx_fv = fair_values.get('fx', {})
    fx_fair = fx_fv.get('fair_value', pd.Series(dtype=float))
    ppp_fair = fx_fv.get('ppp_fair', pd.Series(dtype=float))
    beer_fair = fx_fv.get('beer_fair', pd.Series(dtype=float))
    
    records = []
    for date in spot.index:
        d = date.strftime('%Y-%m-%d')
        obj = {'date': d, 'spot': round(float(spot[date]), 4)}
        
        if date in fx_fair.index and not np.isnan(fx_fair.get(date, np.nan)):
            obj['fx_fair'] = round(float(fx_fair[date]), 4)
        if date in ppp_fair.index and not np.isnan(ppp_fair.get(date, np.nan)):
            obj['ppp_fair'] = round(float(ppp_fair[date]), 4)
        if date in beer_fair.index and not np.isnan(beer_fair.get(date, np.nan)):
            obj['beer_fair'] = round(float(beer_fair[date]), 4)
        
        # Z-scores
        for z_key, z_series in z_states.items():
            if date in z_series.index and not np.isnan(z_series.get(date, np.nan)):
                obj[z_key] = round(float(z_series[date]), 3)
        
        records.append(obj)
    
    return records


def _build_regime_timeseries(regime_info):
    """Build regime probability timeseries"""
    probs = regime_info.get('regime_probs', pd.DataFrame())
    if len(probs) == 0:
        return []
    
    records = []
    for date in probs.index:
        obj = {'date': date.strftime('%Y-%m-%d')}
        for col in probs.columns:
            obj[col] = round(float(probs.loc[date, col]), 4)
        records.append(obj)
    
    return records


def _build_state_timeseries(z_states):
    """Build state variable Z-score timeseries"""
    # Find common dates
    all_dates = set()
    for z_series in z_states.values():
        if len(z_series) > 0:
            all_dates.update(z_series.dropna().index)
    
    if not all_dates:
        return []
    
    all_dates = sorted(all_dates)
    records = []
    for date in all_dates:
        obj = {'date': date.strftime('%Y-%m-%d')}
        for key, z_series in z_states.items():
            if date in z_series.index and not np.isnan(z_series.get(date, np.nan)):
                short_key = key.replace('Z_X', 'Z_X')  # Keep as is
                obj[short_key] = round(float(z_series[date]), 3)
        if len(obj) > 1:  # Has at least one Z-score
            records.append(obj)
    
    return records


if __name__ == '__main__':
    result = run_macro_risk_os()
    print(json.dumps(result, default=str))
