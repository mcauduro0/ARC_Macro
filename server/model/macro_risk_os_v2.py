"""
MACRO RISK OS v2 — Institutional Rebuild
=========================================
Overlay-on-CDI framework with instrument-level returns, Ridge walk-forward,
unified backtest=production engine, dynamic risk budgets, and risk overlays.

Architecture:
  1. DataLayer          — load & align market/macro data, compute instrument returns
  2. FeatureEngine      — Z-scores, FX fair value (log), carry, half-life valuation
  3. AlphaModels        — Ridge walk-forward per instrument
  4. RegimeModel        — HMM 3-state on exogenous observables
  5. Optimizer          — mean-variance with TC, turnover penalty, factor limits
  6. RiskOverlays       — drawdown scaling, vol targeting, regime scaling
  7. ProductionEngine   — single code path for live & backtest
  8. BacktestHarness    — calls ProductionEngine in walk-forward loop
"""

import sys, os, json, math, warnings
from datetime import datetime
import numpy as np
import pandas as pd
from scipy.optimize import minimize
from sklearn.linear_model import Ridge
from sklearn.ensemble import GradientBoostingRegressor, RandomForestRegressor
import xgboost as xgb
from feature_selection import DualFeatureSelector, FeatureSelectionResult, InteractionBuilder, INTERACTION_PAIRS
from arch import arch_model
from scipy import stats
import shap
warnings.filterwarnings('ignore')

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")
os.makedirs(OUTPUT_DIR, exist_ok=True)

def log(msg):
    print(msg, file=sys.stderr)

# ============================================================
# DEFAULT CONFIG
# ============================================================
DEFAULT_CONFIG = {
    "base_currency": "BRL",
    "rebalance": "monthly",
    "prediction_horizon": "1m",
    "training_window_months": 36,  # v3.9.1: reduced from 60 to 36 to extend backtest coverage while keeping all instruments real
    "expanding_window": True,  # v3.8: True = expanding window (use all available data), False = fixed rolling window
    "min_training_months": 36,  # v3.9.1: reduced from 60 to 36 (3 years minimum training)
    "refit_frequency": "monthly",
    "standardization_window_months": 60,
    "std_floor": 0.5,
    "valuation_half_life_months": {"fx": 36, "rates": 24},
    "ridge_lambda": 10.0,
    "risk_targets": {"overlay_vol_target_annual": 0.10},
    "drawdown_overlay": {
        "dd_5": -0.05, "dd_10": -0.10,
        "scale_at_dd_5": 0.5, "scale_at_dd_10": 0.0
    },
    "position_limits": {
        "fx_weight_max": 1.0,
        "front_weight_max": 1.5,
        "belly_weight_max": 1.5,
        "long_weight_max": 0.75,
        "hard_weight_max": 1.0,
        "ntnb_weight_max": 0.5  # v5.1: NTN-B inflation-linked bonds — moderate limit (50%)
    },
    "factor_limits": {
        "dxy_limit": 1.5, "vix_limit": 1.5,
        "cds_limit": 1.0, "ust10_limit": 1.0
    },
    "transaction_costs_bps": {
        "fx": 5, "front": 2, "belly": 3, "long": 4, "hard": 5, "ntnb": 4  # v5.1: NTN-B transaction cost
    },
    # v3.8: Regime-dependent transaction cost multipliers
    # In stress regimes, bid-ask spreads widen → higher costs
    "tc_regime_multipliers": {
        "carry": 1.0,       # Normal market: base costs
        "riskoff": 1.5,     # Risk-off: 50% wider spreads
        "stress": 2.5,      # Stress: 150% wider spreads
        "domestic_stress": 2.0,  # Domestic stress: 100% wider
        "domestic_calm": 1.0     # Domestic calm: base costs
    },
    "turnover_penalty_bps": 2,
    "gamma": 2.0,  # risk aversion
    "score_demeaning_window": 60,  # rolling window for score z-score normalization
    # v2.3 improvements
    "fx_fv_weights": {"beer": 1.0},  # BEER-only fair value (institutional standard: GSDEER/BEER). PPP excluded (Balassa-Samuelson bias). Cyclical (Z_real_diff) used as trading signal via mu_fx_val, not in composite.
    "fx_cyclical_beta": 0.05,
    "ic_gating_threshold": 0.0,  # zero out mu for instruments with IC < threshold
    "ic_gating_min_obs": 24,  # minimum observations before IC gating kicks in
    "cov_window_months": 36,  # covariance estimation window
    "cov_shrinkage": True,  # Ledoit-Wolf shrinkage
    "regime_refit_interval": 12,  # refit HMM every N months during backtest
    "signal_quality_sizing": True,  # condition sizing on rolling IC
    # v2.3: Regime-conditional position limits
    "regime_position_limits": {
        # Carry regime: full limits (normal market)
        "carry": {
            "fx_weight_max": 1.0,
            "front_weight_max": 1.5,
            "belly_weight_max": 1.5,
            "long_weight_max": 0.75,
            "hard_weight_max": 1.0,
            "ntnb_weight_max": 0.5
        },
        # Risk-off: reduce duration exposure, maintain FX flexibility
        "riskoff": {
            "fx_weight_max": 0.8,
            "front_weight_max": 1.0,
            "belly_weight_max": 0.75,
            "long_weight_max": 0.40,
            "hard_weight_max": 0.6,
            "ntnb_weight_max": 0.3
        },
        # Stress: aggressive cuts across all instruments
        "stress": {
            "fx_weight_max": 0.5,
            "front_weight_max": 0.5,
            "belly_weight_max": 0.4,
            "long_weight_max": 0.25,
            "hard_weight_max": 0.3,
            "ntnb_weight_max": 0.15
        }
    },
}

# ============================================================
# 1. DATA LAYER
# ============================================================
def load_series(name):
    """Load CSV from data dir, return DatetimeIndex Series."""
    path = os.path.join(DATA_DIR, f"{name}.csv")
    if not os.path.exists(path):
        return pd.Series(dtype=float)
    df = pd.read_csv(path)
    # Detect date column
    date_col = None
    for c in ['Date', 'date', 'observation_date', 'data', 'Unnamed: 0']:
        if c in df.columns:
            date_col = c
            break
    if date_col is None:
        return pd.Series(dtype=float)
    val_col = [c for c in df.columns if c != date_col][0] if len(df.columns) > 1 else None
    if val_col is None:
        return pd.Series(dtype=float)
    df[date_col] = pd.to_datetime(df[date_col], errors='coerce')
    df = df.dropna(subset=[date_col])
    df = df.set_index(date_col)
    s = pd.to_numeric(df[val_col], errors='coerce').dropna()
    s.index.name = 'date'
    return s.sort_index()


def to_monthly(series, method='last'):
    """Resample to month-end."""
    if len(series) == 0:
        return pd.Series(dtype=float)
    s = series.copy()
    s.index = pd.to_datetime(s.index)
    if method == 'last':
        return s.resample('ME').last().dropna()
    return s.resample('ME').mean().dropna()


def winsorize(s, lower=0.05, upper=0.95):
    """Winsorize at 5-95 percentiles."""
    if len(s) < 10:
        return s
    lo = s.quantile(lower)
    hi = s.quantile(upper)
    return s.clip(lo, hi)


class DataLayer:
    """Load all market data and compute instrument returns."""

    def __init__(self, config=None):
        self.cfg = config or DEFAULT_CONFIG
        self.data = {}
        self.monthly = {}  # monthly aligned data
        self.instrument_returns = {}  # monthly returns per instrument

    def load_all(self):
        """Load all required series."""
        log("=" * 60)
        log("DATA LAYER v2 — Loading market data")
        log("=" * 60)

        # FX
        self.data['spot'] = load_series('USDBRL')
        self.data['ptax'] = load_series('PTAX')

        # DI curve (monthly from data_collector)
        for tenor in ['1Y', '2Y', '5Y', '10Y', '3M', '6M']:
            self.data[f'di_{tenor.lower()}'] = load_series(f'DI_{tenor}')
            anbima = load_series(f'ANBIMA_DI_{tenor}')
            if len(anbima) > 1:
                self.data[f'di_{tenor.lower()}'] = anbima

        # SELIC / CDI
        self.data['selic_target'] = load_series('SELIC_META')
        self.data['selic_over'] = load_series('SELIC_OVER')

        # NTN-B / Breakeven
        self.data['ntnb_5y'] = load_series('NTNB_5Y')
        self.data['ntnb_10y'] = load_series('NTNB_10Y')
        # Tesouro Direto NTN-B (primary source with full history)
        tesouro_ntnb_5y = load_series('TESOURO_NTNB_5Y')
        tesouro_ntnb_10y = load_series('TESOURO_NTNB_10Y')
        if len(tesouro_ntnb_5y) > 12:
            self.data['tesouro_ntnb_5y'] = tesouro_ntnb_5y
            log(f"    TESOURO_NTNB_5Y: {len(tesouro_ntnb_5y)} pts (Tesouro Direto)")
        if len(tesouro_ntnb_10y) > 12:
            self.data['tesouro_ntnb_10y'] = tesouro_ntnb_10y
            log(f"    TESOURO_NTNB_10Y: {len(tesouro_ntnb_10y)} pts (Tesouro Direto)")
        self.data['breakeven_5y'] = load_series('BREAKEVEN_5Y')
        self.data['breakeven_10y'] = load_series('BREAKEVEN_10Y')
        # ANBIMA overrides
        for k in ['NTNB_5Y', 'NTNB_10Y', 'BREAKEVEN_5Y', 'BREAKEVEN_10Y']:
            a = load_series(f'ANBIMA_{k}')
            if len(a) > 1:
                self.data[k.lower()] = a

        # US rates
        self.data['ust_2y'] = load_series('UST_2Y')
        self.data['ust_5y'] = load_series('UST_5Y')
        self.data['ust_10y'] = load_series('UST_10Y')

        # Credit
        self.data['cds_5y'] = load_series('CDS_5Y')
        self.data['embi_spread'] = load_series('EMBI_SPREAD')

        # Global
        self.data['dxy'] = load_series('DXY')
        self.data['vix'] = load_series('VIX')
        self.data['nfci'] = load_series('NFCI')

        # Macro BR
        # IPCA: load monthly variation (BCB 433) for computing 12M in build_monthly()
        self.data['ipca_monthly'] = load_series('IPCA_MONTHLY')
        self.data['ipca_yoy'] = load_series('IPCA_12M')  # Will be overwritten in build_monthly() if ipca_monthly available
        self.data['ipca_exp'] = load_series('IPCA_EXP_12M')
        self.data['debt_gdp'] = load_series('DIVIDA_BRUTA_PIB')
        self.data['primary_balance'] = load_series('PRIMARY_BALANCE')
        self.data['tot'] = load_series('TERMS_OF_TRADE')

        # Macro US
        self.data['us_cpi_exp'] = load_series('US_CPI_EXP')

        # Commodities (for regime)
        self.data['bcom'] = load_series('BCOM')
        if len(self.data['bcom']) == 0:
            self.data['bcom'] = load_series('CRUDE_OIL')

        # FX forwards / cupom cambial
        # v2.3: Multi-source cupom cambial with full coverage
        # Priority: Swap DI x Dólar 30d (BCB 7811, 1991-present) > Cupom limpo 30d (3954, 1994-2024) > Legacy 3955
        swap_dixdol_30d = load_series('SWAP_DIXDOL_30D')
        cupom_limpo_30d = load_series('FX_CUPOM_LIMPO_30D')
        legacy_cupom_1m = load_series('FX_CUPOM_1M')
        
        # Build blended series: start with longest, overlay with more accurate
        if len(swap_dixdol_30d) > 12:
            # Swap DI x Dólar is the primary source (1991-present, 420+ pts)
            self.data['fx_cupom_1m'] = swap_dixdol_30d
            log(f"    FX cupom: using Swap DI x Dólar 30d (BCB 7811) — {len(swap_dixdol_30d)} pts")
            # Cross-validate with cupom limpo where both exist
            if len(cupom_limpo_30d) > 12:
                common = swap_dixdol_30d.index.intersection(cupom_limpo_30d.index)
                if len(common) > 12:
                    corr = swap_dixdol_30d.reindex(common).corr(cupom_limpo_30d.reindex(common))
                    log(f"    FX cupom: cross-validation corr(swap, limpo) = {corr:.4f} on {len(common)} months")
        elif len(cupom_limpo_30d) > 12:
            self.data['fx_cupom_1m'] = cupom_limpo_30d
            log(f"    FX cupom: using Cupom Limpo 30d (BCB 3954) — {len(cupom_limpo_30d)} pts")
        elif len(legacy_cupom_1m) > 12:
            self.data['fx_cupom_1m'] = legacy_cupom_1m
            log(f"    FX cupom: using legacy 3955 — {len(legacy_cupom_1m)} pts")
        else:
            self.data['fx_cupom_1m'] = pd.Series(dtype=float)
            log(f"    FX cupom: NO cupom cambial data available")
        
        # Also load other tenors for CIP basis and carry analysis
        self.data['swap_dixdol_90d'] = load_series('SWAP_DIXDOL_90D')
        self.data['swap_dixdol_360d'] = load_series('SWAP_DIXDOL_360D')

        # DI swaps (for CIP basis)
        self.data['di_swap_360d'] = load_series('DI_SWAP_360D')
        self.data['di_swap_90d'] = load_series('DI_SWAP_90D')

        # PPP
        self.data['ppp_factor'] = load_series('PPP_FACTOR')
        self.data['reer'] = load_series('REER_BIS')
        if len(self.data['reer']) == 0:
            self.data['reer'] = load_series('REER_BCB')

        # Balassa-Samuelson & FEER data
        gdppc_path = os.path.join(DATA_DIR, 'GDP_PER_CAPITA.csv')
        if os.path.exists(gdppc_path):
            gdppc_df = pd.read_csv(gdppc_path)
            gdppc_df['date'] = pd.to_datetime(gdppc_df['date'])
            gdppc_df = gdppc_df.set_index('date')
            if 'gdppc_ratio' in gdppc_df.columns:
                self.data['gdppc_ratio'] = gdppc_df['gdppc_ratio'].dropna()
            log(f"    gdppc_ratio loaded: {len(self.data.get('gdppc_ratio', []))} pts")
        ca_path = os.path.join(DATA_DIR, 'CURRENT_ACCOUNT.csv')
        if os.path.exists(ca_path):
            ca_df = pd.read_csv(ca_path)
            ca_df['date'] = pd.to_datetime(ca_df['date'])
            ca_df = ca_df.set_index('date')
            if 'ca_pct_gdp' in ca_df.columns:
                self.data['ca_pct_gdp'] = ca_df['ca_pct_gdp'].dropna()
            log(f"    ca_pct_gdp loaded: {len(self.data.get('ca_pct_gdp', []))} pts")
        trade_path = os.path.join(DATA_DIR, 'TRADE_OPENNESS.csv')
        if os.path.exists(trade_path):
            trade_df = pd.read_csv(trade_path)
            trade_df['date'] = pd.to_datetime(trade_df['date'])
            trade_df = trade_df.set_index('date')
            if 'trade_pct_gdp' in trade_df.columns:
                self.data['trade_openness'] = trade_df['trade_pct_gdp'].dropna()
            log(f"    trade_openness loaded: {len(self.data.get('trade_openness', []))} pts")

        # BEER fundamentals
        self.data['bop_current'] = load_series('BOP_CURRENT')
        self.data['ibc_br'] = load_series('IBC_BR')
        self.data['iron_ore'] = load_series('IRON_ORE')

        # US real yields & breakevens
        self.data['us_tips_10y'] = load_series('US_TIPS_10Y')
        self.data['us_tips_5y'] = load_series('US_TIPS_5Y')
        self.data['us_breakeven_10y'] = load_series('US_BREAKEVEN_10Y')

        # US HY spread (risk appetite)
        self.data['us_hy_spread'] = load_series('US_HY_SPREAD')

        # EWZ (equity risk appetite)
        self.data['ewz'] = load_series('EWZ')

        # v3.7: Additional variables
        self.data['focus_fx_12m'] = load_series('FOCUS_FX_12M')
        self.data['cftc_brl_net_spec'] = load_series('CFTC_BRL_NET_SPEC')
        self.data['idp_flow'] = load_series('IDP_FLOW')
        self.data['portfolio_flow'] = load_series('PORTFOLIO_FLOW')

        log(f"\n  Loaded {sum(1 for v in self.data.values() if len(v) > 0)} series")
        for k, v in sorted(self.data.items()):
            if len(v) > 0:
                log(f"    {k:25s}: {len(v):>5} pts, {v.index[0].strftime('%Y-%m')} → {v.index[-1].strftime('%Y-%m')}")

        return self

    def build_monthly(self):
        """Build monthly aligned dataset."""
        log("\n  Building monthly aligned data...")
        for k, v in self.data.items():
            if len(v) > 0:
                self.monthly[k] = to_monthly(v)

        # Compute IPCA 12M (acumulado) from IPCA monthly variation
        # BCB series 432 is the index number, not the YoY change
        # We compute it properly: (1+m1/100)*(1+m2/100)*...*(1+m12/100) - 1) * 100
        ipca_m = self.monthly.get('ipca_monthly', pd.Series(dtype=float))
        if len(ipca_m) > 12:
            # Rolling 12-month compounded inflation
            ipca_factor = (1 + ipca_m / 100)  # Convert % to factor
            ipca_12m = ipca_factor.rolling(12).apply(lambda x: x.prod() - 1, raw=True) * 100
            self.monthly['ipca_yoy'] = ipca_12m.dropna()
            log(f"    ipca_yoy computed from monthly: {len(self.monthly['ipca_yoy'])} months, current={self.monthly['ipca_yoy'].iloc[-1]:.2f}%")
        elif 'ipca_yoy' in self.monthly:
            # Fallback: use the raw series but warn
            log(f"    WARNING: using raw ipca_yoy series (may be index number, not YoY %)")

        # Forward-fill REER beyond last available month (BIS data has ~2 month lag)
        # REER changes slowly, so forward-fill is appropriate for 1-2 months
        if 'reer' in self.monthly and len(self.monthly['reer']) > 0:
            reer_m = self.monthly['reer']
            spot_m = self.monthly.get('ptax', self.monthly.get('spot', pd.Series(dtype=float)))
            if len(spot_m) > 0:
                last_spot_date = spot_m.index[-1]
                last_reer_date = reer_m.index[-1]
                if last_spot_date > last_reer_date:
                    extra_dates = spot_m.index[spot_m.index > last_reer_date]
                    if len(extra_dates) > 0 and len(extra_dates) <= 6:  # Only forward-fill up to 6 months
                        extra = pd.Series(reer_m.iloc[-1], index=extra_dates)
                        self.monthly['reer'] = pd.concat([reer_m, extra]).sort_index()
                        log(f"    reer forward-filled {len(extra_dates)} months beyond {last_reer_date.strftime('%Y-%m')} (value={reer_m.iloc[-1]:.2f})")

        # Interpolate annual PPP factor to monthly (linear between years)
        if 'ppp_factor' in self.monthly and len(self.monthly['ppp_factor']) > 2:
            ppp_m = self.monthly['ppp_factor']
            # If data is annual (< 50 points for 30+ years), interpolate
            if len(ppp_m) < 50:
                ppp_daily = ppp_m.resample('D').interpolate(method='linear')
                ppp_interp = ppp_daily.resample('ME').last().dropna()
                # Forward-fill beyond last annual data point to cover current month
                # PPP changes slowly (structural), so forward-fill is appropriate
                spot_m = self.monthly.get('ptax', self.monthly.get('spot', pd.Series(dtype=float)))
                if len(spot_m) > 0 and len(ppp_interp) > 0:
                    last_spot_date = spot_m.index[-1]
                    last_ppp_date = ppp_interp.index[-1]
                    if last_spot_date > last_ppp_date:
                        # Extend PPP with forward-fill to match spot dates
                        extra_dates = spot_m.index[spot_m.index > last_ppp_date]
                        if len(extra_dates) > 0:
                            extra = pd.Series(ppp_interp.iloc[-1], index=extra_dates)
                            ppp_interp = pd.concat([ppp_interp, extra]).sort_index()
                            log(f"    ppp_factor forward-filled {len(extra_dates)} months beyond {last_ppp_date.strftime('%Y-%m')}")
                self.monthly['ppp_factor'] = ppp_interp
                log(f"    ppp_factor interpolated: {len(ppp_m)} → {len(self.monthly['ppp_factor'])} monthly points")

        # Interpolate annual GDP per capita ratio to monthly
        def _interpolate_annual(key):
            if key in self.monthly and len(self.monthly[key]) > 2:
                raw = self.monthly[key]
                if len(raw) < 50:  # Annual data
                    daily = raw.resample('D').interpolate(method='linear')
                    interp = daily.resample('ME').last().dropna()
                    # Forward-fill to match spot dates
                    spot_m = self.monthly.get('ptax', self.monthly.get('spot', pd.Series(dtype=float)))
                    if len(spot_m) > 0 and len(interp) > 0:
                        last_spot = spot_m.index[-1]
                        last_data = interp.index[-1]
                        if last_spot > last_data:
                            extra = spot_m.index[spot_m.index > last_data]
                            if len(extra) > 0:
                                interp = pd.concat([interp, pd.Series(interp.iloc[-1], index=extra)]).sort_index()
                    self.monthly[key] = interp
                    log(f"    {key} interpolated: {len(raw)} → {len(interp)} monthly points")

        _interpolate_annual('gdppc_ratio')
        _interpolate_annual('ca_pct_gdp')
        _interpolate_annual('trade_openness')

        return self

    def compute_instrument_returns(self):
        """
        Compute monthly returns for each instrument.
        Convention: positive return = position makes money.
        """
        log("\n  Computing instrument returns...")

        # --- CDI (cash return) ---
        # Use selic_over (BCB 4189, annual % rate) as primary source
        # selic_target (BCB 11) is a daily rate in decimal, NOT suitable for monthly CDI
        selic = self.monthly.get('selic_over', pd.Series(dtype=float))
        if len(selic) == 0:
            selic = self.monthly.get('selic_target', pd.Series(dtype=float))
        if len(selic) > 0:
            # Monthly CDI return from annual SELIC rate (% p.a.)
            self.instrument_returns['cash'] = ((1 + selic / 100) ** (1/12)) - 1
            log(f"    cash (CDI): {len(self.instrument_returns['cash'])} months, avg={self.instrument_returns['cash'].mean()*100:.3f}% monthly")

        # --- FX NDF 1M (long USD) ---
        # ret_fx = spot_return - carry_cost
        # Carry cost = cupom cambial (onshore USD rate) from BCB Swap DI x Dólar
        # v2.3: Prefer PTAX (BCB, starts 2000) over Yahoo USDBRL (starts 2010)
        spot_m = self.monthly.get('ptax', pd.Series(dtype=float))
        if len(spot_m) == 0:
            spot_m = self.monthly.get('spot', pd.Series(dtype=float))

        if len(spot_m) > 12:
            spot_ret = spot_m.pct_change()  # Δspot/spot (positive = USD appreciates)

            # v2.3: Cupom cambial from Swap DI x Dólar 30d (BCB 7811, 1991-present)
            # This is the onshore USD interest rate implied by the FX swap market
            # The forward premium = (DI rate - cupom cambial) / 12 approximately
            # For NDF carry: cost of holding long USD = cupom cambial / 12
            cupom_1m = self.monthly.get('fx_cupom_1m', pd.Series(dtype=float))
            
            if len(cupom_1m) > 12:
                # Cupom cambial is in % p.a. → convert to monthly carry cost
                # NDF carry cost = cupom / 100 / 12 (monthly)
                fwd_premium = cupom_1m / 100 / 12
                common = spot_ret.index.intersection(fwd_premium.index)
                fx_ret = spot_ret.reindex(common) - fwd_premium.shift(1).reindex(common)
                self.instrument_returns['fx'] = fx_ret.dropna()
                log(f"    fx: using cupom cambial (Swap DI x Dólar 30d) for carry, {len(common)} months")
            else:
                # Fallback: DI-UST proxy
                di_short = self.monthly.get('di_3m', self.monthly.get('di_1y', pd.Series(dtype=float)))
                ust_short = self.monthly.get('ust_2y', pd.Series(dtype=float))
                if len(di_short) > 12 and len(ust_short) > 12:
                    proxy_common = spot_ret.index.intersection(di_short.index).intersection(ust_short.index)
                    fwd_premium = (di_short.reindex(proxy_common) - ust_short.reindex(proxy_common)) / 100 / 12
                    fx_ret = spot_ret.reindex(proxy_common) - fwd_premium.shift(1).reindex(proxy_common)
                    self.instrument_returns['fx'] = fx_ret.dropna()
                    log(f"    fx: using DI-UST proxy for carry (no cupom cambial data)")
                else:
                    self.instrument_returns['fx'] = spot_ret.dropna()
                    log(f"    fx: spot return only (no carry data)")
            log(f"    fx (NDF 1M long USD): {len(self.instrument_returns['fx'])} months")

        # --- BR_FRONT: receiver 1Y (long duration = benefit from yield decline) ---
        # pnl ≈ -Δy * DV01 + carry_roll
        # For receiver: positive when yields fall
        di_1y = self.monthly.get('di_1y', pd.Series(dtype=float))
        if len(di_1y) > 12:
            dy = di_1y.diff()  # change in yield (percentage points)
            duration_1y = 1.0  # approximate modified duration
            # Carry: yield level / 12 (monthly carry from being receiver)
            carry_1y = di_1y.shift(1) / 100 / 12
            # Rolldown: approximate from curve slope (3M to 1Y)
            di_3m = self.monthly.get('di_3m', pd.Series(dtype=float))
            rolldown_1y = pd.Series(0.0, index=di_1y.index)
            if len(di_3m) > 12:
                slope = (di_1y - di_3m.reindex(di_1y.index)) / 100
                rolldown_1y = (slope.shift(1) * (9/12) / 12).fillna(0)  # v3.9.1: fillna(0) where di_3m unavailable

            # Receiver return: -Δy * duration + carry + rolldown
            # But we need to subtract CDI since this is an overlay
            # Actually, for the overlay, the carry IS the excess carry over CDI
            selic_m = self.monthly.get('selic_over', pd.Series(dtype=float))
            if len(selic_m) == 0:
                selic_m = self.monthly.get('selic_target', pd.Series(dtype=float))
            excess_carry = pd.Series(0.0, index=di_1y.index)
            if len(selic_m) > 0:
                # Excess carry = (DI_1Y - SELIC) / 12 (annualized spread, monthly)
                excess_carry = (di_1y - selic_m.reindex(di_1y.index)).fillna(0) / 100 / 12

            ret_front = (-dy / 100 * duration_1y) + excess_carry.shift(1) + rolldown_1y
            self.instrument_returns['front'] = winsorize(ret_front.dropna())
            log(f"    front (receiver 1Y): {len(self.instrument_returns['front'])} months")

        # --- BR_BELLY: receiver 5Y ---
        di_5y = self.monthly.get('di_5y', pd.Series(dtype=float))
        if len(di_5y) > 12:
            dy = di_5y.diff()
            duration_5y = 4.5  # approximate
            di_2y = self.monthly.get('di_2y', di_1y if len(di_1y) > 0 else pd.Series(dtype=float))
            rolldown_5y = pd.Series(0.0, index=di_5y.index)
            if len(di_2y) > 12:
                slope = (di_5y - di_2y.reindex(di_5y.index)) / 100
                rolldown_5y = (slope.shift(1) * (3/5) / 12).fillna(0)  # v3.9.1: fillna(0) where di_2y unavailable

            excess_carry_5y = pd.Series(0.0, index=di_5y.index)
            if len(selic) > 0:
                excess_carry_5y = (di_5y - selic.reindex(di_5y.index)).fillna(0) / 100 / 12

            ret_belly = (-dy / 100 * duration_5y) + excess_carry_5y.shift(1) + rolldown_5y
            self.instrument_returns['belly'] = winsorize(ret_belly.dropna())
            log(f"    belly (receiver 5Y): {len(self.instrument_returns['belly'])} months")

        # --- BR_LONG: receiver 10Y ---
        di_10y = self.monthly.get('di_10y', pd.Series(dtype=float))
        if len(di_10y) > 12:
            dy = di_10y.diff()
            duration_10y = 7.5  # approximate
            rolldown_10y = pd.Series(0.0, index=di_10y.index)
            if len(di_5y) > 12:
                slope = (di_10y - di_5y.reindex(di_10y.index)) / 100
                rolldown_10y = (slope.shift(1) * (5/10) / 12).fillna(0)  # v3.9.1: fillna(0) where di_5y unavailable

            excess_carry_10y = pd.Series(0.0, index=di_10y.index)
            if len(selic) > 0:
                excess_carry_10y = (di_10y - selic.reindex(di_10y.index)).fillna(0) / 100 / 12

            ret_long = (-dy / 100 * duration_10y) + excess_carry_10y.shift(1) + rolldown_10y
            self.instrument_returns['long'] = winsorize(ret_long.dropna())
            log(f"    long (receiver 10Y): {len(self.instrument_returns['long'])} months")

        # --- Hard Currency Sovereign (spread DV01) ---
        embi = self.monthly.get('embi_spread', pd.Series(dtype=float))
        ust10 = self.monthly.get('ust_10y', pd.Series(dtype=float))
        if len(embi) > 12:
            d_spread = embi.diff()  # in bps
            spread_dv01_dur = 5.0  # approximate spread duration
            # Carry: spread level / 12
            spread_carry = embi.shift(1) / 10000 / 12  # bps to decimal, monthly

            # Spread return (long credit = benefit from spread tightening)
            ret_hard_spread = (-d_spread / 10000 * spread_dv01_dur) + spread_carry

            # Treasury component (if not hedged)
            ret_hard_ust = pd.Series(0.0, index=embi.index)
            if len(ust10) > 12:
                d_ust = ust10.diff()
                ust_dur = 8.0
                ret_hard_ust = -d_ust.reindex(embi.index).fillna(0) / 100 * ust_dur

            # Total hard currency return (spread + treasury, unhedged)
            ret_hard = ret_hard_spread + ret_hard_ust * 0.0  # Start with spread-only (hedged)
            self.instrument_returns['hard'] = winsorize(ret_hard.dropna())
            log(f"    hard (sovereign spread): {len(self.instrument_returns['hard'])} months")


        # --- NTN-B (Cupom de Inflação) — Real yield returns ---
        ntnb_5y = self.monthly.get('tesouro_ntnb_5y', self.monthly.get('ntnb_5y', pd.Series(dtype=float)))
        if len(ntnb_5y) > 12:
            d_real_yield = ntnb_5y.diff()  # change in real yield (%)
            ntnb_dur = 4.5  # approximate modified duration for 5Y NTN-B
            # Carry: real yield / 12 (monthly carry from holding NTN-B)
            ntnb_carry = ntnb_5y.shift(1) / 100 / 12  # percent to decimal, monthly
            # Return: benefit from real yield decline + carry
            ret_ntnb = (-d_real_yield / 100 * ntnb_dur) + ntnb_carry
            self.instrument_returns['ntnb'] = winsorize(ret_ntnb.dropna())
            log(f"    ntnb (NTN-B real yield): {len(self.instrument_returns['ntnb'])} months")
        # Build aligned return DataFrame
        self._build_return_df()
        return self

    def _build_return_df(self):
        """Build aligned monthly return DataFrame for all instruments.
        v3.9.1: All core instruments must have real data — no zero-filling.
        Uses training_window=36 (instead of 60) to maximize backtest coverage
        while maintaining data integrity across all asset classes.
        
        Hard currency (EMBI-based) is optional — fill with 0 if data ends early,
        since it's a separate asset class that doesn't distort the DI-based instruments.
        """
        instruments = ['fx', 'front', 'belly', 'long', 'hard', 'ntnb']
        core_instruments = ['fx', 'front', 'belly', 'long']  # Must have real data
        frames = {}
        for inst in instruments:
            if inst in self.instrument_returns:
                frames[inst] = self.instrument_returns[inst]

        if frames:
            full_df = pd.DataFrame(frames)
            
            # Require all core instruments to have real data (no zero-filling)
            core_cols = [c for c in core_instruments if c in full_df.columns]
            if core_cols:
                aligned = full_df.dropna(subset=core_cols)
                # Only fill NaN for non-core instruments (hard) with 0
                for col in aligned.columns:
                    if col not in core_cols:
                        nan_count = aligned[col].isna().sum()
                        if nan_count > 0:
                            log(f"    {col}: {nan_count} NaN months filled with 0 (non-core instrument)")
                            aligned[col] = aligned[col].fillna(0)
                self.ret_df = aligned
            else:
                self.ret_df = full_df.dropna()

            log(f"\n  Aligned return matrix: {len(self.ret_df)} months x {len(self.ret_df.columns)} instruments")
            log(f"  Period: {self.ret_df.index[0].strftime('%Y-%m')} → {self.ret_df.index[-1].strftime('%Y-%m')}")

            # Summary stats
            for col in self.ret_df.columns:
                ann_ret = self.ret_df[col].mean() * 12 * 100
                ann_vol = self.ret_df[col].std() * np.sqrt(12) * 100
                sr = ann_ret / ann_vol if ann_vol > 0 else 0
                log(f"    {col:8s}: ann_ret={ann_ret:>6.2f}%, ann_vol={ann_vol:>6.2f}%, SR={sr:>5.2f}")
        else:
            self.ret_df = pd.DataFrame()


# ============================================================
# 2. FEATURE ENGINE
# ============================================================
class FeatureEngine:
    """Build features: Z-scores, valuation, carry, half-life signals."""

    def __init__(self, data_layer, config=None):
        self.dl = data_layer
        self.cfg = config or DEFAULT_CONFIG
        self.features = {}  # Dict of pd.Series, keyed by feature name
        self.feature_df = None  # Aligned DataFrame

    def build_all(self):
        log("\n" + "=" * 60)
        log("FEATURE ENGINE v2.2")
        log("=" * 60)

        self._build_z_scores()
        self._build_fx_valuation()
        self._build_carry()
        self._build_cip_basis()
        self._build_beer_cointegration()
        self._build_reer_gap()
        self._build_term_premium()
        self._build_breakeven_decomposition()
        self._build_fiscal_premium()
        self._build_composite_equilibrium()
        self._build_feature_df()
        return self

    def _z_score_rolling(self, series, window=None, floor=None):
        """Rolling Z-score with floor on std."""
        w = window or self.cfg['standardization_window_months']
        f = floor or self.cfg['std_floor']
        mean_r = series.rolling(w, min_periods=max(24, w // 2)).mean()
        std_r = series.rolling(w, min_periods=max(24, w // 2)).std()
        std_r = std_r.clip(lower=f)
        z = (series - mean_r) / std_r
        return winsorize(z.dropna())

    def _build_z_scores(self):
        """Build Z-score features from macro variables."""
        log("\n  Building Z-score features...")
        m = self.dl.monthly

        # Z_dxy
        if 'dxy' in m and len(m['dxy']) > 24:
            self.features['Z_dxy'] = self._z_score_rolling(m['dxy'])

        # Z_vix
        if 'vix' in m and len(m['vix']) > 24:
            self.features['Z_vix'] = self._z_score_rolling(m['vix'])

        # Z_cds_br
        if 'cds_5y' in m and len(m['cds_5y']) > 24:
            self.features['Z_cds_br'] = self._z_score_rolling(m['cds_5y'])
        elif 'embi_spread' in m and len(m['embi_spread']) > 24:
            self.features['Z_cds_br'] = self._z_score_rolling(m['embi_spread'])

        # Z_real_diff = (DI_1Y - IPCA_exp) - (UST_2Y - US_CPI_exp)
        di1y = m.get('di_1y', pd.Series(dtype=float))
        ipca_exp = m.get('ipca_exp', pd.Series(dtype=float))
        ust2y = m.get('ust_2y', pd.Series(dtype=float))
        us_cpi = m.get('us_cpi_exp', pd.Series(dtype=float))
        if all(len(s) > 24 for s in [di1y, ipca_exp, ust2y, us_cpi]):
            common = di1y.index
            for s in [ipca_exp, ust2y, us_cpi]:
                common = common.intersection(s.index)
            br_real = di1y.reindex(common) - ipca_exp.reindex(common)
            us_real = ust2y.reindex(common) - us_cpi.reindex(common)
            real_diff = br_real - us_real
            self.features['Z_real_diff'] = self._z_score_rolling(real_diff)

        # Z_infl_surprise = IPCA_yoy - IPCA_exp
        ipca_yoy = m.get('ipca_yoy', pd.Series(dtype=float))
        if len(ipca_yoy) > 24 and len(ipca_exp) > 24:
            common = ipca_yoy.index.intersection(ipca_exp.index)
            surprise = ipca_yoy.reindex(common) - ipca_exp.reindex(common)
            self.features['Z_infl_surprise'] = self._z_score_rolling(surprise)

        # Z_fiscal = zscore(debt_gdp) + zscore(cds_5y)
        debt = m.get('debt_gdp', pd.Series(dtype=float))
        cds = m.get('cds_5y', m.get('embi_spread', pd.Series(dtype=float)))
        if len(debt) > 24 and len(cds) > 24:
            z_debt = self._z_score_rolling(debt)
            z_cds = self._z_score_rolling(cds)
            common = z_debt.index.intersection(z_cds.index)
            self.features['Z_fiscal'] = (z_debt.reindex(common) + z_cds.reindex(common)) / 2

        # Z_tot (terms of trade)
        tot = m.get('tot', pd.Series(dtype=float))
        if len(tot) > 24:
            self.features['Z_tot'] = self._z_score_rolling(tot)

        # Z_hy_spread (US high yield spread — risk appetite)
        hy = m.get('us_hy_spread', pd.Series(dtype=float))
        if len(hy) > 24:
            self.features['Z_hy_spread'] = self._z_score_rolling(hy)

        # Z_ewz (EWZ equity returns — BR risk appetite)
        ewz = m.get('ewz', pd.Series(dtype=float))
        if len(ewz) > 24:
            ewz_ret = ewz.pct_change().dropna()
            self.features['Z_ewz'] = self._z_score_rolling(ewz_ret)

        # Z_iron_ore (iron ore — commodity/ToT proxy)
        iron = m.get('iron_ore', pd.Series(dtype=float))
        if len(iron) > 24:
            iron_ret = iron.pct_change().dropna()
            self.features['Z_iron_ore'] = self._z_score_rolling(iron_ret)

        # Z_bop (current account balance — external vulnerability)
        bop = m.get('bop_current', pd.Series(dtype=float))
        if len(bop) > 24:
            self.features['Z_bop'] = self._z_score_rolling(bop)

        # ---- v3.7 Additional Variables ----

        # Z_focus_fx (Focus survey USDBRL 12m expectation — sentiment/positioning)
        focus_fx = m.get('focus_fx_12m', pd.Series(dtype=float))
        if len(focus_fx) > 24:
            # Compute surprise: actual spot vs Focus expectation
            spot_m = m.get('ptax', m.get('spot', pd.Series(dtype=float)))
            if len(spot_m) > 24:
                common = focus_fx.index.intersection(spot_m.index)
                if len(common) > 24:
                    fx_surprise = (spot_m.reindex(common) - focus_fx.reindex(common)) / focus_fx.reindex(common)
                    self.features['Z_focus_fx'] = self._z_score_rolling(fx_surprise.dropna())
                    log(f"    Z_focus_fx: {len(self.features['Z_focus_fx'])} months")

        # Z_cftc_brl (CFTC net speculative positioning — crowding/sentiment)
        cftc = m.get('cftc_brl_net_spec', pd.Series(dtype=float))
        if len(cftc) > 24:
            self.features['Z_cftc_brl'] = self._z_score_rolling(cftc)
            log(f"    Z_cftc_brl: {len(self.features['Z_cftc_brl'])} months")

        # Z_idp_flow (IDP — foreign direct investment, structural flow)
        idp = m.get('idp_flow', pd.Series(dtype=float))
        if len(idp) > 24:
            # Use 12m rolling sum for smoother signal
            idp_12m = idp.rolling(12, min_periods=6).sum()
            self.features['Z_idp_flow'] = self._z_score_rolling(idp_12m.dropna())
            log(f"    Z_idp_flow: {len(self.features['Z_idp_flow'])} months")

        # Z_portfolio_flow (portfolio flows — hot money, risk appetite)
        port_flow = m.get('portfolio_flow', pd.Series(dtype=float))
        if len(port_flow) > 24:
            # Use 6m rolling sum for more responsive signal
            port_6m = port_flow.rolling(6, min_periods=3).sum()
            self.features['Z_portfolio_flow'] = self._z_score_rolling(port_6m.dropna())
            log(f"    Z_portfolio_flow: {len(self.features['Z_portfolio_flow'])} months")

        for k, v in self.features.items():
            log(f"    {k:25s}: {len(v)} months")

    def _build_fx_valuation(self):
        """FX fair value in log-space with half-life mean reversion."""
        log("\n  Building FX valuation signal...")
        # Prefer PTAX (BCB, starts 2000) over Yahoo spot (starts 2010) for longer history
        spot_m = self.dl.monthly.get('ptax', self.dl.monthly.get('spot', pd.Series(dtype=float)))
        if len(spot_m) < 36:
            log("    Insufficient spot data")
            return

        # PPP fair value
        ppp = self.dl.monthly.get('ppp_factor', pd.Series(dtype=float))
        reer = self.dl.monthly.get('reer', pd.Series(dtype=float))

        # Build fair value components
        fv_components = {}

        # PPP component
        if len(ppp) > 24:
            common = spot_m.index.intersection(ppp.index)
            fv_components['ppp'] = ppp.reindex(common)

        # BEER component (from REER): if REER is high, BRL is expensive → fair USD is lower
        if len(reer) > 36:
            reer_m = reer
            reer_mean = reer_m.rolling(60, min_periods=36).mean()
            # BEER fair value: spot adjusted by REER deviation
            common = spot_m.index.intersection(reer_m.index)
            reer_ratio = reer_m.reindex(common) / reer_mean.reindex(common)
            fv_components['beer'] = spot_m.reindex(common) / reer_ratio

        # Cyclical component: based on real rate differential
        z_real_diff = self.features.get('Z_real_diff', pd.Series(dtype=float))
        if len(z_real_diff) > 24:
            # Higher real diff → BRL should appreciate → lower fair USDBRL
            common = spot_m.index.intersection(z_real_diff.index)
            # Cyclical adjustment: spot * exp(-beta * Z_real_diff)
            beta_cyc = self.cfg.get('fx_cyclical_beta', 0.05)
            fv_components['cyc'] = spot_m.reindex(common) * np.exp(-beta_cyc * z_real_diff.reindex(common))

        # --- Balassa-Samuelson adjusted PPP ---
        # PPP_BS = PPP_raw * (GDP_pc_US / GDP_pc_BR)^beta
        # beta = 0.35 (cross-section Penn effect elasticity for EM, literature standard)
        gdppc_ratio = self.dl.monthly.get('gdppc_ratio', pd.Series(dtype=float))
        if len(ppp) > 24 and len(gdppc_ratio) > 10:
            common_bs = ppp.index.intersection(gdppc_ratio.index).intersection(spot_m.index)
            if len(common_bs) > 12:
                bs_beta = self.cfg.get('bs_beta', 0.35)
                prod_ratio = (1.0 / gdppc_ratio.reindex(common_bs))  # US/BR ratio
                ppp_bs = ppp.reindex(common_bs) * (prod_ratio ** bs_beta)
                fv_components['ppp_bs'] = ppp_bs
                log(f"    ppp_bs (Balassa-Samuelson): {len(ppp_bs)} months, beta={bs_beta}, last={ppp_bs.iloc[-1]:.4f}")

        # --- FEER (Fundamental Equilibrium Exchange Rate) ---
        # FEER = spot * (1 + (CA_target - CA_actual) / (elasticity * trade_openness))
        ca_pct = self.dl.monthly.get('ca_pct_gdp', pd.Series(dtype=float))
        trade_open = self.dl.monthly.get('trade_openness', pd.Series(dtype=float))
        if len(ca_pct) > 10 and len(trade_open) > 10:
            ca_target = self.cfg.get('feer_ca_target', -2.0)  # % of GDP (sustainable)
            feer_elasticity = self.cfg.get('feer_elasticity', 0.7)  # Marshall-Lerner
            common_feer = spot_m.index.intersection(ca_pct.index).intersection(trade_open.index)
            if len(common_feer) > 12:
                ca_gap = (ca_pct.reindex(common_feer) - ca_target) / 100.0
                trade_frac = trade_open.reindex(common_feer) / 100.0
                reer_adj = -ca_gap / (feer_elasticity * trade_frac)
                feer = spot_m.reindex(common_feer) * (1 + reer_adj)
                fv_components['feer'] = feer
                log(f"    feer: {len(feer)} months, CA_target={ca_target}%, elasticity={feer_elasticity}, last={feer.iloc[-1]:.4f}")

        if not fv_components:
            log("    No fair value components available")
            return

        # Store each component's timeseries with its OWN index (not truncated to intersection)
        # This prevents BEER from being flat when PPP data ends earlier
        if 'ppp' in fv_components:
            ppp_vals = fv_components['ppp']
            valid_ppp = ppp_vals[ppp_vals > 0]
            self._ppp_fair = float(valid_ppp.iloc[-1]) if len(valid_ppp) > 0 else 0
            self.features['ppp_fair_ts'] = ppp_vals
            log(f"    ppp_fair_ts: {len(ppp_vals)} months, last={ppp_vals.iloc[-1]:.4f}")
        else:
            self._ppp_fair = 0

        if 'ppp_bs' in fv_components:
            ppp_bs_vals = fv_components['ppp_bs']
            valid_ppp_bs = ppp_bs_vals[ppp_bs_vals > 0]
            self._ppp_bs_fair = float(valid_ppp_bs.iloc[-1]) if len(valid_ppp_bs) > 0 else 0
            self.features['ppp_bs_fair_ts'] = ppp_bs_vals
            log(f"    ppp_bs_fair_ts: {len(ppp_bs_vals)} months, last={ppp_bs_vals.iloc[-1]:.4f}")
        else:
            self._ppp_bs_fair = 0

        if 'feer' in fv_components:
            feer_vals = fv_components['feer']
            valid_feer = feer_vals[feer_vals > 0]
            self._feer_fair = float(valid_feer.iloc[-1]) if len(valid_feer) > 0 else 0
            self.features['feer_fair_ts'] = feer_vals
            log(f"    feer_fair_ts: {len(feer_vals)} months, last={feer_vals.iloc[-1]:.4f}")
        else:
            self._feer_fair = 0

        if 'beer' in fv_components:
            beer_vals = fv_components['beer']
            valid_beer = beer_vals[beer_vals > 0]
            self._beer_fair = float(valid_beer.iloc[-1]) if len(valid_beer) > 0 else 0
            self.features['beer_fair_ts'] = beer_vals
            log(f"    beer_fair_ts: {len(beer_vals)} months, last={beer_vals.iloc[-1]:.4f}")
        else:
            self._beer_fair = 0

        # Combine in log-space using UNION of dates (not intersection)
        # For each date, use whichever components are available with re-normalized weights
        weights = self.cfg.get('fx_fv_weights', {'beer': 1.0})

        # Build union of all component dates that also exist in spot
        all_dates = pd.DatetimeIndex([])
        for comp in fv_components.values():
            all_dates = all_dates.union(comp.index)
        union_idx = spot_m.index.intersection(all_dates).sort_values()

        if len(union_idx) < 24:
            log(f"    Insufficient union dates: {len(union_idx)}")
            return

        # For each date, compute weighted log-FV using available components
        fx_fair_vals = []
        for dt in union_idx:
            log_fv = 0.0
            total_w = 0.0
            for name, comp in fv_components.items():
                if dt in comp.index:
                    val = comp.loc[dt]
                    if val > 0:
                        w = weights.get(name, 0.0)  # Only include components with explicit weights
                        log_fv += w * np.log(val)
                        total_w += w
            if total_w > 0:
                fx_fair_vals.append(np.exp(log_fv / total_w))
            else:
                fx_fair_vals.append(np.nan)

        fx_fair = pd.Series(fx_fair_vals, index=union_idx).dropna()
        self.features['fx_fair'] = fx_fair

        # Valuation signal: val_fx = log(FX_fair / spot)
        val_fx = np.log(fx_fair / spot_m.reindex(fx_fair.index))
        self.features['val_fx'] = val_fx

        # Half-life mean reversion signal
        hl = self.cfg['valuation_half_life_months']['fx']
        k_fx = math.log(2) / hl
        mu_fx_val = k_fx * val_fx
        self.features['mu_fx_val'] = mu_fx_val

        # Store latest fair values
        self._fx_fair = float(fx_fair.iloc[-1])
        self.features['fx_fair_ts'] = fx_fair

        log(f"    fx_fair: {len(fx_fair)} months, current={fx_fair.iloc[-1]:.4f}")
        log(f"    val_fx: mean={val_fx.mean():.4f}, current={val_fx.iloc[-1]:.4f}")
        log(f"    mu_fx_val: mean={mu_fx_val.mean()*100:.2f}%, current={mu_fx_val.iloc[-1]*100:.2f}%")

    def _build_carry(self):
        """Build carry features for each instrument."""
        log("\n  Building carry features...")
        m = self.dl.monthly

        # FX carry (long USD perspective)
        # carry_fx_longUSD = -log(fwd_1m / spot) ≈ -(DI_short - UST_short) / 12
        di_short = m.get('di_3m', m.get('di_1y', pd.Series(dtype=float)))
        ust_short = m.get('ust_2y', pd.Series(dtype=float))
        spot_m = m.get('spot', m.get('ptax', pd.Series(dtype=float)))

        if len(di_short) > 12 and len(ust_short) > 12:
            common = di_short.index.intersection(ust_short.index)
            # Carry for long USD = -(BR rate - US rate) / 12
            # Negative carry for long USD when BR rates > US rates
            carry_fx = -(di_short.reindex(common) - ust_short.reindex(common)) / 100 / 12
            self.features['carry_fx'] = carry_fx
            log(f"    carry_fx: {len(carry_fx)} months, mean={carry_fx.mean()*100:.3f}%/m")

        # Rates carry: excess carry over CDI for each bucket
        selic = m.get('selic_over', pd.Series(dtype=float))
        if len(selic) == 0:
            selic = m.get('selic_target', pd.Series(dtype=float))
        for bucket, tenor_key in [('front', 'di_1y'), ('belly', 'di_5y'), ('long', 'di_10y')]:
            di = m.get(tenor_key, pd.Series(dtype=float))
            if len(di) > 12 and len(selic) > 12:
                common = di.index.intersection(selic.index)
                excess = (di.reindex(common) - selic.reindex(common)) / 100 / 12
                self.features[f'carry_{bucket}'] = excess
                log(f"    carry_{bucket}: {len(excess)} months, mean={excess.mean()*100:.3f}%/m")

        # Hard carry: spread level / 12
        # Carry DDI (cupom cambial) — use swap DI x Dólar rate
        cupom_360 = m.get('swap_dixdol_360d', pd.Series(dtype=float))
        cupom_30 = m.get('fx_cupom_1m', pd.Series(dtype=float))
        cupom_for_carry = cupom_360 if len(cupom_360) > 12 else cupom_30
        if len(cupom_for_carry) > 12:
            carry_hard = cupom_for_carry / 100 / 12  # percent to decimal, monthly
            self.features['carry_hard'] = carry_hard
            log(f"    carry_hard (cupom cambial): {len(carry_hard)} months, mean={carry_hard.mean()*100:.3f}%/m")
        else:
            embi = m.get('embi_spread', pd.Series(dtype=float))
            if len(embi) > 12:
                carry_hard = embi / 10000 / 12
                self.features['carry_hard'] = carry_hard
                log(f"    carry_hard (EMBI fallback): {len(carry_hard)} months, mean={carry_hard.mean()*100:.3f}%/m")
        # Carry NTN-B
        ntnb_5y = m.get('tesouro_ntnb_5y', m.get('ntnb_5y', pd.Series(dtype=float)))
        if len(ntnb_5y) > 12:
            carry_ntnb = ntnb_5y / 100 / 12
            self.features['carry_ntnb'] = carry_ntnb
            log(f"    carry_ntnb: {len(carry_ntnb)} months, mean={carry_ntnb.mean()*100:.3f}%/m")
        # Z-score of IPCA expectations (for NTN-B model)
        ipca_exp = m.get('ipca_exp_12m', pd.Series(dtype=float))
        if len(ipca_exp) > 24:
            self.features['Z_ipca_exp'] = self._z_score_rolling(ipca_exp)
            log(f"    Z_ipca_exp: {len(self.features['Z_ipca_exp'])} months")

    def _build_cip_basis(self):
        """
        CIP Basis: deviation from covered interest parity.
        basis = (fwd/spot) - (1+i_BR)/(1+i_USD)
        Captures funding premium distortions in BRL.
        Positive basis = USD funding premium, signals stress.
        """
        log("\n  Building CIP basis feature...")
        m = self.dl.monthly
        # Use DI swap 360D as BR 1Y rate, UST 2Y as US rate proxy
        di_swap = m.get('di_swap_360d', pd.Series(dtype=float))
        if len(di_swap) == 0:
            di_swap = m.get('di_1y', pd.Series(dtype=float))
        ust = m.get('ust_2y', pd.Series(dtype=float))
        spot = m.get('spot', m.get('ptax', pd.Series(dtype=float)))

        if all(len(s) > 24 for s in [di_swap, ust, spot]):
            common = di_swap.index.intersection(ust.index).intersection(spot.index)
            # Theoretical forward premium: (1+i_BR)/(1+i_US) - 1
            theo_fwd_premium = ((1 + di_swap.reindex(common)/100) / (1 + ust.reindex(common)/100)) - 1
            # Actual forward premium proxy: spot change + carry
            actual_fwd_premium = (di_swap.reindex(common) - ust.reindex(common)) / 100
            # CIP basis = actual - theoretical (deviation from parity)
            cip_basis = actual_fwd_premium - theo_fwd_premium
            # Z-score the basis
            self.features['Z_cip_basis'] = self._z_score_rolling(cip_basis.dropna())
            # Raw basis level (useful for FX carry adjustment)
            self.features['cip_basis'] = cip_basis.dropna()
            log(f"    Z_cip_basis: {len(self.features['Z_cip_basis'])} months")
            log(f"    cip_basis: mean={cip_basis.mean()*100:.3f}%, current={cip_basis.iloc[-1]*100:.3f}%")
        else:
            log("    Insufficient data for CIP basis")

    def _build_beer_cointegration(self):
        """
        BEER (Behavioral Equilibrium Exchange Rate) via rolling cointegration.
        log(REER) = f(ToT, BOP/GDP, real_rate_diff, productivity)
        Extract residual as misalignment signal.
        """
        log("\n  Building BEER cointegration signal...")
        m = self.dl.monthly
        reer = m.get('reer', pd.Series(dtype=float))
        tot = m.get('tot', pd.Series(dtype=float))
        bop = m.get('bop_current', pd.Series(dtype=float))
        ibc = m.get('ibc_br', pd.Series(dtype=float))

        if len(reer) < 60:
            log("    Insufficient REER data for BEER")
            return

        # Build BEER fundamentals DataFrame
        beer_vars = {'log_reer': np.log(reer)}
        if len(tot) > 24:
            beer_vars['tot'] = tot
        if len(bop) > 24:
            # Cumulative 12m BOP as % (proxy for external balance)
            beer_vars['bop_12m'] = bop.rolling(12, min_periods=6).sum()
        if len(ibc) > 24:
            # IBC-BR as productivity proxy (log level)
            beer_vars['log_ibc'] = np.log(ibc.clip(lower=1))

        # Real rate differential
        z_rd = self.features.get('Z_real_diff', pd.Series(dtype=float))
        if len(z_rd) > 24:
            beer_vars['real_diff'] = z_rd

        if len(beer_vars) < 3:  # need at least log_reer + 2 fundamentals
            log("    Insufficient fundamentals for BEER")
            return

        beer_df = pd.DataFrame(beer_vars).dropna()
        if len(beer_df) < 60:
            log(f"    Insufficient aligned data: {len(beer_df)} months")
            return

        # Rolling 60m OLS: log(REER) = a + b1*ToT + b2*BOP + b3*IBC + b4*RealDiff + eps
        window = 60
        y_col = 'log_reer'
        x_cols = [c for c in beer_df.columns if c != y_col]

        residuals = pd.Series(dtype=float, index=beer_df.index)
        for i in range(window, len(beer_df)):
            train = beer_df.iloc[i-window:i]
            y = train[y_col].values
            X = train[x_cols].values
            X = np.column_stack([np.ones(len(X)), X])
            try:
                beta = np.linalg.lstsq(X, y, rcond=None)[0]
                # Current fitted value
                x_curr = beer_df[x_cols].iloc[i].values
                x_curr = np.concatenate([[1], x_curr])
                fitted = np.dot(beta, x_curr)
                actual = beer_df[y_col].iloc[i]
                residuals.iloc[i] = actual - fitted  # positive = REER above fair value = BRL overvalued
            except Exception:
                pass

        residuals = residuals.dropna()
        if len(residuals) > 12:
            # BEER misalignment: positive = BRL overvalued (REER too high)
            # For FX signal: overvalued BRL → expect depreciation → long USD
            self.features['beer_misalignment'] = residuals
            self.features['Z_beer'] = self._z_score_rolling(residuals)
            log(f"    beer_misalignment: {len(residuals)} months")
            log(f"    Z_beer: mean={residuals.mean():.4f}, current={residuals.iloc[-1]:.4f}")
        else:
            log("    BEER estimation produced insufficient residuals")

    def _build_reer_gap(self):
        """
        REER Gap: log(REER_actual) - log(REER_trend_60m)
        Standalone valuation signal independent of BEER model.
        Positive gap = BRL overvalued relative to trend.
        """
        log("\n  Building REER gap signal...")
        m = self.dl.monthly
        reer = m.get('reer', pd.Series(dtype=float))

        if len(reer) < 60:
            log("    Insufficient REER data")
            return

        log_reer = np.log(reer)
        # HP-filter-like trend: rolling 60m mean of log(REER)
        trend = log_reer.rolling(60, min_periods=36).mean()
        gap = log_reer - trend
        gap = gap.dropna()

        if len(gap) > 12:
            self.features['reer_gap'] = gap
            self.features['Z_reer_gap'] = self._z_score_rolling(gap)
            log(f"    reer_gap: {len(gap)} months, current={gap.iloc[-1]:.4f}")
        else:
            log("    Insufficient REER gap data")

    def _build_term_premium(self):
        """
        Term Premium Proxy for BR rates.
        TP = y_long - avg(expected_short_rates)
        Approximated as: TP = DI_10Y - (n * DI_1Y - (n-1) * DI_1Y_fwd_implied) / n
        Simplified: TP ≈ DI_10Y - DI_1Y (slope as proxy)
        Enhanced: use rolling regression of yield changes on macro to extract TP.
        """
        log("\n  Building term premium proxy...")
        m = self.dl.monthly
        di_1y = m.get('di_1y', pd.Series(dtype=float))
        di_5y = m.get('di_5y', pd.Series(dtype=float))
        di_10y = m.get('di_10y', pd.Series(dtype=float))
        selic = m.get('selic_over', pd.Series(dtype=float))
        if len(selic) == 0:
            selic = m.get('selic_target', pd.Series(dtype=float))

        if all(len(s) > 24 for s in [di_1y, di_5y, di_10y, selic]):
            common = di_1y.index.intersection(di_5y.index).intersection(di_10y.index).intersection(selic.index)

            # Slope-based term premium: DI_10Y - DI_1Y
            slope_10_1 = di_10y.reindex(common) - di_1y.reindex(common)
            self.features['term_premium_slope'] = slope_10_1
            self.features['Z_term_premium'] = self._z_score_rolling(slope_10_1.dropna())

            # Forward-implied term premium: DI_5Y - expected path
            # Expected path proxy: SELIC + rolling mean of (DI_1Y - SELIC)
            rate_exp = selic.reindex(common) + (di_1y.reindex(common) - selic.reindex(common)).rolling(24, min_periods=12).mean()
            tp_5y = di_5y.reindex(common) - rate_exp
            tp_5y = tp_5y.dropna()
            if len(tp_5y) > 12:
                self.features['term_premium_5y'] = tp_5y
                self.features['Z_tp_5y'] = self._z_score_rolling(tp_5y)
                log(f"    term_premium_5y: {len(tp_5y)} months, current={tp_5y.iloc[-1]:.2f}pp")

            log(f"    term_premium_slope: {len(slope_10_1)} months, current={slope_10_1.iloc[-1]:.2f}pp")
        else:
            log("    Insufficient DI curve data for term premium")

    def _build_breakeven_decomposition(self):
        """
        Breakeven Decomposition using US data:
        y_nominal = y_real + breakeven_inflation
        breakeven = expected_inflation + inflation_risk_premium
        
        The inflation risk premium (IRP) is a key signal for rates positioning.
        """
        log("\n  Building breakeven decomposition...")
        m = self.dl.monthly
        tips_10y = m.get('us_tips_10y', pd.Series(dtype=float))
        be_10y = m.get('us_breakeven_10y', pd.Series(dtype=float))
        us_cpi_exp = m.get('us_cpi_exp', pd.Series(dtype=float))

        if all(len(s) > 24 for s in [tips_10y, be_10y]):
            common = tips_10y.index.intersection(be_10y.index)

            # Breakeven = nominal - real (already given as US_BREAKEVEN_10Y)
            # Inflation risk premium = breakeven - expected inflation
            if len(us_cpi_exp) > 12:
                common2 = common.intersection(us_cpi_exp.index)
                irp = be_10y.reindex(common2) - us_cpi_exp.reindex(common2)
                irp = irp.dropna()
                if len(irp) > 12:
                    self.features['us_irp'] = irp
                    self.features['Z_us_irp'] = self._z_score_rolling(irp)
                    log(f"    us_irp: {len(irp)} months, current={irp.iloc[-1]:.2f}pp")

            # US real yield as feature (important for EM rates)
            self.features['us_real_yield'] = tips_10y.reindex(common).dropna()
            self.features['Z_us_real_yield'] = self._z_score_rolling(tips_10y.reindex(common).dropna())
            log(f"    us_real_yield: {len(tips_10y.reindex(common).dropna())} months")

            # US breakeven level
            self.features['Z_us_breakeven'] = self._z_score_rolling(be_10y.reindex(common).dropna())
            log(f"    Z_us_breakeven: {len(be_10y.reindex(common).dropna())} months")
        else:
            log("    Insufficient US TIPS/breakeven data")

    def _build_fiscal_premium(self):
        """
        Fiscal Premium: residual from yield decomposition.
        y_nom = E[infl] + real_neutral + TP_global + fiscal_premium
        Approximated as: fiscal_premium = DI_10Y - UST_10Y - CDS_5Y/100 - breakeven_diff
        Or simpler: Z-score of (DI_10Y - UST_10Y) adjusted for CDS.
        """
        log("\n  Building fiscal premium signal...")
        m = self.dl.monthly
        di_10y = m.get('di_10y', pd.Series(dtype=float))
        ust_10y = m.get('ust_10y', pd.Series(dtype=float))
        cds = m.get('cds_5y', m.get('embi_spread', pd.Series(dtype=float)))
        primary_bal = m.get('primary_balance', pd.Series(dtype=float))
        debt = m.get('debt_gdp', pd.Series(dtype=float))

        if all(len(s) > 24 for s in [di_10y, ust_10y, cds]):
            common = di_10y.index.intersection(ust_10y.index).intersection(cds.index)

            # Yield spread over UST, adjusted for credit risk
            yield_spread = di_10y.reindex(common) - ust_10y.reindex(common)
            credit_adj = cds.reindex(common) / 100  # CDS in bps → pp
            # Fiscal premium = yield spread - credit spread
            fiscal_prem = yield_spread - credit_adj
            fiscal_prem = fiscal_prem.dropna()

            if len(fiscal_prem) > 12:
                self.features['fiscal_premium'] = fiscal_prem
                self.features['Z_fiscal_premium'] = self._z_score_rolling(fiscal_prem)
                log(f"    fiscal_premium: {len(fiscal_prem)} months, current={fiscal_prem.iloc[-1]:.2f}pp")

        # Primary balance momentum (12m change)
        if len(primary_bal) > 24:
            pb_mom = primary_bal.diff(12)
            pb_mom = pb_mom.dropna()
            if len(pb_mom) > 12:
                self.features['Z_pb_momentum'] = self._z_score_rolling(pb_mom)
                log(f"    Z_pb_momentum: {len(pb_mom)} months")

        # Debt/GDP acceleration
        if len(debt) > 24:
            debt_accel = debt.diff(12)  # 12m change in debt/GDP
            debt_accel = debt_accel.dropna()
            if len(debt_accel) > 12:
                self.features['Z_debt_accel'] = self._z_score_rolling(debt_accel)
                log(f"    Z_debt_accel: {len(debt_accel)} months")

    def _build_composite_equilibrium(self):
        """
        Composite Equilibrium Rate Framework v1.0
        Replaces the simple Taylor Rule with a 5-model composite estimator.

        Models:
          1. Fiscal-Augmented r*  — debt/GDP, primary balance, CDS, EMBI
          2. Real Rate Parity r*  — US TIPS + country risk premium
          3. Market-Implied r*    — ACM-style term structure decomposition
          4. State-Space r*       — Kalman Filter with fiscal/external channels
          5. Regime-Switching r*  — HMM regime-conditional r* (deferred to update_with_regime)

        The composite r* is combined into SELIC* via regime-dependent Taylor coefficients.
        """
        from composite_equilibrium import (
            FiscalAugmentedRStar, RealRateParityRStar,
            MarketImpliedRStar, StateSpaceRStar, CompositeEquilibriumRate
        )

        log("\n  Building Composite Equilibrium Rate (5-model framework)...")
        m = self.dl.monthly

        # === Load all required data ===
        selic = m.get('selic_over', pd.Series(dtype=float))
        if len(selic) == 0:
            selic = m.get('selic_target', pd.Series(dtype=float))
        ipca_12m = m.get('ipca_yoy', pd.Series(dtype=float))
        ipca_exp = m.get('ipca_exp', pd.Series(dtype=float))
        ibc_br = m.get('ibc_br', pd.Series(dtype=float))
        di_1y = m.get('di_1y', pd.Series(dtype=float))
        di_2y = m.get('di_2y', pd.Series(dtype=float))
        di_3y = m.get('di_3y', pd.Series(dtype=float))
        di_5y = m.get('di_5y', pd.Series(dtype=float))
        di_10y = m.get('di_10y', pd.Series(dtype=float))
        di_3m = m.get('di_3m', pd.Series(dtype=float))
        di_6m = m.get('di_6m', pd.Series(dtype=float))
        debt_gdp = m.get('debt_gdp', pd.Series(dtype=float))
        primary_bal = m.get('primary_balance', pd.Series(dtype=float))
        cds_5y = m.get('cds_5y', pd.Series(dtype=float))
        embi = m.get('embi_spread', pd.Series(dtype=float))
        us_tips_5y = m.get('us_tips_5y', pd.Series(dtype=float))
        us_tips_10y = m.get('us_tips_10y', pd.Series(dtype=float))
        vix = m.get('vix', pd.Series(dtype=float))
        bop_current = m.get('bop_current', pd.Series(dtype=float))
        tot = m.get('tot', pd.Series(dtype=float))

        # Need at minimum SELIC and IPCA
        if len(selic) < 24 or len(ipca_12m) < 24:
            log(f"    Insufficient data for equilibrium (selic={len(selic)}, ipca={len(ipca_12m)})")
            return

        # === Build inflation target series ===
        common = selic.index.intersection(ipca_12m.index)
        if len(ipca_exp) > 12:
            common = common.intersection(ipca_exp.index)
        pi_star = pd.Series(index=common, dtype=float)
        for dt in common:
            yr = dt.year
            if yr <= 2017: pi_star[dt] = 4.5
            elif yr == 2018: pi_star[dt] = 4.25
            elif yr == 2019: pi_star[dt] = 4.0
            elif yr == 2020: pi_star[dt] = 3.75
            elif yr == 2021: pi_star[dt] = 3.5
            elif yr <= 2023: pi_star[dt] = 3.25
            else: pi_star[dt] = 3.0
        self._pi_star_series = pi_star

        # === Model 1: Fiscal-Augmented r* ===
        model_results = {}
        try:
            fiscal_model = FiscalAugmentedRStar(window=60, prior_weight=0.3)
            rstar_fiscal, decomp = fiscal_model.estimate(
                selic, ipca_exp, debt_gdp, primary_bal, cds_5y, embi
            )
            if len(rstar_fiscal) > 12:
                model_results['fiscal'] = rstar_fiscal
                self._fiscal_decomposition = decomp
                log(f"    Model 1 (Fiscal): {len(rstar_fiscal)} months, current r*={rstar_fiscal.iloc[-1]:.2f}%")
            else:
                log("    Model 1 (Fiscal): insufficient data")
        except Exception as e:
            log(f"    Model 1 (Fiscal) error: {e}")

        # === Model 2: Real Rate Parity r* ===
        try:
            parity_model = RealRateParityRStar(window=60)
            rstar_parity = parity_model.estimate(
                us_tips_5y, us_tips_10y, cds_5y, embi, vix,
                debt_gdp, bop_current, tot
            )
            if len(rstar_parity) > 12:
                model_results['parity'] = rstar_parity
                log(f"    Model 2 (Parity): {len(rstar_parity)} months, current r*={rstar_parity.iloc[-1]:.2f}%")
            else:
                log("    Model 2 (Parity): insufficient data")
        except Exception as e:
            log(f"    Model 2 (Parity) error: {e}")

        # === Model 3: Market-Implied r* (ACM) ===
        try:
            acm_model = MarketImpliedRStar(n_factors=3, window=60)
            rstar_market, tp_market = acm_model.estimate(
                di_3m, di_6m, di_1y, di_2y, di_3y, di_5y, di_10y,
                ipca_exp=ipca_exp
            )
            if len(rstar_market) > 12:
                model_results['market_implied'] = rstar_market
                self._acm_term_premium = tp_market
                log(f"    Model 3 (ACM): {len(rstar_market)} months, current r*={rstar_market.iloc[-1]:.2f}%")
            else:
                log("    Model 3 (ACM): insufficient data")
        except Exception as e:
            log(f"    Model 3 (ACM) error: {e}")

        # === Model 4: State-Space r* (Kalman) ===
        try:
            kalman_model = StateSpaceRStar(window=120)
            rstar_kalman = kalman_model.estimate(
                selic, ipca_12m, ipca_exp, ibc_br, debt_gdp, cds_5y
            )
            if len(rstar_kalman) > 12:
                model_results['state_space'] = rstar_kalman
                log(f"    Model 4 (Kalman): {len(rstar_kalman)} months, current r*={rstar_kalman.iloc[-1]:.2f}%")
            else:
                log("    Model 4 (Kalman): insufficient data")
        except Exception as e:
            log(f"    Model 4 (Kalman) error: {e}")

        # Store intermediate results for regime update
        self._eq_model_results = model_results
        self._eq_selic = selic
        self._eq_ipca_12m = ipca_12m
        self._eq_ipca_exp = ipca_exp
        self._eq_ibc_br = ibc_br
        self._eq_di_1y = di_1y
        self._eq_di_5y = di_5y
        self._eq_di_10y = di_10y

        # === Initial composite (without regime — use base weights) ===
        if len(model_results) > 0:
            compositor = CompositeEquilibriumRate()
            # Use neutral regime probs for initial estimate
            neutral_probs = {'P_carry': 0.5, 'P_riskoff': 0.25, 'P_stress': 0.25}
            composite_rstar, selic_star = compositor.compute(
                model_results, neutral_probs, ipca_12m, ipca_exp,
                ibc_br, selic, pi_star
            )

            if len(selic_star) > 12:
                self._taylor_selic_star = selic_star
                self.features['taylor_selic_star'] = selic_star
                self._composite_rstar = composite_rstar
                self._compositor = compositor

                selic_c = selic.reindex(selic_star.index)
                taylor_gap = selic_c - selic_star
                self.features['taylor_gap'] = taylor_gap
                self.features['Z_taylor_gap'] = self._z_score_rolling(taylor_gap.dropna())

                log(f"    Composite r*: {composite_rstar.iloc[-1]:.2f}% (real)")
                log(f"    Composite SELIC*: {selic_star.iloc[-1]:.2f}% (nominal)")
                log(f"    Taylor gap: {taylor_gap.iloc[-1]:.2f}pp")
                log(f"    Models active: {list(model_results.keys())}")
                for name, contrib in compositor.model_contributions.items():
                    log(f"      {name}: weight={contrib['weight']:.1%}, r*={contrib['current_value']:.2f}%")

                # Fair values for rates instruments
                self._front_fair = round(float(selic_star.iloc[-1]), 2)

                # Term structure fair values using composite SELIC*
                selic_c = selic.reindex(common)
                if len(di_1y) > 12 and len(di_5y) > 12:
                    di_common = di_1y.index.intersection(di_5y.index).intersection(selic_star.index)
                    if len(di_common) > 12:
                        hist_tp_5y = (di_5y.reindex(di_common) - selic_c.reindex(di_common)).rolling(60, min_periods=24).mean()
                        if hist_tp_5y.notna().sum() > 0:
                            tp_5y_current = float(hist_tp_5y.iloc[-1]) if pd.notna(hist_tp_5y.iloc[-1]) else 1.0
                            self._belly_fair = round(float(selic_star.iloc[-1]) + tp_5y_current, 2)
                            log(f"    Belly fair (SELIC* + TP_5Y): {self._belly_fair:.2f}%")

                # === NEW: Derive ML-ready features from composite equilibrium ===
                self._build_equilibrium_ml_features(composite_rstar, selic_star, selic, di_1y, di_5y)

                if len(di_10y) > 12:
                    di10_common = di_10y.index.intersection(selic_star.index)
                    if len(di10_common) > 12:
                        hist_tp_10y = (di_10y.reindex(di10_common) - selic_c.reindex(di10_common)).rolling(60, min_periods=24).mean()
                        if hist_tp_10y.notna().sum() > 0:
                            tp_10y_current = float(hist_tp_10y.iloc[-1]) if pd.notna(hist_tp_10y.iloc[-1]) else 1.5
                            self._long_fair = round(float(selic_star.iloc[-1]) + tp_10y_current, 2)
                            log(f"    Long fair (SELIC* + TP_10Y): {self._long_fair:.2f}%")
            else:
                log("    Insufficient data for composite equilibrium")
        else:
            log("    No models produced valid r* estimates — falling back")

    def _build_equilibrium_ml_features(self, composite_rstar, selic_star, selic, di_1y, di_5y):
        """
        Build ML-ready features from the composite equilibrium framework.
        These features capture the predictive power of the r* methodology
        for instrument-level return prediction.

        Features created:
          - Z_policy_gap: z-scored SELIC - SELIC* (policy stance)
          - Z_rstar_composite: z-scored composite r* level
          - Z_rstar_momentum: z-scored 6m change in r*
          - Z_fiscal_component: z-scored fiscal component of r*
          - Z_sovereign_component: z-scored sovereign component of r*
          - Z_selic_star_gap: z-scored DI_1Y - SELIC* (market pricing vs equilibrium)
          - rstar_regime_signal: categorical signal (-1/0/+1 for accommodative/neutral/restrictive)
        """
        log("\n  Building equilibrium ML features...")

        # 1. Z_policy_gap: SELIC - SELIC* (positive = restrictive, negative = accommodative)
        if len(selic_star) > 24 and len(selic) > 24:
            common = selic.index.intersection(selic_star.index)
            policy_gap = selic.reindex(common) - selic_star.reindex(common)
            policy_gap = policy_gap.dropna()
            if len(policy_gap) > 24:
                self.features['policy_gap'] = policy_gap
                self.features['Z_policy_gap'] = self._z_score_rolling(policy_gap)
                log(f"    Z_policy_gap: {len(self.features['Z_policy_gap'])} months, current={policy_gap.iloc[-1]:.2f}pp")

        # 2. Z_rstar_composite: level of composite r* (high r* = tight financial conditions)
        if len(composite_rstar) > 24:
            self.features['rstar_composite'] = composite_rstar
            self.features['Z_rstar_composite'] = self._z_score_rolling(composite_rstar)
            log(f"    Z_rstar_composite: {len(self.features['Z_rstar_composite'])} months, current={composite_rstar.iloc[-1]:.2f}%")

        # 3. Z_rstar_momentum: 6m change in r* (rising r* = bearish for receivers)
        if len(composite_rstar) > 30:
            rstar_mom = composite_rstar.diff(6)
            rstar_mom = rstar_mom.dropna()
            if len(rstar_mom) > 24:
                self.features['rstar_momentum'] = rstar_mom
                self.features['Z_rstar_momentum'] = self._z_score_rolling(rstar_mom)
                log(f"    Z_rstar_momentum: {len(self.features['Z_rstar_momentum'])} months, current={rstar_mom.iloc[-1]:.2f}pp")

        # 4. Z_fiscal_component: fiscal contribution to r* (from Model 1 decomposition)
        if hasattr(self, '_fiscal_decomposition') and self._fiscal_decomposition:
            fiscal_comp = self._fiscal_decomposition.get('fiscal', pd.Series(dtype=float))
            if len(fiscal_comp) > 24:
                self.features['fiscal_component'] = fiscal_comp
                self.features['Z_fiscal_component'] = self._z_score_rolling(fiscal_comp)
                log(f"    Z_fiscal_component: {len(self.features['Z_fiscal_component'])} months")

            sovereign_comp = self._fiscal_decomposition.get('sovereign', pd.Series(dtype=float))
            if len(sovereign_comp) > 24:
                self.features['sovereign_component'] = sovereign_comp
                self.features['Z_sovereign_component'] = self._z_score_rolling(sovereign_comp)
                log(f"    Z_sovereign_component: {len(self.features['Z_sovereign_component'])} months")

        # 5. Z_selic_star_gap: DI_1Y - SELIC* (market pricing vs equilibrium rate)
        if len(selic_star) > 24 and len(di_1y) > 24:
            common = di_1y.index.intersection(selic_star.index)
            selic_star_gap = di_1y.reindex(common) - selic_star.reindex(common)
            selic_star_gap = selic_star_gap.dropna()
            if len(selic_star_gap) > 24:
                self.features['selic_star_gap'] = selic_star_gap
                self.features['Z_selic_star_gap'] = self._z_score_rolling(selic_star_gap)
                log(f"    Z_selic_star_gap: {len(self.features['Z_selic_star_gap'])} months, current={selic_star_gap.iloc[-1]:.2f}pp")

        # 6. rstar_regime_signal: categorical signal based on r* level
        # Restrictive (r* > 6%) = +1, Neutral (3-6%) = 0, Accommodative (r* < 3%) = -1
        if len(composite_rstar) > 24:
            rstar_signal = pd.Series(0.0, index=composite_rstar.index)
            rstar_signal[composite_rstar > 6.0] = 1.0   # Restrictive
            rstar_signal[composite_rstar < 3.0] = -1.0  # Accommodative
            # Intermediate zones: linear interpolation
            mask_high = (composite_rstar > 4.5) & (composite_rstar <= 6.0)
            rstar_signal[mask_high] = (composite_rstar[mask_high] - 4.5) / 1.5  # 0 to 1
            mask_low = (composite_rstar >= 3.0) & (composite_rstar < 4.5)
            rstar_signal[mask_low] = -(4.5 - composite_rstar[mask_low]) / 1.5  # 0 to -1
            self.features['rstar_regime_signal'] = rstar_signal
            log(f"    rstar_regime_signal: {len(rstar_signal)} months, current={rstar_signal.iloc[-1]:.2f}")

        # 7. Z_rstar_curve_gap: DI_5Y - SELIC* (medium-term pricing vs equilibrium)
        if len(selic_star) > 24 and len(di_5y) > 24:
            common = di_5y.index.intersection(selic_star.index)
            curve_gap = di_5y.reindex(common) - selic_star.reindex(common)
            curve_gap = curve_gap.dropna()
            if len(curve_gap) > 24:
                self.features['Z_rstar_curve_gap'] = self._z_score_rolling(curve_gap)
                log(f"    Z_rstar_curve_gap: {len(self.features['Z_rstar_curve_gap'])} months")

    def update_equilibrium_with_regime(self, regime_probs_dict, regime_probs_df=None):
        """
        Update the composite equilibrium with actual regime probabilities.
        Called AFTER RegimeModel.fit() in the ProductionEngine.step().

        regime_probs_dict: dict {P_carry: float, P_riskoff: float, ...}
        regime_probs_df: pd.DataFrame with full regime history (optional, for Model 5)
        """
        from composite_equilibrium import (
            RegimeSwitchingRStar, CompositeEquilibriumRate
        )

        if not hasattr(self, '_eq_model_results') or len(self._eq_model_results) == 0:
            return

        model_results = self._eq_model_results.copy()

        # === Model 5: Regime-Switching r* ===
        if regime_probs_df is not None and len(regime_probs_df) > 12:
            try:
                regime_model = RegimeSwitchingRStar(window=60)
                rstar_regime = regime_model.estimate(
                    self._eq_selic, self._eq_ipca_exp, regime_probs_df
                )
                if len(rstar_regime) > 12:
                    model_results['regime'] = rstar_regime
                    log(f"    Model 5 (Regime): {len(rstar_regime)} months, current r*={rstar_regime.iloc[-1]:.2f}%")
            except Exception as e:
                log(f"    Model 5 (Regime) error: {e}")

        # === Recompute composite with actual regime weights ===
        compositor = CompositeEquilibriumRate()
        composite_rstar, selic_star = compositor.compute(
            model_results, regime_probs_dict,
            self._eq_ipca_12m, self._eq_ipca_exp,
            self._eq_ibc_br, self._eq_selic,
            self._pi_star_series
        )

        if len(selic_star) > 12:
            self._taylor_selic_star = selic_star
            self.features['taylor_selic_star'] = selic_star
            self._composite_rstar = composite_rstar
            self._compositor = compositor

            selic_c = self._eq_selic.reindex(selic_star.index)
            taylor_gap = selic_c - selic_star
            self.features['taylor_gap'] = taylor_gap
            self.features['Z_taylor_gap'] = self._z_score_rolling(taylor_gap.dropna())

            self._front_fair = round(float(selic_star.iloc[-1]), 2)

            # Update term structure fair values
            di_5y = self._eq_di_5y
            di_10y = self._eq_di_10y
            common = selic_c.index

            if len(di_5y) > 12:
                di_common = di_5y.index.intersection(selic_star.index)
                if len(di_common) > 12:
                    hist_tp_5y = (di_5y.reindex(di_common) - selic_c.reindex(di_common)).rolling(60, min_periods=24).mean()
                    if hist_tp_5y.notna().sum() > 0:
                        tp_5y_current = float(hist_tp_5y.iloc[-1]) if pd.notna(hist_tp_5y.iloc[-1]) else 1.0
                        self._belly_fair = round(float(selic_star.iloc[-1]) + tp_5y_current, 2)

            if len(di_10y) > 12:
                di10_common = di_10y.index.intersection(selic_star.index)
                if len(di10_common) > 12:
                    hist_tp_10y = (di_10y.reindex(di10_common) - selic_c.reindex(di10_common)).rolling(60, min_periods=24).mean()
                    if hist_tp_10y.notna().sum() > 0:
                        tp_10y_current = float(hist_tp_10y.iloc[-1]) if pd.notna(hist_tp_10y.iloc[-1]) else 1.5
                        self._long_fair = round(float(selic_star.iloc[-1]) + tp_10y_current, 2)

            log(f"    Regime-updated composite r*: {composite_rstar.iloc[-1]:.2f}%")
            log(f"    Regime-updated SELIC*: {selic_star.iloc[-1]:.2f}%")
            for name, contrib in compositor.model_contributions.items():
                log(f"      {name}: weight={contrib['weight']:.1%}, r*={contrib['current_value']:.2f}%")

            # v4.0: Rebuild ML features with regime-updated r* and rebuild feature_df
            di_1y = self._eq_di_1y if hasattr(self, '_eq_di_1y') else self.dl.monthly.get('di_1y', pd.Series(dtype=float))
            di_5y = self._eq_di_5y if hasattr(self, '_eq_di_5y') else self.dl.monthly.get('di_5y', pd.Series(dtype=float))
            self._build_equilibrium_ml_features(composite_rstar, selic_star, self._eq_selic, di_1y, di_5y)
            self._build_feature_df()  # Rebuild to include updated equilibrium features

    def _build_feature_df(self):
        """Build aligned feature DataFrame."""
        if not self.features:
            self.feature_df = pd.DataFrame()
            return

        self.feature_df = pd.DataFrame(self.features)
        # Forward fill macro features (published with lag)
        self.feature_df = self.feature_df.ffill().dropna(how='all')
        log(f"\n  Feature matrix: {len(self.feature_df)} months x {len(self.feature_df.columns)} features")

    def get_features_at(self, date, feature_names=None):
        """Get feature vector at a specific date (no look-ahead)."""
        if self.feature_df is None or len(self.feature_df) == 0:
            return None
        available = self.feature_df.loc[:date]
        if len(available) == 0:
            return None
        row = available.iloc[-1]
        if feature_names:
            row = row.reindex(feature_names)
        return row


# ============================================================
# 3. ALPHA MODELS (Ridge Walk-Forward)
# ============================================================
class AlphaModels:
    """Ridge regression walk-forward per instrument."""

    FEATURE_MAP = {
        # v4.0: Enhanced with composite equilibrium features (r*, policy gap, fiscal/sovereign components)
        'fx':    ['Z_dxy', 'Z_vix', 'Z_cds_br', 'Z_real_diff', 'Z_tot', 'mu_fx_val', 'carry_fx',
                  'Z_cip_basis', 'Z_beer', 'Z_reer_gap', 'Z_hy_spread', 'Z_ewz', 'Z_iron_ore', 'Z_bop',
                  'Z_focus_fx', 'Z_cftc_brl', 'Z_idp_flow', 'Z_portfolio_flow',
                  'Z_policy_gap', 'rstar_regime_signal'],  # v4.0: +2 equilibrium features
        'front': ['Z_real_diff', 'Z_infl_surprise', 'Z_fiscal', 'carry_front',
                  'Z_term_premium', 'Z_us_real_yield', 'Z_pb_momentum', 'Z_portfolio_flow',
                  'Z_policy_gap', 'Z_rstar_composite', 'Z_rstar_momentum',
                  'Z_selic_star_gap', 'rstar_regime_signal'],  # v4.0: +5 equilibrium features
        'belly': ['Z_real_diff', 'Z_fiscal', 'Z_cds_br', 'Z_dxy', 'carry_belly',
                  'Z_term_premium', 'Z_tp_5y', 'Z_us_real_yield', 'Z_fiscal_premium', 'Z_us_breakeven',
                  'Z_portfolio_flow',
                  'Z_policy_gap', 'Z_rstar_composite', 'Z_rstar_momentum',
                  'Z_fiscal_component', 'Z_selic_star_gap', 'rstar_regime_signal',
                  'Z_rstar_curve_gap'],  # v4.0: +7 equilibrium features
        'long':  ['Z_fiscal', 'Z_dxy', 'Z_vix', 'Z_cds_br', 'carry_long',
                  'Z_term_premium', 'Z_fiscal_premium', 'Z_debt_accel', 'Z_us_real_yield',
                  'Z_portfolio_flow',
                  'Z_policy_gap', 'Z_rstar_composite', 'Z_rstar_momentum',
                  'Z_fiscal_component', 'Z_sovereign_component', 'rstar_regime_signal',
                  'Z_rstar_curve_gap'],  # v4.0: +7 equilibrium features
        'hard':  ['Z_vix', 'Z_cds_br', 'Z_fiscal', 'Z_dxy', 'carry_hard',
                  'Z_hy_spread', 'Z_us_real_yield', 'Z_ewz', 'Z_us_breakeven',
                  'Z_cftc_brl', 'Z_portfolio_flow',
                  'Z_rstar_composite', 'Z_fiscal_component', 'Z_sovereign_component',
                  'rstar_regime_signal'],  # v5.0: cupom cambial DDI
        'ntnb': ['carry_ntnb', 'Z_ipca_exp', 'Z_fiscal', 'Z_us_real_yield',
                  'Z_us_breakeven', 'Z_dxy', 'Z_vix', 'Z_cds_br',
                  'Z_rstar_composite', 'Z_fiscal_component'],  # v5.0: NTN-B model
    }

    def __init__(self, data_layer, feature_engine, config=None):
        self.dl = data_layer
        self.fe = feature_engine
        self.cfg = config or DEFAULT_CONFIG
        self.models = {}  # fitted Ridge models per instrument
        self.predictions = {}  # mu predictions per instrument

    def fit_and_predict(self, asof_date):
        """
        Fit Ridge models using data up to asof_date and predict mu for next month.
        Returns dict of {instrument: mu_prediction}.
        """
        window = self.cfg['training_window_months']
        ridge_lambda = self.cfg['ridge_lambda']
        ret_df = self.dl.ret_df
        feat_df = self.fe.feature_df

        if ret_df is None or len(ret_df) == 0 or feat_df is None or len(feat_df) == 0:
            return {}

        predictions = {}

        for inst, feat_names in self.FEATURE_MAP.items():
            if inst not in ret_df.columns:
                continue

            # Get available features
            available_feats = [f for f in feat_names if f in feat_df.columns]
            if len(available_feats) < 2:
                continue

            # Align returns and features up to asof_date
            y = ret_df[inst].loc[:asof_date]
            X = feat_df[available_feats].loc[:asof_date]

            # Align indices
            common = y.index.intersection(X.index)
            y = y.reindex(common).dropna()
            X = X.reindex(y.index).dropna()
            y = y.reindex(X.index)

            # Use training window
            # v3.8: Expanding vs fixed rolling window
            expanding = self.cfg.get('expanding_window', False)
            min_train = self.cfg.get('min_training_months', 60)
            if not expanding and len(y) > window:
                y = y.iloc[-window:]
                X = X.iloc[-window:]

            if len(y) < min(min_train, 36):
                continue

            # Winsorize
            y = winsorize(y)
            for col in X.columns:
                X[col] = winsorize(X[col])

            # Fit Ridge
            try:
                model = Ridge(alpha=ridge_lambda, fit_intercept=True)
                model.fit(X.values, y.values)
                self.models[inst] = {
                    'model': model,
                    'features': available_feats,
                    'r2': model.score(X.values, y.values),
                    'n_obs': len(y),
                }

                # Predict using latest features
                latest_feat = self.fe.get_features_at(asof_date, available_feats)
                if latest_feat is not None and not latest_feat.isna().all():
                    latest_feat = latest_feat.fillna(0)
                    mu = float(model.predict(latest_feat.values.reshape(1, -1))[0])
                    predictions[inst] = mu
            except Exception as e:
                log(f"    [{inst}] Ridge fit failed: {e}")

        self.predictions = predictions
        return predictions

    def compute_ic_rolling(self, instrument, window=36):
        """Compute rolling Information Coefficient (correlation of prediction vs realized)."""
        # This requires stored predictions over time — computed during backtest
        pass


class EnsembleAlphaModels:
    """
    v3.7: Expanded ensemble of Ridge + GBM + RandomForest + XGBoost with adaptive weights.
    Each model is fit walk-forward per instrument. Ensemble weights are
    proportional to rolling OOS weighted correlation (exponentially weighted, 24m halflife).
    """
    FEATURE_MAP = AlphaModels.FEATURE_MAP
    MODEL_NAMES = ['ridge', 'gbm', 'rf', 'xgb']  # v3.7: 4 models

    def __init__(self, data_layer, feature_engine, config=None):
        self.dl = data_layer
        self.fe = feature_engine
        self.cfg = config or DEFAULT_CONFIG
        self.models = {}  # {instrument: {model_name: model}}
        self.predictions = {}  # {instrument: mu}
        self.model_predictions = {}  # {instrument: {model_name: mu, 'ensemble': mu, 'w_*': w}}
        self.oos_history = {}  # {instrument: {model_name: [(pred, real)]}}
        self.ensemble_weights = {}  # {instrument: {model_name: w}}
        self.hp_cache = {}  # v3.7: {instrument: {model_params}} from purged k-fold CV
        # v4.2: Dual feature selection
        self.feature_selector = DualFeatureSelector({
            'enet_n_alphas': 50,
            'enet_cv_folds': 5,
            'enet_path_n_alphas': 100,
            'boruta_iterations': 30,  # reduced for speed in walk-forward
            'boruta_max_depth': 5,
            'boruta_n_estimators': 150,
            'stability_n_subsamples': 50,  # v5.1: increased from 30 for better stability
            'stability_subsample_ratio': 0.8,
        })
        self.feature_selection_results = {}  # {instrument: FeatureSelectionResult.to_dict()}
        self.selected_features = {}  # {instrument: {'lasso': [...], 'boruta': [...], 'final': [...]}}
        # v5.2: Regime-adaptive feature selection
        self._prev_dominant_regime = None  # track regime for adaptive re-selection
        self._fs_refit_count = 0  # count of feature selection refits
        self._fs_refit_cooldown = 6  # minimum months between regime-triggered refits
        self._fs_last_refit_step = -999  # step of last refit
        self._current_step = 0  # current walk-forward step

    @property
    def _regime_triggered_refit(self):
        """Check if a regime-triggered refit flag is active (set per step, consumed per instrument loop)."""
        return getattr(self, '_regime_refit_flag', False)

    def update_regime_for_feature_selection(self, regime_probs):
        """
        v5.2: Detect regime change and trigger feature re-selection.
        Called by ProductionEngine.step() before fit_and_predict().
        
        Logic:
        - Determine dominant regime from probabilities (max P_carry/P_riskoff/P_stress)
        - If dominant regime changed from previous step, set refit flag
        - Respect cooldown period (minimum 6 months between regime-triggered refits)
        - Log regime transitions for transparency
        """
        self._current_step += 1
        self._regime_refit_flag = False
        
        # Determine dominant global regime
        p_carry = regime_probs.get('P_carry', 0.33)
        p_riskoff = regime_probs.get('P_riskoff', 0.33)
        p_stress = regime_probs.get('P_stress', 0.33)
        
        regime_map = {'carry': p_carry, 'riskoff': p_riskoff, 'stress': p_stress}
        dominant = max(regime_map, key=regime_map.get)
        
        # Check for regime change
        if self._prev_dominant_regime is not None and dominant != self._prev_dominant_regime:
            # Check cooldown
            steps_since_last = self._current_step - self._fs_last_refit_step
            if steps_since_last >= self._fs_refit_cooldown:
                self._regime_refit_flag = True
                self._fs_refit_count += 1
                self._fs_last_refit_step = self._current_step
                log(f"  [FS] v5.2 Regime change: {self._prev_dominant_regime} → {dominant} "
                    f"(P_carry={p_carry:.2f}, P_riskoff={p_riskoff:.2f}, P_stress={p_stress:.2f}) "
                    f"→ triggering feature re-selection (refit #{self._fs_refit_count})")
                # Clear cached features to force re-selection for all instruments
                self.selected_features.clear()
            else:
                log(f"  [FS] v5.2 Regime change: {self._prev_dominant_regime} → {dominant} "
                    f"(cooldown: {steps_since_last}/{self._fs_refit_cooldown} months, skipping refit)")
        
        self._prev_dominant_regime = dominant

    def _run_feature_selection(self, inst, X_w, y_w, available_feats):
        """
        v4.4: Run Elastic Net + Boruta + Interactions + Stability.
        Elastic Net features → Ridge model (structural linear block).
        Boruta-confirmed features → GBM/RF/XGBoost models (non-linear block).
        """
        try:
            result = self.feature_selector.select(X_w, y_w, inst)
            self.feature_selection_results[inst] = result.to_dict()
            
            # Elastic Net features for Ridge (structural linear block)
            lasso_feats = result.enet_selected if result.enet_selected else available_feats
            # Boruta features for tree models (non-linear block)
            boruta_feats = result.boruta_confirmed + result.boruta_tentative
            boruta_feats = boruta_feats if boruta_feats else available_feats
            # Final merged features (for ensemble prediction) — includes confirmed interactions
            final_feats = result.final_features if result.final_features else available_feats
            
            self.selected_features[inst] = {
                'lasso': lasso_feats,
                'boruta': boruta_feats,
                'final': final_feats,
            }
            return lasso_feats, boruta_feats, final_feats
        except Exception as e:
            log(f"[FeatureSelection] {inst}: Failed ({e}), using all features")
            self.selected_features[inst] = {
                'lasso': available_feats,
                'boruta': available_feats,
                'final': available_feats,
            }
            return available_feats, available_feats, available_feats

    def fit_and_predict(self, asof_date):
        """
        Fit Ridge + GBM + RF + XGBoost per instrument, combine with adaptive weights.
        v4.2: Uses dual feature selection — LASSO for Ridge, Boruta for tree models.
        Returns dict of {instrument: ensemble_mu}.
        """
        window = self.cfg['training_window_months']
        ridge_lambda = self.cfg['ridge_lambda']
        ret_df = self.dl.ret_df
        feat_df = self.fe.feature_df

        if ret_df is None or len(ret_df) == 0 or feat_df is None or len(feat_df) == 0:
            return {}

        predictions = {}
        model_preds = {}

        for inst, feat_names in self.FEATURE_MAP.items():
            if inst not in ret_df.columns:
                continue

            available_feats = [f for f in feat_names if f in feat_df.columns]
            if len(available_feats) < 2:
                continue

            # Align returns and features up to asof_date
            y = ret_df[inst].loc[:asof_date]
            X = feat_df[available_feats].loc[:asof_date]
            common = y.index.intersection(X.index)
            y = y.reindex(common).dropna()
            X = X.reindex(y.index).dropna()
            y = y.reindex(X.index)

            # v3.8: Expanding vs fixed rolling window
            expanding = self.cfg.get('expanding_window', False)
            min_train = self.cfg.get('min_training_months', 60)
            if not expanding and len(y) > window:
                y = y.iloc[-window:]
                X = X.iloc[-window:]

            if len(y) < min(min_train, 36):
                continue

            # Winsorize
            y_w = winsorize(y)
            X_w = X.copy()
            for col in X_w.columns:
                X_w[col] = winsorize(X_w[col])

            # v5.2: Regime-adaptive feature selection
            # Re-select features when: (a) first time, or (b) regime change detected
            needs_reselection = inst not in self.selected_features or self._regime_triggered_refit
            if needs_reselection:
                lasso_feats, boruta_feats, final_feats = self._run_feature_selection(
                    inst, X_w, y_w, available_feats
                )
            else:
                lasso_feats = self.selected_features[inst]['lasso']
                boruta_feats = self.selected_features[inst]['boruta']
                final_feats = self.selected_features[inst]['final']

            # v4.5: Compute confirmed interaction columns on training data
            confirmed_ix = [f for f in final_feats if f.startswith('IX_')]
            if confirmed_ix:
                for feat_a, feat_b, name in INTERACTION_PAIRS:
                    ix_col = f'IX_{name}'
                    if ix_col in confirmed_ix and feat_a in X_w.columns and feat_b in X_w.columns:
                        a_std = (X_w[feat_a] - X_w[feat_a].mean()) / (X_w[feat_a].std() + 1e-10)
                        b_std = (X_w[feat_b] - X_w[feat_b].mean()) / (X_w[feat_b].std() + 1e-10)
                        X_w[ix_col] = a_std * b_std
                log(f"    [{inst}] v4.5: Added {len([c for c in confirmed_ix if c in X_w.columns])} "
                    f"confirmed interaction features to training data")

            # Get latest features for prediction (use final merged set)
            latest_feat = self.fe.get_features_at(asof_date, available_feats)
            if latest_feat is None or latest_feat.isna().all():
                continue
            latest_feat = latest_feat.fillna(0)

            # v4.5: Compute confirmed interaction columns on prediction data
            if confirmed_ix:
                for feat_a, feat_b, name in INTERACTION_PAIRS:
                    ix_col = f'IX_{name}'
                    if ix_col in confirmed_ix and feat_a in latest_feat.index and feat_b in latest_feat.index:
                        # For single-row prediction, standardize using training stats
                        if feat_a in X_w.columns and feat_b in X_w.columns:
                            a_val = (latest_feat[feat_a] - X_w[feat_a].mean()) / (X_w[feat_a].std() + 1e-10)
                            b_val = (latest_feat[feat_b] - X_w[feat_b].mean()) / (X_w[feat_b].std() + 1e-10)
                            latest_feat[ix_col] = a_val * b_val

            X_pred = latest_feat.values.reshape(1, -1)

            inst_preds = {}

            # v3.7: Use CV-optimized hyperparameters if available
            hp = self.hp_cache.get(inst, {})

            # v4.2: Build feature-specific training/prediction matrices
            # LASSO features → Ridge (structural linear block)
            # v4.5: Include confirmed interactions in both Ridge and tree models
            lasso_avail = [f for f in lasso_feats if f in X_w.columns]
            X_w_lasso = X_w[lasso_avail] if lasso_avail else X_w
            X_pred_lasso = latest_feat[lasso_avail].values.reshape(1, -1) if lasso_avail else X_pred
            # Boruta features → GBM/RF/XGBoost (non-linear block)
            boruta_avail = [f for f in boruta_feats if f in X_w.columns]
            X_w_boruta = X_w[boruta_avail] if boruta_avail else X_w
            X_pred_boruta = latest_feat[boruta_avail].values.reshape(1, -1) if boruta_avail else X_pred

            # --- Ridge (uses LASSO-selected structural features) ---
            try:
                ridge_alpha = hp.get('ridge_alpha', ridge_lambda)
                ridge = Ridge(alpha=ridge_alpha, fit_intercept=True)
                ridge.fit(X_w_lasso.values, y_w.values)
                mu_ridge = float(ridge.predict(X_pred_lasso)[0])
                inst_preds['ridge'] = mu_ridge
            except Exception:
                inst_preds['ridge'] = 0.0

            # --- GradientBoosting (uses Boruta-confirmed features) ---
            try:
                gbm_params = hp.get('gbm', {
                    'n_estimators': 100, 'max_depth': 3, 'learning_rate': 0.05,
                    'subsample': 0.8, 'min_samples_leaf': 5, 'random_state': 42,
                })
                gbm = GradientBoostingRegressor(**gbm_params)
                gbm.fit(X_w_boruta.values, y_w.values)
                mu_gbm = float(gbm.predict(X_pred_boruta)[0])
                inst_preds['gbm'] = mu_gbm
            except Exception:
                inst_preds['gbm'] = 0.0

            # --- v3.7: Random Forest (uses Boruta-confirmed features) ---
            try:
                rf_params = hp.get('rf', {
                    'n_estimators': 200, 'max_depth': 4, 'min_samples_leaf': 5,
                    'max_features': 'sqrt', 'random_state': 42, 'n_jobs': 1,
                })
                rf = RandomForestRegressor(**rf_params)
                rf.fit(X_w_boruta.values, y_w.values)
                mu_rf = float(rf.predict(X_pred_boruta)[0])
                inst_preds['rf'] = mu_rf
            except Exception:
                inst_preds['rf'] = 0.0

            # --- v3.7: XGBoost (uses Boruta-confirmed features) ---
            try:
                xgb_params = hp.get('xgb', {
                    'n_estimators': 100, 'max_depth': 3, 'learning_rate': 0.05,
                    'subsample': 0.8, 'colsample_bytree': 0.8, 'min_child_weight': 5,
                    'reg_alpha': 0.1, 'reg_lambda': 1.0, 'random_state': 42, 'verbosity': 0,
                })
                xgb_model = xgb.XGBRegressor(**xgb_params)
                xgb_model.fit(X_w_boruta.values, y_w.values)
                mu_xgb = float(xgb_model.predict(X_pred_boruta)[0])
                inst_preds['xgb'] = mu_xgb
            except Exception:
                inst_preds['xgb'] = 0.0

            # --- Adaptive Ensemble Weights (4 models) ---
            weights = self._compute_ensemble_weights(inst)
            mu_ensemble = sum(weights.get(m, 0.25) * inst_preds.get(m, 0) for m in self.MODEL_NAMES)

            predictions[inst] = mu_ensemble
            inst_preds['ensemble'] = mu_ensemble
            for m in self.MODEL_NAMES:
                inst_preds[f'w_{m}'] = weights.get(m, 0.25)
            # Backward compat: keep w_ridge, w_gbm at top level
            inst_preds['w_ridge'] = weights.get('ridge', 0.25)
            inst_preds['w_gbm'] = weights.get('gbm', 0.25)
            model_preds[inst] = inst_preds

            self.models[inst] = {f'{m}_fitted': True for m in self.MODEL_NAMES}

        self.predictions = predictions
        self.model_predictions = model_preds
        return predictions

    def _compute_ensemble_weights(self, instrument):
        """
        v3.7: Compute adaptive weights for 4 models based on rolling OOS
        weighted correlation with exponential decay (halflife 24m).
        Returns dict {model_name: weight}.
        """
        n_models = len(self.MODEL_NAMES)
        equal_w = {m: 1.0 / n_models for m in self.MODEL_NAMES}

        if instrument not in self.oos_history:
            return equal_w

        hist = self.oos_history[instrument]
        min_obs = 12

        scores = {}
        for model_name in self.MODEL_NAMES:
            if model_name not in hist or len(hist[model_name]) < min_obs:
                scores[model_name] = 0.0
                continue

            pairs = hist[model_name][-36:]  # use last 36 months
            preds = np.array([p for p, _ in pairs])
            reals = np.array([r for _, r in pairs])

            # Exponential weights (halflife 24m)
            n = len(preds)
            decay = np.exp(-np.log(2) / 24 * np.arange(n - 1, -1, -1))

            # Weighted correlation as proxy for OOS quality
            if np.std(preds) > 1e-8 and np.std(reals) > 1e-8:
                w_sum = decay.sum()
                mean_p = np.sum(decay * preds) / w_sum
                mean_r = np.sum(decay * reals) / w_sum
                cov_pr = np.sum(decay * (preds - mean_p) * (reals - mean_r)) / w_sum
                std_p = np.sqrt(np.sum(decay * (preds - mean_p) ** 2) / w_sum)
                std_r = np.sqrt(np.sum(decay * (reals - mean_r) ** 2) / w_sum)
                if std_p > 1e-8 and std_r > 1e-8:
                    scores[model_name] = max(cov_pr / (std_p * std_r), 0)
                else:
                    scores[model_name] = 0.0
            else:
                scores[model_name] = 0.0

        total = sum(scores.values())
        if total > 0:
            return {m: scores.get(m, 0) / total for m in self.MODEL_NAMES}
        else:
            return equal_w

    def update_oos_history(self, instrument, model_name, prediction, realized):
        """Track OOS predictions for adaptive weight computation."""
        if instrument not in self.oos_history:
            self.oos_history[instrument] = {}
        if model_name not in self.oos_history[instrument]:
            self.oos_history[instrument][model_name] = []
        self.oos_history[instrument][model_name].append((prediction, realized))

    def compute_ic_rolling(self, instrument, window=36):
        pass

    @staticmethod
    def purged_kfold_cv(X, y, n_splits=5, purge_gap=3, model_class=Ridge, model_params=None):
        """
        v3.7: Purged k-fold cross-validation for time series.
        Prevents look-ahead bias by:
        1. Splitting data into k chronological folds
        2. Purging `purge_gap` observations between train and test sets
        3. Never using future data to train

        Returns mean OOS R² across folds.
        """
        n = len(y)
        fold_size = n // n_splits
        if fold_size < 12:
            return 0.0  # too few observations per fold

        scores = []
        for i in range(n_splits):
            test_start = i * fold_size
            test_end = min((i + 1) * fold_size, n)

            # Train on everything BEFORE the test fold (with purge gap)
            train_end = max(0, test_start - purge_gap)
            if train_end < 24:  # need minimum training data
                continue

            X_train = X[:train_end]
            y_train = y[:train_end]
            X_test = X[test_start:test_end]
            y_test = y[test_start:test_end]

            if len(X_train) < 24 or len(X_test) < 6:
                continue

            try:
                params = model_params or {}
                model = model_class(**params)
                model.fit(X_train, y_train)
                y_pred = model.predict(X_test)

                # OOS R²
                ss_res = np.sum((y_test - y_pred) ** 2)
                ss_tot = np.sum((y_test - np.mean(y_test)) ** 2)
                r2 = 1 - ss_res / ss_tot if ss_tot > 0 else 0
                scores.append(r2)
            except Exception:
                continue

        return float(np.mean(scores)) if scores else 0.0

    def select_hyperparameters(self, X, y, inst):
        """
        v3.7: Use purged k-fold CV to select optimal hyperparameters.
        Returns dict of optimal params for each model type.
        Called periodically (every 12 months) during walk-forward.
        """
        best_params = {}

        # Ridge: select alpha
        ridge_alphas = [1.0, 5.0, 10.0, 20.0, 50.0]
        best_ridge_score = -np.inf
        best_ridge_alpha = 10.0
        for alpha in ridge_alphas:
            score = self.purged_kfold_cv(
                X, y, n_splits=5, purge_gap=3,
                model_class=Ridge, model_params={'alpha': alpha, 'fit_intercept': True}
            )
            if score > best_ridge_score:
                best_ridge_score = score
                best_ridge_alpha = alpha
        best_params['ridge_alpha'] = best_ridge_alpha

        # GBM: select n_estimators and max_depth
        gbm_configs = [
            {'n_estimators': 50, 'max_depth': 2, 'learning_rate': 0.05, 'subsample': 0.8, 'min_samples_leaf': 5, 'random_state': 42},
            {'n_estimators': 100, 'max_depth': 3, 'learning_rate': 0.05, 'subsample': 0.8, 'min_samples_leaf': 5, 'random_state': 42},
            {'n_estimators': 100, 'max_depth': 2, 'learning_rate': 0.03, 'subsample': 0.8, 'min_samples_leaf': 5, 'random_state': 42},
            {'n_estimators': 150, 'max_depth': 3, 'learning_rate': 0.03, 'subsample': 0.7, 'min_samples_leaf': 5, 'random_state': 42},
        ]
        best_gbm_score = -np.inf
        best_gbm_cfg = gbm_configs[1]  # default
        for cfg in gbm_configs:
            score = self.purged_kfold_cv(
                X, y, n_splits=5, purge_gap=3,
                model_class=GradientBoostingRegressor, model_params=cfg
            )
            if score > best_gbm_score:
                best_gbm_score = score
                best_gbm_cfg = cfg
        best_params['gbm'] = best_gbm_cfg

        # RF: select n_estimators and max_depth
        rf_configs = [
            {'n_estimators': 100, 'max_depth': 3, 'min_samples_leaf': 5, 'max_features': 'sqrt', 'random_state': 42, 'n_jobs': 1},
            {'n_estimators': 200, 'max_depth': 4, 'min_samples_leaf': 5, 'max_features': 'sqrt', 'random_state': 42, 'n_jobs': 1},
            {'n_estimators': 200, 'max_depth': 3, 'min_samples_leaf': 3, 'max_features': 'sqrt', 'random_state': 42, 'n_jobs': 1},
            {'n_estimators': 300, 'max_depth': 5, 'min_samples_leaf': 5, 'max_features': 'sqrt', 'random_state': 42, 'n_jobs': 1},
        ]
        best_rf_score = -np.inf
        best_rf_cfg = rf_configs[1]  # default
        for cfg in rf_configs:
            score = self.purged_kfold_cv(
                X, y, n_splits=5, purge_gap=3,
                model_class=RandomForestRegressor, model_params=cfg
            )
            if score > best_rf_score:
                best_rf_score = score
                best_rf_cfg = cfg
        best_params['rf'] = best_rf_cfg

        # XGBoost: select params
        xgb_configs = [
            {'n_estimators': 50, 'max_depth': 2, 'learning_rate': 0.05, 'subsample': 0.8, 'colsample_bytree': 0.8, 'min_child_weight': 5, 'reg_alpha': 0.1, 'reg_lambda': 1.0, 'random_state': 42, 'verbosity': 0},
            {'n_estimators': 100, 'max_depth': 3, 'learning_rate': 0.05, 'subsample': 0.8, 'colsample_bytree': 0.8, 'min_child_weight': 5, 'reg_alpha': 0.1, 'reg_lambda': 1.0, 'random_state': 42, 'verbosity': 0},
            {'n_estimators': 100, 'max_depth': 2, 'learning_rate': 0.03, 'subsample': 0.7, 'colsample_bytree': 0.7, 'min_child_weight': 3, 'reg_alpha': 0.5, 'reg_lambda': 2.0, 'random_state': 42, 'verbosity': 0},
            {'n_estimators': 150, 'max_depth': 3, 'learning_rate': 0.03, 'subsample': 0.8, 'colsample_bytree': 0.8, 'min_child_weight': 5, 'reg_alpha': 0.1, 'reg_lambda': 1.5, 'random_state': 42, 'verbosity': 0},
        ]
        best_xgb_score = -np.inf
        best_xgb_cfg = xgb_configs[1]  # default
        for cfg in xgb_configs:
            score = self.purged_kfold_cv(
                X, y, n_splits=5, purge_gap=3,
                model_class=xgb.XGBRegressor, model_params=cfg
            )
            if score > best_xgb_score:
                best_xgb_score = score
                best_xgb_cfg = cfg
        best_params['xgb'] = best_xgb_cfg

        log(f"    [{inst}] CV scores: Ridge(a={best_ridge_alpha})={best_ridge_score:.3f}, "
            f"GBM={best_gbm_score:.3f}, RF={best_rf_score:.3f}, XGB={best_xgb_score:.3f}")

        return best_params

    def compute_shap_importance(self, asof_date):
        """
        v3.8: Compute SHAP feature importance for each instrument using the
        latest fitted XGBoost and RF models. Returns dict of:
        {instrument: {feature_name: shap_value, ...}}
        """
        ret_df = self.dl.ret_df
        feat_df = self.fe.feature_df
        if ret_df is None or feat_df is None:
            return {}

        importance = {}
        for inst, feat_names in self.FEATURE_MAP.items():
            if inst not in ret_df.columns:
                continue
            available_feats = [f for f in feat_names if f in feat_df.columns]
            if len(available_feats) < 2:
                continue

            y = ret_df[inst].loc[:asof_date]
            X = feat_df[available_feats].loc[:asof_date]
            common = y.index.intersection(X.index)
            y = y.reindex(common).dropna()
            X = X.reindex(y.index).dropna()
            y = y.reindex(X.index)

            expanding = self.cfg.get('expanding_window', False)
            window = self.cfg['training_window_months']
            if not expanding and len(y) > window:
                y = y.iloc[-window:]
                X = X.iloc[-window:]

            if len(y) < 36:
                continue

            try:
                # Fit XGBoost for SHAP (tree-based SHAP is fast and exact)
                xgb_model = xgb.XGBRegressor(
                    n_estimators=100, max_depth=3, learning_rate=0.05,
                    subsample=0.8, colsample_bytree=0.8, verbosity=0, random_state=42
                )
                xgb_model.fit(X.values, y.values)

                # Compute SHAP values
                explainer = shap.TreeExplainer(xgb_model)
                shap_values = explainer.shap_values(X.values)

                # Mean absolute SHAP value per feature (global importance)
                mean_abs_shap = np.abs(shap_values).mean(axis=0)

                # Current SHAP (for the latest observation)
                latest_feat = self.fe.get_features_at(asof_date, available_feats)
                if latest_feat is not None and not latest_feat.isna().all():
                    latest_X = latest_feat.values.reshape(1, -1)
                    current_shap = explainer.shap_values(latest_X)[0]
                else:
                    current_shap = shap_values[-1]  # use last training observation

                inst_importance = {}
                for j, feat in enumerate(available_feats):
                    inst_importance[feat] = {
                        'mean_abs': round(float(mean_abs_shap[j]), 6),
                        'current': round(float(current_shap[j]), 6),
                        'rank': 0  # will be filled below
                    }

                # Rank by mean absolute SHAP
                sorted_feats = sorted(inst_importance.items(), key=lambda x: x[1]['mean_abs'], reverse=True)
                for rank, (feat, vals) in enumerate(sorted_feats, 1):
                    inst_importance[feat]['rank'] = rank

                importance[inst] = inst_importance
            except Exception as e:
                log(f"    SHAP failed for {inst}: {e}")
                continue

        return importance

    def compute_shap_snapshot(self, asof_date):
        """
        v3.9: Lightweight SHAP snapshot for historical tracking.
        Returns dict of {instrument: {feature: mean_abs_shap}} at a given date.
        Uses smaller n_estimators for speed since this runs many times during backtest.
        """
        ret_df = self.dl.ret_df
        feat_df = self.fe.feature_df
        if ret_df is None or feat_df is None:
            return {}

        snapshot = {}
        for inst, feat_names in self.FEATURE_MAP.items():
            if inst not in ret_df.columns:
                continue
            available_feats = [f for f in feat_names if f in feat_df.columns]
            if len(available_feats) < 2:
                continue

            y = ret_df[inst].loc[:asof_date]
            X = feat_df[available_feats].loc[:asof_date]
            common = y.index.intersection(X.index)
            y = y.reindex(common).dropna()
            X = X.reindex(y.index).dropna()
            y = y.reindex(X.index)

            expanding = self.cfg.get('expanding_window', False)
            window = self.cfg['training_window_months']
            if not expanding and len(y) > window:
                y = y.iloc[-window:]
                X = X.iloc[-window:]

            if len(y) < 36:
                continue

            try:
                xgb_model = xgb.XGBRegressor(
                    n_estimators=50, max_depth=3, learning_rate=0.05,
                    subsample=0.8, colsample_bytree=0.8, verbosity=0, random_state=42
                )
                xgb_model.fit(X.values, y.values)
                explainer = shap.TreeExplainer(xgb_model)
                shap_values = explainer.shap_values(X.values)
                mean_abs_shap = np.abs(shap_values).mean(axis=0)

                inst_snap = {}
                for j, feat in enumerate(available_feats):
                    inst_snap[feat] = round(float(mean_abs_shap[j]), 6)
                snapshot[inst] = inst_snap
            except Exception:
                continue

        return snapshot


# ============================================================
# 4. REGIME MODEL (HMM 3-State)
# ============================================================
class RegimeModel:
    """
    Two-Level Regime Model:
    Level 1 (Global): HMM 3-state on global risk observables (DXY, VIX, UST, HY spread, commodities)
    Level 2 (Domestic): HMM 2-state on BR-specific stress indicators (CDS, FX vol, fiscal, REER)
    Combined output: P_carry, P_riskoff, P_stress, P_domestic_calm, P_domestic_stress
    """

    def __init__(self, data_layer, config=None):
        self.dl = data_layer
        self.cfg = config or DEFAULT_CONFIG
        self.hmm_global = None
        self.hmm_domestic = None
        self.regime_probs = None  # DataFrame with all regime probabilities

    def fit(self, asof_date=None):
        """Fit two-level HMM regime model.
        v2.3: When asof_date is provided, only uses data up to that date
        to prevent look-ahead bias in backtest.
        """
        log("\n" + "=" * 60)
        log("REGIME MODEL v2.3 (Two-Level HMM — Expanding Window)")
        log("=" * 60)
        if asof_date is not None:
            log(f"  Fitting with data up to {asof_date} (no look-ahead)")

        m = self.dl.monthly

        # ===== LEVEL 1: GLOBAL REGIME (3-state) =====
        log("\n  Level 1: Global Regime (3-state)")
        global_obs = {}

        # G1: ΔDXY (1m change)
        dxy = m.get('dxy', pd.Series(dtype=float))
        if len(dxy) > 12:
            global_obs['d_dxy'] = dxy.pct_change()

        # G2: VIX level
        vix = m.get('vix', pd.Series(dtype=float))
        if len(vix) > 12:
            global_obs['vix'] = vix

        # G3: ΔUST10
        ust10 = m.get('ust_10y', pd.Series(dtype=float))
        if len(ust10) > 12:
            global_obs['d_ust10'] = ust10.diff()

        # G4: US HY spread (risk appetite)
        hy = m.get('us_hy_spread', pd.Series(dtype=float))
        if len(hy) > 12:
            global_obs['hy_spread'] = hy

        # G5: Commodity returns
        bcom = m.get('bcom', pd.Series(dtype=float))
        if len(bcom) > 12:
            global_obs['ret_comm'] = bcom.pct_change()

        # G6: EWZ returns (EM equity risk appetite)
        ewz = m.get('ewz', pd.Series(dtype=float))
        if len(ewz) > 12:
            global_obs['ret_ewz'] = ewz.pct_change()

        # ===== LEVEL 2: DOMESTIC REGIME (2-state) =====
        log("  Level 2: Domestic Regime (2-state)")
        domestic_obs = {}

        # D1: ΔCDS_BR
        cds = m.get('cds_5y', m.get('embi_spread', pd.Series(dtype=float)))
        if len(cds) > 12:
            domestic_obs['d_cds'] = cds.pct_change()

        # D2: FX realized vol (20d proxy from monthly)
        spot = m.get('spot', m.get('ptax', pd.Series(dtype=float)))
        if len(spot) > 12:
            fx_ret = spot.pct_change()
            domestic_obs['fx_vol'] = fx_ret.rolling(6, min_periods=3).std() * np.sqrt(12)

        # D3: Fiscal pressure (debt/GDP change)
        debt = m.get('debt_gdp', pd.Series(dtype=float))
        if len(debt) > 12:
            domestic_obs['d_debt'] = debt.diff(12)

        # D4: REER deviation from trend
        reer = m.get('reer', pd.Series(dtype=float))
        if len(reer) > 36:
            log_reer = np.log(reer)
            reer_trend = log_reer.rolling(36, min_periods=24).mean()
            domestic_obs['reer_dev'] = log_reer - reer_trend

        # D5: DI curve slope (steepness = stress indicator)
        di_1y = m.get('di_1y', pd.Series(dtype=float))
        di_10y = m.get('di_10y', pd.Series(dtype=float))
        if len(di_1y) > 12 and len(di_10y) > 12:
            common_di = di_1y.index.intersection(di_10y.index)
            domestic_obs['di_slope'] = di_10y.reindex(common_di) - di_1y.reindex(common_di)

        # D6: Policy gap (SELIC - SELIC*) — v4.0: from composite equilibrium
        # Access from feature engine if already built
        if self.dl and hasattr(self, '_feature_engine_ref') and self._feature_engine_ref:
            fe = self._feature_engine_ref
            if hasattr(fe, 'features') and 'policy_gap' in fe.features:
                pg = fe.features['policy_gap']
                if len(pg) > 12:
                    domestic_obs['policy_gap'] = pg
                    log(f"    D6: Policy gap added ({len(pg)} months)")

        # D7: Fiscal premium component of r* — v4.0
        if self.dl and hasattr(self, '_feature_engine_ref') and self._feature_engine_ref:
            fe = self._feature_engine_ref
            if hasattr(fe, 'features') and 'fiscal_component' in fe.features:
                fc = fe.features['fiscal_component']
                if len(fc) > 12:
                    domestic_obs['fiscal_premium'] = fc
                    log(f"    D7: Fiscal premium added ({len(fc)} months)")

        # Fit global HMM
        global_prob_df = self._fit_hmm(
            global_obs, n_states=3, asof_date=asof_date,
            label_col='vix', level_name='Global'
        )

        # Fit domestic HMM
        domestic_prob_df = self._fit_hmm(
            domestic_obs, n_states=2, asof_date=asof_date,
            label_col='d_cds', level_name='Domestic'
        )

        # Combine into single regime_probs DataFrame
        if global_prob_df is not None and domestic_prob_df is not None:
            common_idx = global_prob_df.index.intersection(domestic_prob_df.index)
            self.regime_probs = pd.concat([
                global_prob_df.reindex(common_idx),
                domestic_prob_df.reindex(common_idx)
            ], axis=1)
        elif global_prob_df is not None:
            self.regime_probs = global_prob_df
            # Add default domestic probs
            self.regime_probs['P_domestic_calm'] = 0.5
            self.regime_probs['P_domestic_stress'] = 0.5
        elif domestic_prob_df is not None:
            self.regime_probs = domestic_prob_df
            self.regime_probs['P_carry'] = 0.33
            self.regime_probs['P_riskoff'] = 0.33
            self.regime_probs['P_stress'] = 0.33
        else:
            log("  Both HMMs failed — using uniform priors")

        if self.regime_probs is not None and len(self.regime_probs) > 0:
            latest = self.regime_probs.iloc[-1]
            log(f"\n  Combined regime (latest):")
            for col in self.regime_probs.columns:
                log(f"    {col}: {latest.get(col, 0):.1%}")

        return self

    def _fit_hmm(self, obs_dict, n_states, asof_date, label_col, level_name):
        """Fit a single HMM and return labeled probability DataFrame.
        v2.3: Strictly filters data to asof_date to prevent look-ahead.
        """
        if len(obs_dict) < 2:
            log(f"  {level_name}: Insufficient observables ({len(obs_dict)})")
            return None

        obs_df = pd.DataFrame(obs_dict).dropna()
        if asof_date is not None:
            obs_df = obs_df.loc[:asof_date]

        if len(obs_df) < 60:
            log(f"  {level_name}: Insufficient data ({len(obs_df)} months)")
            return None

        # Standardize
        obs_std = (obs_df - obs_df.mean()) / obs_df.std().clip(lower=0.01)

        try:
            from hmmlearn.hmm import GaussianHMM
            hmm = GaussianHMM(
                n_components=n_states,
                covariance_type='full',
                n_iter=200,
                random_state=42,
                tol=0.01
            )
            hmm.fit(obs_std.values)

            probs = hmm.predict_proba(obs_std.values)
            states = hmm.predict(obs_std.values)

            if n_states == 3:
                # Label by VIX/label_col mean: lowest = carry, highest = riskoff, middle = stress
                state_means = {}
                for s in range(3):
                    mask = states == s
                    if mask.sum() > 0 and label_col in obs_df.columns:
                        state_means[s] = obs_df.loc[mask, label_col].mean()
                    else:
                        state_means[s] = s

                sorted_states = sorted(state_means.keys(), key=lambda x: state_means.get(x, 0))
                label_map = {sorted_states[0]: 'carry', sorted_states[1]: 'stress', sorted_states[2]: 'riskoff'}

                prob_df = pd.DataFrame(index=obs_df.index)
                for s, label in label_map.items():
                    prob_df[f'P_{label}'] = probs[:, s]

                if level_name == 'Global':
                    self.hmm_global = hmm

                for label in ['carry', 'riskoff', 'stress']:
                    col = f'P_{label}'
                    if col in prob_df.columns:
                        dominant = (prob_df[col] > 0.5).sum()
                        log(f"    {level_name} {label:12s}: dominant in {dominant}/{len(prob_df)} months ({dominant/len(prob_df)*100:.1f}%)")

            elif n_states == 2:
                # Label by stress indicator: higher label_col mean = stress
                state_means = {}
                for s in range(2):
                    mask = states == s
                    if mask.sum() > 0 and label_col in obs_df.columns:
                        state_means[s] = obs_df.loc[mask, label_col].mean()
                    else:
                        state_means[s] = s

                sorted_states = sorted(state_means.keys(), key=lambda x: state_means.get(x, 0))
                label_map = {sorted_states[0]: 'domestic_calm', sorted_states[1]: 'domestic_stress'}

                prob_df = pd.DataFrame(index=obs_df.index)
                for s, label in label_map.items():
                    prob_df[f'P_{label}'] = probs[:, s]

                self.hmm_domestic = hmm

                for label in ['domestic_calm', 'domestic_stress']:
                    col = f'P_{label}'
                    if col in prob_df.columns:
                        dominant = (prob_df[col] > 0.5).sum()
                        log(f"    {level_name} {label:12s}: dominant in {dominant}/{len(prob_df)} months ({dominant/len(prob_df)*100:.1f}%)")

            return prob_df

        except Exception as e:
            log(f"  {level_name} HMM fit failed: {e}")
            return None

    def get_probs_at(self, date):
        """Get regime probabilities at date."""
        defaults = {
            'P_carry': 0.33, 'P_riskoff': 0.33, 'P_stress': 0.33,
            'P_domestic_calm': 0.5, 'P_domestic_stress': 0.5
        }
        if self.regime_probs is None or len(self.regime_probs) == 0:
            return defaults
        available = self.regime_probs.loc[:date]
        if len(available) == 0:
            return defaults
        result = available.iloc[-1].to_dict()
        # Ensure all keys present
        for k, v in defaults.items():
            if k not in result:
                result[k] = v
        return result


# ============================================================
# 5. OPTIMIZER
# ============================================================
class Optimizer:
    """Mean-variance optimizer with TC, turnover penalty, factor limits."""

    def __init__(self, data_layer, config=None):
        self.dl = data_layer
        self.cfg = config or DEFAULT_CONFIG

    def optimize(self, mu, cov, prev_weights, ic_scores=None, regime_probs=None):
        """
        Optimize portfolio weights.
        mu: dict {instrument: expected_return}
        cov: covariance matrix (DataFrame)
        prev_weights: dict {instrument: previous_weight}
        ic_scores: dict {instrument: rolling IC} for dynamic budgets
        regime_probs: dict {state: probability} for regime-conditional limits
        """
        instruments = sorted(mu.keys())
        n = len(instruments)
        if n == 0:
            return {}

        mu_vec = np.array([mu.get(inst, 0) for inst in instruments])
        prev_vec = np.array([prev_weights.get(inst, 0) for inst in instruments])

        # Covariance matrix
        if cov is not None and len(cov) > 0:
            cov_mat = cov.reindex(index=instruments, columns=instruments).fillna(0).values
        else:
            # Fallback: diagonal with historical vol
            vols = []
            for inst in instruments:
                if inst in self.dl.ret_df.columns:
                    vols.append(self.dl.ret_df[inst].std())
                else:
                    vols.append(0.05)
            cov_mat = np.diag(np.array(vols) ** 2)

        gamma = self.cfg['gamma']
        tc_bps = self.cfg['transaction_costs_bps']
        turnover_pen = self.cfg['turnover_penalty_bps'] / 10000

        # v3.8: Regime-dependent transaction cost multiplier
        tc_mult = 1.0
        tc_regime_mults = self.cfg.get('tc_regime_multipliers', {})
        if regime_probs:
            # Weighted average of regime multipliers by probability
            tc_mult = sum(
                regime_probs.get(regime, 0) * tc_regime_mults.get(regime, 1.0)
                for regime in tc_regime_mults
            )
            tc_mult = max(tc_mult, 0.5)  # floor at 0.5x

        # Dynamic risk budgets by IC
        budget_scale = np.ones(n)
        if ic_scores and len(ic_scores) >= 3:
            ic_pos = np.array([max(ic_scores.get(inst, 0), 0) for inst in instruments])
            total_ic = ic_pos.sum()
            if total_ic > 0:
                budget_scale = ic_pos / total_ic * n  # Scale so sum = n
            else:
                # All ICs negative → use equal but reduced budgets
                budget_scale = np.ones(n) * 0.5

        # Objective: maximize mu·p - 0.5*gamma*p'Σp - TC - turnover
        def objective(p):
            ret = np.dot(mu_vec * budget_scale, p)
            risk = 0.5 * gamma * np.dot(p, np.dot(cov_mat, p))
            tc = sum(tc_bps.get(instruments[i], 5) / 10000 * tc_mult * abs(p[i] - prev_vec[i]) for i in range(n))
            turnover = turnover_pen * tc_mult * np.sum(np.abs(p - prev_vec))
            return -(ret - risk - tc - turnover)

        # Constraints
        constraints = []

        # Vol target
        vol_target = self.cfg['risk_targets']['overlay_vol_target_annual'] / np.sqrt(12)  # monthly
        constraints.append({
            'type': 'ineq',
            'fun': lambda p: vol_target**2 - np.dot(p, np.dot(cov_mat, p))
        })

        # Position limits — regime-conditional (v2.3)
        # Determine effective limits based on dominant regime
        base_limits = self.cfg['position_limits']
        regime_limits_cfg = self.cfg.get('regime_position_limits', {})
        
        if regime_probs and regime_limits_cfg:
            # Probability-weighted blending of regime-specific limits
            p_carry = regime_probs.get('P_carry', 0.33)
            p_riskoff = regime_probs.get('P_riskoff', 0.33)
            p_stress = regime_probs.get('P_stress', 0.33)
            
            carry_lim = regime_limits_cfg.get('carry', base_limits)
            riskoff_lim = regime_limits_cfg.get('riskoff', base_limits)
            stress_lim = regime_limits_cfg.get('stress', base_limits)
            
            limits = {}
            for key in base_limits:
                limits[key] = (
                    p_carry * carry_lim.get(key, base_limits[key]) +
                    p_riskoff * riskoff_lim.get(key, base_limits[key]) +
                    p_stress * stress_lim.get(key, base_limits[key])
                )
        else:
            limits = base_limits
        
        bounds = []
        for inst in instruments:
            max_w = limits.get(f'{inst}_weight_max', 0.5)  # v5.1: conservative default (was 2.0)
            bounds.append((-max_w, max_w))

        # Optimize
        try:
            x0 = prev_vec if np.any(prev_vec != 0) else np.zeros(n)
            result = minimize(
                objective, x0, method='SLSQP',
                bounds=bounds, constraints=constraints,
                options={'maxiter': 500, 'ftol': 1e-10}
            )
            if result.success:
                weights = {instruments[i]: float(result.x[i]) for i in range(n)}
            else:
                # Fallback: simple mu-weighted
                weights = {instruments[i]: float(mu_vec[i] * budget_scale[i] * 0.5) for i in range(n)}
        except Exception as e:
            log(f"  Optimizer failed: {e}")
            weights = {instruments[i]: float(mu_vec[i] * budget_scale[i] * 0.5) for i in range(n)}

        return weights


# ============================================================
# 6. RISK OVERLAYS
# ============================================================
class RiskOverlays:
    """Drawdown scaling, vol targeting, regime scaling."""

    def __init__(self, config=None):
        self.cfg = config or DEFAULT_CONFIG

    def apply(self, weights, drawdown, realized_vol_20d, regime_probs):
        """Apply all risk overlays to weights."""
        w = dict(weights)

        # 1. Drawdown scaling (continuous linear interpolation)
        dd_cfg = self.cfg['drawdown_overlay']
        dd_5 = dd_cfg['dd_5']    # e.g., -0.05
        dd_10 = dd_cfg['dd_10']  # e.g., -0.10
        if drawdown <= dd_10:
            scale = dd_cfg['scale_at_dd_10']  # 0.0 at worst
        elif drawdown <= dd_5:
            # Linear interpolation between dd_5 (0.5) and dd_10 (0.0)
            frac = (drawdown - dd_5) / (dd_10 - dd_5)  # 0 at dd_5, 1 at dd_10
            scale = dd_cfg['scale_at_dd_5'] * (1 - frac) + dd_cfg['scale_at_dd_10'] * frac
        elif drawdown <= 0:
            # Linear interpolation between 0 (1.0) and dd_5 (0.5)
            frac = drawdown / dd_5  # 0 at 0%, 1 at dd_5
            scale = 1.0 * (1 - frac) + dd_cfg['scale_at_dd_5'] * frac
        else:
            scale = 1.0
        # Minimum scale of 0.1 to allow recovery
        scale = max(scale, 0.10)
        w = {k: v * scale for k, v in w.items()}

        # 2. Vol targeting
        vol_target = self.cfg['risk_targets']['overlay_vol_target_annual']
        if realized_vol_20d > 0:
            vol_scale = min(1.0, vol_target / realized_vol_20d)
            w = {k: v * vol_scale for k, v in w.items()}

        # 3. Regime scaling
        # v2.3: REMOVED global regime scaling from overlays to eliminate double-counting.
        # Regime adjustment is already applied to mu in ProductionEngine.step() (lines 1700-1731).
        # Keeping only extreme domestic stress as a hard risk limit (circuit breaker).
        p_domestic_stress = regime_probs.get('P_domestic_stress', 0)
        p_riskoff = regime_probs.get('P_riskoff', 0)

        # Circuit breaker: simultaneous global risk-off AND domestic stress
        if p_riskoff > 0.7 and p_domestic_stress > 0.7:
            # Extreme combined stress: hard cut to prevent catastrophic loss
            for k in ['belly', 'long']:
                if k in w:
                    w[k] *= 0.5
            if 'hard' in w:
                w['hard'] *= 0.4
            if 'ntnb' in w:
                w['ntnb'] *= 0.4
            if 'front' in w:
                w['front'] *= 0.7
            log(f"    RiskOverlay: circuit breaker triggered (P_riskoff={p_riskoff:.2f}, P_dom_stress={p_domestic_stress:.2f})")

        return w


# ============================================================
# 7. PRODUCTION ENGINE (Single Code Path)
# ============================================================
class ProductionEngine:
    """
    Single code path for live and backtest.
    build_features → fit_models → predict_mu → optimize → apply_overlays
    Now uses EnsembleAlphaModels (Ridge + GBM) with score demeaning.
    """

    def __init__(self, config=None):
        self.cfg = config or DEFAULT_CONFIG
        self.data_layer = DataLayer(self.cfg)
        self.feature_engine = None
        self.alpha_models = None  # EnsembleAlphaModels
        self.regime_model = None
        self.optimizer = None
        self.risk_overlays = RiskOverlays(self.cfg)
        # Score demeaning state
        self.raw_score_history = []  # rolling history for demeaning
        self.demeaning_window = self.cfg.get('score_demeaning_window', 60)
        # v3.7: Hyperparameter cache (refit every 12 months via purged k-fold CV)
        self.hp_cache = {}  # {instrument: {model_params}}
        self.hp_last_refit = {}  # {instrument: last_refit_step_count}
        self.step_count = 0
        self.hp_refit_interval = 12  # refit hyperparameters every 12 months

    def initialize(self):
        """Load data and build features (called once)."""
        self.data_layer.load_all().build_monthly().compute_instrument_returns()
        self.feature_engine = FeatureEngine(self.data_layer, self.cfg)
        self.feature_engine.build_all()
        self.alpha_models = EnsembleAlphaModels(self.data_layer, self.feature_engine, self.cfg)
        self.regime_model = RegimeModel(self.data_layer, self.cfg)
        # v4.0: Wire feature_engine ref so RegimeModel can access equilibrium features
        self.regime_model._feature_engine_ref = self.feature_engine
        self.optimizer = Optimizer(self.data_layer, self.cfg)
        return self

    def _demean_score(self, raw_score):
        """
        Apply rolling z-score normalization to composite score.
        score = (raw - mean_60m) / max(std_60m, 0.5)
        This ensures the score oscillates symmetrically around zero.
        """
        self.raw_score_history.append(raw_score)
        window = self.demeaning_window
        history = self.raw_score_history[-window:]

        if len(history) < 12:  # need minimum history
            return raw_score

        mean_w = np.mean(history)
        std_w = max(np.std(history), 0.5)
        return (raw_score - mean_w) / std_w

    def step(self, asof_date, prev_weights, drawdown, realized_vol, ic_scores=None):
        """
        Execute one step of the production engine.
        Returns: (weights, mu, regime_probs, extra_info)
        extra_info contains model-level details for dashboard.
        v2.3: IC gating, improved score demeaning, covariance shrinkage.
        """
        # 1. Fit regime
        regime_probs = self.regime_model.get_probs_at(asof_date)

        # 1b. Update composite equilibrium with actual regime probabilities
        if hasattr(self.feature_engine, 'update_equilibrium_with_regime'):
            regime_probs_df = self.regime_model.regime_probs if hasattr(self.regime_model, 'regime_probs') else None
            self.feature_engine.update_equilibrium_with_regime(regime_probs, regime_probs_df)

        # v3.7: Periodic hyperparameter selection via purged k-fold CV
        self.step_count += 1
        if self.step_count % self.hp_refit_interval == 1:  # refit every 12 steps
            window = self.cfg['training_window_months']
            ret_df = self.data_layer.ret_df
            feat_df = self.feature_engine.feature_df
            if ret_df is not None and feat_df is not None:
                for inst, feat_names in EnsembleAlphaModels.FEATURE_MAP.items():
                    if inst not in ret_df.columns:
                        continue
                    available_feats = [f for f in feat_names if f in feat_df.columns]
                    if len(available_feats) < 2:
                        continue
                    y = ret_df[inst].loc[:asof_date]
                    X = feat_df[available_feats].loc[:asof_date]
                    common = y.index.intersection(X.index)
                    y = y.reindex(common).dropna()
                    X = X.reindex(y.index).dropna()
                    y = y.reindex(X.index)
                    if len(y) > window:
                        y = y.iloc[-window:]
                        X = X.iloc[-window:]
                    if len(y) >= 60:  # need enough data for CV
                        hp = self.alpha_models.select_hyperparameters(X.values, y.values, inst)
                        self.hp_cache[inst] = hp

        # 2. v5.2: Update regime info for adaptive feature selection
        if hasattr(self.alpha_models, 'update_regime_for_feature_selection'):
            self.alpha_models.update_regime_for_feature_selection(regime_probs)

        # 2a. Fit ensemble alpha models and predict mu
        mu = self.alpha_models.fit_and_predict(asof_date)

        # 2b. IC-conditional gating: SOFT scaling (not zero-out) for instruments with low IC
        # This preserves signal diversity while reducing allocation to low-conviction instruments
        ic_threshold = self.cfg.get('ic_gating_threshold', 0.0)
        ic_min_obs = self.cfg.get('ic_gating_min_obs', 24)
        ic_floor = self.cfg.get('ic_gating_floor', 0.15)  # Minimum scaling factor (15%)
        if ic_scores and self.cfg.get('signal_quality_sizing', True):
            # Find the max IC across instruments for normalization
            valid_ics = [v for k, v in ic_scores.items() if not k.endswith('_n') and v is not None]
            ic_max = max(valid_ics) if valid_ics else 0.3
            ic_max = max(ic_max, 0.1)  # Floor to avoid division issues
            for inst in list(mu.keys()):
                ic_val = ic_scores.get(inst, None)
                if ic_val is not None:
                    n_obs = ic_scores.get(f'{inst}_n', ic_min_obs)
                    if n_obs >= ic_min_obs:
                        if ic_val < ic_threshold:
                            # Soft gating: scale down proportionally, with floor
                            # IC < 0 → scale = floor (15%), IC = 0 → scale = floor
                            scale = max(ic_floor, (ic_val + 0.1) / (ic_max + 0.1))
                            scale = np.clip(scale, ic_floor, 1.0)
                            mu[inst] = mu[inst] * scale
                        elif ic_val > 0:
                            # Positive IC: scale up slightly for high-conviction instruments
                            ic_boost = min(ic_val / ic_max, 1.5)  # Cap at 1.5x
                            mu[inst] = mu[inst] * max(ic_boost, 1.0)

        # 3. Score demeaning: compute raw composite score, then normalize
        raw_score = sum(mu.values())
        demeaned_score = self._demean_score(raw_score)

        # v2.3: Improved scale factor with safeguard against instability near zero
        if abs(raw_score) > 0.005:  # Minimum threshold to avoid erratic scaling
            scale_factor = demeaned_score / raw_score
            # Clip scale factor to prevent extreme amplification
            scale_factor = np.clip(scale_factor, -3.0, 3.0)
        else:
            # Near-zero raw score: use demeaned score directly as additive offset
            scale_factor = 1.0 if abs(demeaned_score) < 0.01 else 0.0

        mu_demeaned = {inst: m * scale_factor for inst, m in mu.items()}

        # 4. Regime-adjusted mu (two-level: global + domestic)
        mu_adj = {}
        p_carry = regime_probs.get('P_carry', 0.33)
        p_riskoff = regime_probs.get('P_riskoff', 0.33)
        p_stress_global = regime_probs.get('P_stress', 0.33)
        p_dom_calm = regime_probs.get('P_domestic_calm', 0.5)
        p_dom_stress = regime_probs.get('P_domestic_stress', 0.5)

        # Global regime scaling per instrument type
        global_scale = {
            'fx':    p_carry * 1.0 + p_riskoff * 0.7 + p_stress_global * 0.5,  # FX less dampened (can profit from risk-off)
            'front': p_carry * 1.0 + p_riskoff * 0.5 + p_stress_global * 0.3,
            'belly': p_carry * 1.0 + p_riskoff * 0.4 + p_stress_global * 0.3,
            'long':  p_carry * 1.0 + p_riskoff * 0.3 + p_stress_global * 0.2,
            'hard':  p_carry * 1.0 + p_riskoff * 0.3 + p_stress_global * 0.2,
            'ntnb':  p_carry * 1.0 + p_riskoff * 0.5 + p_stress_global * 0.3,
        }
        # Domestic regime scaling (softer — domestic stress is chronic in EM, not always actionable)
        # Only apply meaningful reduction when domestic stress is very high AND global is also stressed
        domestic_scale = {
            'fx':    p_dom_calm * 1.0 + p_dom_stress * 0.95,   # FX barely affected by domestic alone
            'front': p_dom_calm * 1.0 + p_dom_stress * 0.85,
            'belly': p_dom_calm * 1.0 + p_dom_stress * 0.80,
            'long':  p_dom_calm * 1.0 + p_dom_stress * 0.70,   # Long most sensitive to domestic
            'hard':  p_dom_calm * 1.0 + p_dom_stress * 0.90,   # Hard less affected by domestic
            'ntnb':  p_dom_calm * 1.0 + p_dom_stress * 0.70,   # NTN-B affected by domestic inflation
        }

        for inst, m_val in mu_demeaned.items():
            g_scale = global_scale.get(inst, 0.5)
            d_scale = domestic_scale.get(inst, 0.7)
            # Combined: product of global and domestic scaling
            combined_scale = g_scale * d_scale
            mu_adj[inst] = m_val * combined_scale

        # 5. Rolling covariance with Ledoit-Wolf shrinkage
        ret_df = self.data_layer.ret_df
        available = ret_df.loc[:asof_date]
        cov = None
        cov_window = self.cfg.get('cov_window_months', 36)
        use_shrinkage = self.cfg.get('cov_shrinkage', True)
        if len(available) > 24:
            cov_data = available.iloc[-min(cov_window, len(available)):]
            if use_shrinkage and len(cov_data) > cov_data.shape[1] + 1:
                try:
                    from sklearn.covariance import LedoitWolf
                    lw = LedoitWolf().fit(cov_data.fillna(0).values)
                    cov = pd.DataFrame(lw.covariance_, index=cov_data.columns, columns=cov_data.columns)
                except Exception:
                    cov = cov_data.cov()
            else:
                cov = cov_data.cov()

        # 6. Optimize (v2.3: pass regime_probs for regime-conditional position limits)
        weights = self.optimizer.optimize(mu_adj, cov, prev_weights, ic_scores, regime_probs)

        # 7. Apply risk overlays
        weights = self.risk_overlays.apply(weights, drawdown, realized_vol, regime_probs)

        # Extra info for dashboard
        extra_info = {
            'raw_score': raw_score,
            'demeaned_score': demeaned_score,
            'model_predictions': self.alpha_models.model_predictions,
        }

        return weights, mu, regime_probs, extra_info


# ============================================================
# 8. BACKTEST HARNESS
# ============================================================
class BacktestHarness:
    """Walk-forward backtest calling ProductionEngine."""

    def __init__(self, config=None):
        self.cfg = config or DEFAULT_CONFIG
        self.engine = ProductionEngine(self.cfg)
        self.results = []
        self.summary = {}

    def run(self):
        """Run full walk-forward backtest."""
        log("\n" + "=" * 60)
        log("BACKTEST HARNESS v2 — Walk-Forward")
        log("=" * 60)

        self.engine.initialize()

        # v2.3: Regime model fitted with expanding window during backtest
        # Initial fit uses data up to start of backtest period
        ret_df_temp = self.engine.data_layer.ret_df
        train_window_temp = self.cfg['training_window_months']
        if len(ret_df_temp) > train_window_temp:
            initial_asof = ret_df_temp.index[train_window_temp]
            self.engine.regime_model.fit(asof_date=initial_asof)
        else:
            self.engine.regime_model.fit()
        regime_refit_interval = self.cfg.get('regime_refit_interval', 12)
        last_regime_refit = 0

        ret_df = self.engine.data_layer.ret_df
        if len(ret_df) < 72:  # Need 60 for training + 12 for test
            log("  Insufficient data for backtest")
            return self

        cash_ret = self.engine.data_layer.instrument_returns.get('cash', pd.Series(dtype=float))

        # v3.8: Load Ibovespa benchmark for comparison
        ibov_ret = pd.Series(dtype=float)
        try:
            ibov_path = os.path.join(DATA_DIR, 'IBOVESPA.csv')
            if os.path.exists(ibov_path):
                ibov_df = pd.read_csv(ibov_path, parse_dates=[0], index_col=0)
                ibov_col = ibov_df.columns[0] if len(ibov_df.columns) > 0 else None
                if ibov_col:
                    ibov_prices = ibov_df[ibov_col].dropna()
                    ibov_ret = ibov_prices.pct_change().dropna()
                    ibov_ret.index = ibov_ret.index.to_period('M').to_timestamp()
                    ibov_ret = ibov_ret.groupby(ibov_ret.index).apply(lambda x: (1 + x).prod() - 1)
                    log(f"  Ibovespa benchmark loaded: {len(ibov_ret)} monthly returns")
        except Exception as e:
            log(f"  Ibovespa benchmark failed to load: {e}")

        # Start after training window
        train_window = self.cfg['training_window_months']
        start_idx = train_window
        dates = ret_df.index[start_idx:]

        log(f"  Backtest period: {dates[0].strftime('%Y-%m')} → {dates[-1].strftime('%Y-%m')} ({len(dates)} months)")

        # State
        equity_overlay = 1.0
        equity_total = 1.0
        equity_ibov = 1.0  # v3.8: Ibovespa benchmark equity
        peak_overlay = 1.0
        peak_total = 1.0
        peak_ibov = 1.0
        prev_weights = {}
        ic_history = {}  # {instrument: [(pred, realized), ...]}
        shap_history = []  # v3.9: periodic SHAP snapshots [{date, instrument, feature, importance}]
        shap_interval = 6  # compute SHAP every 6 months
        last_shap_idx = -shap_interval  # force first computation

        records = []

        for i, date in enumerate(dates):
            prev_date = ret_df.index[ret_df.index.get_loc(date) - 1]

            # v2.3: Periodic HMM refit with expanding window
            if i - last_regime_refit >= regime_refit_interval:
                self.engine.regime_model.fit(asof_date=prev_date)
                last_regime_refit = i

            # Drawdown
            dd_overlay = (equity_overlay - peak_overlay) / peak_overlay if peak_overlay > 0 else 0

            # v3.7: GARCH(1,1) volatility model (replaces simple realized vol)
            realized_vol_ann = 0.10  # conservative default before enough history
            if len(records) >= 24:
                recent_rets = np.array([r['overlay_return'] for r in records[-min(60, len(records)):]]) * 100  # scale to %
                try:
                    garch = arch_model(recent_rets, vol='Garch', p=1, q=1, mean='Zero', rescale=False)
                    garch_fit = garch.fit(disp='off', show_warning=False)
                    # Forecast 1-step ahead conditional variance
                    forecast = garch_fit.forecast(horizon=1)
                    cond_var = float(forecast.variance.iloc[-1, 0])  # monthly variance in %²
                    garch_vol_monthly = np.sqrt(cond_var) / 100  # back to decimal
                    realized_vol_ann = garch_vol_monthly * np.sqrt(12)
                    realized_vol_ann = max(realized_vol_ann, 0.02)  # floor at 2%
                    realized_vol_ann = min(realized_vol_ann, 0.50)  # cap at 50%
                except Exception:
                    # Fallback to simple realized vol if GARCH fails
                    recent_rets_dec = [r['overlay_return'] for r in records[-min(20, len(records)):]]
                    realized_vol_ann = float(np.std(recent_rets_dec) * np.sqrt(12))
                    realized_vol_ann = max(realized_vol_ann, 0.02)
            elif len(records) >= 12:
                recent_rets = [r['overlay_return'] for r in records[-min(20, len(records)):]]
                realized_vol_ann = float(np.std(recent_rets) * np.sqrt(12))
                realized_vol_ann = max(realized_vol_ann, 0.02)

            # IC scores (rolling 36m)
            ic_scores = {}
            for inst in ret_df.columns:
                if inst in ic_history and len(ic_history[inst]) >= 12:
                    preds, reals = zip(*ic_history[inst][-36:])
                    if np.std(preds) > 1e-8 and np.std(reals) > 1e-8:
                        ic_scores[inst] = float(np.corrcoef(preds, reals)[0, 1])

            # Production engine step (now returns 4-tuple with extra_info)
            weights, mu, regime_probs, extra_info = self.engine.step(
                prev_date, prev_weights, dd_overlay, realized_vol_ann, ic_scores
            )

            # Mark to market
            overlay_ret = 0.0
            asset_pnl = {}
            for inst in ret_df.columns:
                w = weights.get(inst, 0)
                r = float(ret_df.loc[date, inst]) if inst in ret_df.columns else 0.0
                pnl = w * r
                asset_pnl[inst] = pnl
                overlay_ret += pnl

                # Track IC
                mu_pred = mu.get(inst, 0)
                if inst not in ic_history:
                    ic_history[inst] = []
                ic_history[inst].append((mu_pred, r))

                # Update OOS history for ensemble adaptive weights
                model_preds = extra_info.get('model_predictions', {})
                if inst in model_preds:
                    for model_name in EnsembleAlphaModels.MODEL_NAMES:  # v3.7: all 4 models
                        if model_name in model_preds[inst]:
                            self.engine.alpha_models.update_oos_history(
                                inst, model_name, model_preds[inst][model_name], r
                            )

            # Cash return
            cash_r = 0.0
            if date in cash_ret.index:
                cash_r = float(cash_ret.loc[date])
            elif len(cash_ret) > 0:
                # Use last available
                available_cash = cash_ret.loc[:date]
                if len(available_cash) > 0:
                    cash_r = float(available_cash.iloc[-1])

            # Total return = cash + overlay
            total_ret = cash_r + overlay_ret

            # Update equity
            equity_overlay *= (1 + overlay_ret)
            equity_total *= (1 + total_ret)
            peak_overlay = max(peak_overlay, equity_overlay)
            peak_total = max(peak_total, equity_total)

            # v3.8: Ibovespa benchmark tracking
            ibov_r = 0.0
            # Normalize date to month-start for matching (ret_df uses ME=month-end, ibov uses MS=month-start)
            ibov_key = date.to_period('M').to_timestamp()
            if ibov_key in ibov_ret.index:
                ibov_r = float(ibov_ret.loc[ibov_key])
            equity_ibov *= (1 + ibov_r)
            peak_ibov = max(peak_ibov, equity_ibov)
            dd_ibov_pct = (equity_ibov - peak_ibov) / peak_ibov if peak_ibov > 0 else 0

            # Trailing peak reset: use 12-month trailing high to allow recovery
            if len(records) >= 12:
                trailing_12m = max(r['equity_overlay'] for r in records[-12:])
                peak_overlay = max(trailing_12m, equity_overlay)
                trailing_12m_total = max(r['equity_total'] for r in records[-12:])
                peak_total = max(trailing_12m_total, equity_total)
            dd_overlay_pct = (equity_overlay - peak_overlay) / peak_overlay
            dd_total_pct = (equity_total - peak_total) / peak_total

            # Transaction costs (v3.8: regime-dependent multiplier)
            tc = 0.0
            tc_bps = self.cfg['transaction_costs_bps']
            tc_regime_mults = self.cfg.get('tc_regime_multipliers', {})
            tc_mult = sum(
                regime_probs.get(regime, 0) * tc_regime_mults.get(regime, 1.0)
                for regime in tc_regime_mults
            ) if regime_probs else 1.0
            tc_mult = max(tc_mult, 0.5)
            for inst in weights:
                delta_w = abs(weights.get(inst, 0) - prev_weights.get(inst, 0))
                tc += delta_w * tc_bps.get(inst, 5) / 10000 * tc_mult

            # Turnover
            turnover = sum(abs(weights.get(inst, 0) - prev_weights.get(inst, 0)) for inst in set(list(weights.keys()) + list(prev_weights.keys())))

            records.append({
                'date': date.strftime('%Y-%m-%d'),
                'equity_overlay': round(equity_overlay, 6),
                'equity_total': round(equity_total, 6),
                'overlay_return': round(overlay_ret, 6),
                'cash_return': round(cash_r, 6),
                'total_return': round(total_ret, 6),
                'drawdown_overlay': round(dd_overlay_pct * 100, 2),
                'drawdown_total': round(dd_total_pct * 100, 2),
                'fx_pnl': round(asset_pnl.get('fx', 0) * 100, 3),
                'front_pnl': round(asset_pnl.get('front', 0) * 100, 3),
                'belly_pnl': round(asset_pnl.get('belly', 0) * 100, 3),
                'long_pnl': round(asset_pnl.get('long', 0) * 100, 3),
                'hard_pnl': round(asset_pnl.get('hard', 0) * 100, 3),
                'ntnb_pnl': round(asset_pnl.get('ntnb', 0) * 100, 3),
                'weight_fx': round(weights.get('fx', 0), 4),
                'weight_front': round(weights.get('front', 0), 4),
                'weight_belly': round(weights.get('belly', 0), 4),
                'weight_long': round(weights.get('long', 0), 4),
                'weight_hard': round(weights.get('hard', 0), 4),
                'weight_ntnb': round(weights.get('ntnb', 0), 4),
                'mu_fx': round(mu.get('fx', 0) * 100, 3),
                'mu_front': round(mu.get('front', 0) * 100, 3),
                'mu_belly': round(mu.get('belly', 0) * 100, 3),
                'mu_long': round(mu.get('long', 0) * 100, 3),
                'mu_hard': round(mu.get('hard', 0) * 100, 3),
                'mu_ntnb': round(mu.get('ntnb', 0) * 100, 3),
                'P_carry': round(regime_probs.get('P_carry', 0), 3),
                'P_riskoff': round(regime_probs.get('P_riskoff', 0), 3),
                'P_stress': round(regime_probs.get('P_stress', 0), 3),
                'P_domestic_calm': round(regime_probs.get('P_domestic_calm', 0), 3),
                'P_domestic_stress': round(regime_probs.get('P_domestic_stress', 0), 3),
                'tc_pct': round(tc * 100, 4),
                'tc_mult': round(tc_mult, 2),
                'turnover': round(turnover, 4),
                'score_total': round(sum(mu.get(inst, 0) for inst in mu) * 100, 2),
                'raw_score': round(extra_info.get('raw_score', 0) * 100, 3),
                'demeaned_score': round(extra_info.get('demeaned_score', 0), 3),
                'w_ridge_avg': round(np.mean([mp.get('w_ridge', 0.25) for mp in extra_info.get('model_predictions', {}).values()]) if extra_info.get('model_predictions') else 0.25, 3),
                'w_gbm_avg': round(np.mean([mp.get('w_gbm', 0.25) for mp in extra_info.get('model_predictions', {}).values()]) if extra_info.get('model_predictions') else 0.25, 3),
                'w_rf_avg': round(np.mean([mp.get('w_rf', 0.25) for mp in extra_info.get('model_predictions', {}).values()]) if extra_info.get('model_predictions') else 0.25, 3),
                'w_xgb_avg': round(np.mean([mp.get('w_xgb', 0.25) for mp in extra_info.get('model_predictions', {}).values()]) if extra_info.get('model_predictions') else 0.25, 3),
                # v2.3: Rolling Sharpe 12m for frontend chart
                'rolling_sharpe_12m': round(self._compute_rolling_sharpe(records, 12), 3) if len(records) >= 12 else None,
                # v3.8: Ibovespa benchmark
                'ibov_return': round(ibov_r, 6),
                'equity_ibov': round(equity_ibov, 6),
                'drawdown_ibov': round(dd_ibov_pct * 100, 2),
            })

            prev_weights = dict(weights)

            # v3.9: Periodic SHAP snapshot for historical tracking
            if i - last_shap_idx >= shap_interval and self.engine.alpha_models:
                try:
                    snap = self.engine.alpha_models.compute_shap_snapshot(prev_date)
                    if snap:
                        for inst, feats in snap.items():
                            for feat, importance in feats.items():
                                shap_history.append({
                                    'date': date.strftime('%Y-%m-%d'),
                                    'instrument': inst,
                                    'feature': feat,
                                    'importance': importance,
                                })
                        last_shap_idx = i
                except Exception:
                    pass  # SHAP snapshot is non-critical

            if (i + 1) % 24 == 0:
                log(f"  [{date.strftime('%Y-%m')}] overlay={equity_overlay:.4f}, total={equity_total:.4f}, dd={dd_overlay_pct*100:.1f}%")

        # Trim records to start when overlay has active returns
        # This ensures CDI and overlay start at the same point
        active_start = None
        for idx_r, rec in enumerate(records):
            if abs(rec['overlay_return']) > 1e-8:
                active_start = idx_r
                break

        if active_start is not None and active_start > 0:
            trimmed = records[active_start:]
            log(f"  Trimming backtest: removing {active_start} months of CDI-only period")
            log(f"  Active period: {trimmed[0]['date']} → {trimmed[-1]['date']} ({len(trimmed)} months)")

            # Recalculate equity curves from the active start
            eq_overlay = 1.0
            eq_total = 1.0
            peak_ov = 1.0
            peak_tot = 1.0
            for j, rec in enumerate(trimmed):
                eq_overlay *= (1 + rec['overlay_return'])
                eq_total *= (1 + rec['total_return'])
                peak_ov = max(peak_ov, eq_overlay)
                peak_tot = max(peak_tot, eq_total)
                if j >= 12:
                    trail_ov = max(trimmed[k]['equity_overlay'] for k in range(max(0, j-12), j))
                    peak_ov = max(trail_ov, eq_overlay)
                    trail_tot = max(trimmed[k]['equity_total'] for k in range(max(0, j-12), j))
                    peak_tot = max(trail_tot, eq_total)
                rec['equity_overlay'] = round(eq_overlay, 6)
                rec['equity_total'] = round(eq_total, 6)
                rec['drawdown_overlay'] = round((eq_overlay - peak_ov) / peak_ov * 100, 2) if peak_ov > 0 else 0
                rec['drawdown_total'] = round((eq_total - peak_tot) / peak_tot * 100, 2) if peak_tot > 0 else 0
            records = trimmed

        self.results = records
        self.shap_history = shap_history  # v3.9: temporal SHAP snapshots
        self._compute_summary(records, ic_history)
        log(f"  SHAP history: {len(shap_history)} snapshots across {len(set(s['date'] for s in shap_history))} dates")
        return self

    @staticmethod
    def _compute_rolling_sharpe(records, window=12):
        """Compute rolling Sharpe ratio from the last N months of overlay returns."""
        if len(records) < window:
            return 0.0
        recent = [r['overlay_return'] for r in records[-window:]]
        mean_ret = np.mean(recent)
        std_ret = np.std(recent)
        if std_ret < 1e-8:
            return 0.0
        return float(mean_ret / std_ret * np.sqrt(12))  # annualized

    def _compute_summary(self, records, ic_history):
        """Compute backtest summary metrics."""
        if not records:
            self.summary = {}
            return

        overlay_rets = [r['overlay_return'] for r in records]
        total_rets = [r['total_return'] for r in records]
        n_months = len(records)
        n_years = n_months / 12

        # Overlay metrics
        eq_overlay = records[-1]['equity_overlay']
        ann_ret_overlay = (eq_overlay ** (1 / max(n_years, 0.5)) - 1)
        ann_vol_overlay = float(np.std(overlay_rets) * np.sqrt(12))
        sharpe_overlay = ann_ret_overlay / ann_vol_overlay if ann_vol_overlay > 0 else 0
        max_dd_overlay = min(r['drawdown_overlay'] for r in records)

        # Total metrics
        eq_total = records[-1]['equity_total']
        ann_ret_total = (eq_total ** (1 / max(n_years, 0.5)) - 1)
        ann_vol_total = float(np.std(total_rets) * np.sqrt(12))
        sharpe_total = ann_ret_total / ann_vol_total if ann_vol_total > 0 else 0
        max_dd_total = min(r['drawdown_total'] for r in records)

        # Win rate
        win_overlay = sum(1 for r in overlay_rets if r > 0) / n_months
        win_total = sum(1 for r in total_rets if r > 0) / n_months

        # IC per instrument
        ic_final = {}
        for inst, history in ic_history.items():
            if len(history) >= 12:
                preds, reals = zip(*history)
                if np.std(preds) > 1e-8 and np.std(reals) > 1e-8:
                    ic_final[inst] = round(float(np.corrcoef(preds, reals)[0, 1]), 4)

        # Hit rate per instrument
        hit_rates = {}
        for inst in ['fx', 'front', 'belly', 'long', 'hard', 'ntnb']:
            pnl_key = f'{inst}_pnl'
            pnls = [r[pnl_key] for r in records if pnl_key in r]
            if pnls:
                hit_rates[inst] = round(sum(1 for p in pnls if p > 0) / len(pnls) * 100, 1)

        # Total TC
        total_tc = sum(r['tc_pct'] for r in records)
        avg_turnover = np.mean([r['turnover'] for r in records])

        # Attribution (all 6 instruments including NTN-B)
        attribution = {}
        for inst in ['fx', 'front', 'belly', 'long', 'hard', 'ntnb']:
            pnl_key = f'{inst}_pnl'
            total_pnl = sum(r[pnl_key] for r in records if pnl_key in r)
            attribution[inst] = round(total_pnl, 2)

        # Ensemble weight stats (v3.7: 4 models)
        w_ridge_series = [r.get('w_ridge_avg', 0.25) for r in records]
        w_gbm_series = [r.get('w_gbm_avg', 0.25) for r in records]
        w_rf_series = [r.get('w_rf_avg', 0.25) for r in records]
        w_xgb_series = [r.get('w_xgb_avg', 0.25) for r in records]
        demeaned_scores = [r.get('demeaned_score', 0) for r in records]
        raw_scores = [r.get('raw_score', 0) for r in records]

        self.summary = {
            'period': f"{records[0]['date']} → {records[-1]['date']}",
            'n_months': n_months,
            'overlay': {
                'total_return': round((eq_overlay - 1) * 100, 2),
                'annualized_return': round(ann_ret_overlay * 100, 2),
                'annualized_vol': round(ann_vol_overlay * 100, 2),
                'sharpe': round(sharpe_overlay, 2),
                'max_drawdown': round(max_dd_overlay, 2),
                'calmar': round(ann_ret_overlay * 100 / abs(max_dd_overlay), 2) if max_dd_overlay != 0 else 0,
                'win_rate': round(win_overlay * 100, 1),
            },
            'total': {
                'total_return': round((eq_total - 1) * 100, 2),
                'annualized_return': round(ann_ret_total * 100, 2),
                'annualized_vol': round(ann_vol_total * 100, 2),
                'sharpe': round(sharpe_total, 2),
                'max_drawdown': round(max_dd_total, 2),
                'calmar': round(ann_ret_total * 100 / abs(max_dd_total), 2) if max_dd_total != 0 else 0,
                'win_rate': round(win_total * 100, 1),
            },
            'ic_per_instrument': ic_final,
            'hit_rates': hit_rates,
            'attribution_pct': attribution,
            'total_tc_pct': round(total_tc, 2),
            'avg_monthly_turnover': round(avg_turnover, 4),
            'best_month': {
                'date': max(records, key=lambda r: r['overlay_return'])['date'],
                'return_pct': round(max(records, key=lambda r: r['overlay_return'])['overlay_return'] * 100, 2),
            },
            'worst_month': {
                'date': min(records, key=lambda r: r['overlay_return'])['date'],
                'return_pct': round(min(records, key=lambda r: r['overlay_return'])['overlay_return'] * 100, 2),
            },
            'ensemble': {
                'models': ['ridge', 'gbm', 'rf', 'xgb'],  # v3.7
                'avg_w_ridge': round(float(np.mean(w_ridge_series)), 3),
                'avg_w_gbm': round(float(np.mean(w_gbm_series)), 3),
                'avg_w_rf': round(float(np.mean(w_rf_series)), 3),
                'avg_w_xgb': round(float(np.mean(w_xgb_series)), 3),
                'final_w_ridge': round(w_ridge_series[-1], 3) if w_ridge_series else 0.25,
                'final_w_gbm': round(w_gbm_series[-1], 3) if w_gbm_series else 0.25,
                'final_w_rf': round(w_rf_series[-1], 3) if w_rf_series else 0.25,
                'final_w_xgb': round(w_xgb_series[-1], 3) if w_xgb_series else 0.25,
            },
            'score_demeaning': {
                'raw_score_mean': round(float(np.mean(raw_scores)), 3),
                'raw_score_std': round(float(np.std(raw_scores)), 3),
                'demeaned_score_mean': round(float(np.mean(demeaned_scores)), 3),
                'demeaned_score_std': round(float(np.std(demeaned_scores)), 3),
            },
            'regime_two_level': {
                'domestic_stress_pct': round(sum(1 for r in records if r.get('P_domestic_stress', 0) > 0.5) / n_months * 100, 1),
                'domestic_calm_pct': round(sum(1 for r in records if r.get('P_domestic_calm', 0) > 0.5) / n_months * 100, 1),
                'global_carry_pct': round(sum(1 for r in records if r.get('P_carry', 0) > 0.5) / n_months * 100, 1),
                'global_riskoff_pct': round(sum(1 for r in records if r.get('P_riskoff', 0) > 0.5) / n_months * 100, 1),
                'global_stress_pct': round(sum(1 for r in records if r.get('P_stress', 0) > 0.5) / n_months * 100, 1),
            },
        }

        # v3.8: Ibovespa benchmark metrics
        ibov_rets = [r.get('ibov_return', 0) for r in records]
        eq_ibov = records[-1].get('equity_ibov', 1.0)
        if eq_ibov > 0 and n_years > 0:
            ann_ret_ibov = (eq_ibov ** (1 / max(n_years, 0.5)) - 1)
            ann_vol_ibov = float(np.std(ibov_rets) * np.sqrt(12))
            sharpe_ibov = ann_ret_ibov / ann_vol_ibov if ann_vol_ibov > 0 else 0
            max_dd_ibov = min(r.get('drawdown_ibov', 0) for r in records)
            win_ibov = sum(1 for r in ibov_rets if r > 0) / n_months
            self.summary['ibovespa'] = {
                'total_return': round((eq_ibov - 1) * 100, 2),
                'annualized_return': round(ann_ret_ibov * 100, 2),
                'annualized_vol': round(ann_vol_ibov * 100, 2),
                'sharpe': round(sharpe_ibov, 2),
                'max_drawdown': round(max_dd_ibov, 2),
                'calmar': round(ann_ret_ibov * 100 / abs(max_dd_ibov), 2) if max_dd_ibov != 0 else 0,
                'win_rate': round(win_ibov * 100, 1),
            }
        else:
            self.summary['ibovespa'] = {
                'total_return': 0, 'annualized_return': 0, 'annualized_vol': 0,
                'sharpe': 0, 'max_drawdown': 0, 'calmar': 0, 'win_rate': 0,
            }

        log("\n" + "=" * 60)
        log("BACKTEST SUMMARY v2.3")
        log("=" * 60)
        log(f"  Period: {self.summary['period']} ({n_months} months)")
        log(f"\n  OVERLAY (excess over CDI):")
        log(f"    Total return: {self.summary['overlay']['total_return']:.2f}%")
        log(f"    Ann return:   {self.summary['overlay']['annualized_return']:.2f}%")
        log(f"    Ann vol:      {self.summary['overlay']['annualized_vol']:.2f}%")
        log(f"    Sharpe:       {self.summary['overlay']['sharpe']:.2f}")
        log(f"    Max DD:       {self.summary['overlay']['max_drawdown']:.2f}%")
        log(f"    Calmar:       {self.summary['overlay']['calmar']:.2f}")
        log(f"    Win rate:     {self.summary['overlay']['win_rate']:.1f}%")
        log(f"\n  TOTAL (CDI + overlay):")
        log(f"    Total return: {self.summary['total']['total_return']:.2f}%")
        log(f"    Ann return:   {self.summary['total']['annualized_return']:.2f}%")
        log(f"    Sharpe:       {self.summary['total']['sharpe']:.2f}")
        log(f"\n  IC per instrument: {ic_final}")
        log(f"  Hit rates: {hit_rates}")
        log(f"  Attribution: {attribution}")
        log(f"  Total TC: {total_tc:.2f}%")
        log(f"  Avg monthly turnover: {avg_turnover:.4f}")
        log(f"\n  ENSEMBLE WEIGHTS:")
        log(f"    Avg Ridge: {self.summary['ensemble']['avg_w_ridge']:.3f}")
        log(f"    Avg GBM:   {self.summary['ensemble']['avg_w_gbm']:.3f}")
        log(f"    Final Ridge: {self.summary['ensemble']['final_w_ridge']:.3f}")
        log(f"    Final GBM:   {self.summary['ensemble']['final_w_gbm']:.3f}")
        log(f"\n  SCORE DEMEANING:")
        log(f"    Raw score mean:     {self.summary['score_demeaning']['raw_score_mean']:.3f}")
        log(f"    Raw score std:      {self.summary['score_demeaning']['raw_score_std']:.3f}")
        log(f"    Demeaned score mean: {self.summary['score_demeaning']['demeaned_score_mean']:.3f}")
        log(f"    Demeaned score std:  {self.summary['score_demeaning']['demeaned_score_std']:.3f}")
        log(f"\n  TWO-LEVEL REGIME:")
        log(f"    Global carry:    {self.summary['regime_two_level']['global_carry_pct']:.1f}%")
        log(f"    Global riskoff:  {self.summary['regime_two_level']['global_riskoff_pct']:.1f}%")
        log(f"    Global stress:   {self.summary['regime_two_level']['global_stress_pct']:.1f}%")
        log(f"    Domestic calm:   {self.summary['regime_two_level']['domestic_calm_pct']:.1f}%")
        log(f"    Domestic stress: {self.summary['regime_two_level']['domestic_stress_pct']:.1f}%")
        log(f"\n  IBOVESPA BENCHMARK:")
        ibov = self.summary.get('ibovespa', {})
        log(f"    Total return: {ibov.get('total_return', 0):.2f}%")
        log(f"    Ann return:   {ibov.get('annualized_return', 0):.2f}%")
        log(f"    Sharpe:       {ibov.get('sharpe', 0):.2f}")
        log(f"    Max DD:       {ibov.get('max_drawdown', 0):.2f}%")


# ============================================================
# 9. STRESS TEST ENGINE
# ============================================================
class StressTestEngine:
    """
    Historical stress scenario analysis.
    Computes conditional performance metrics during known crisis periods.
    Each scenario is defined by a date range and a description.
    """

    # Canonical stress scenarios for BRL macro
    SCENARIOS = {
        'taper_tantrum_2013': {
            'name': 'Taper Tantrum',
            'start': '2013-05-01',
            'end': '2013-09-30',
            'description': 'Fed signals tapering of QE. EM selloff, BRL -15%, DI +300bps.',
            'category': 'global',
        },
        'dilma_2015': {
            'name': 'Crise Dilma / Impeachment',
            'start': '2015-01-01',
            'end': '2015-12-31',
            'description': 'Fiscal deterioration, rating downgrade, political crisis. BRL -33%, DI +400bps.',
            'category': 'domestic',
        },
        'joesley_day_2017': {
            'name': 'Joesley Day',
            'start': '2017-05-01',
            'end': '2017-07-31',
            'description': 'Temer corruption tapes leaked. BRL -8% intraday, circuit breaker triggered.',
            'category': 'domestic',
        },
        'covid_2020': {
            'name': 'COVID-19 Crash',
            'start': '2020-02-01',
            'end': '2020-05-31',
            'description': 'Global pandemic. BRL -25%, VIX 82, DI whipsaw, EMBI +300bps.',
            'category': 'global',
        },
        'fed_hike_2022': {
            'name': 'Fed Hiking Cycle',
            'start': '2022-01-01',
            'end': '2022-10-31',
            'description': 'Aggressive Fed tightening. DXY +15%, UST 10Y +250bps, EM pressure.',
            'category': 'global',
        },
        'lula_fiscal_2024': {
            'name': 'Fiscal Concerns Lula',
            'start': '2024-04-01',
            'end': '2024-08-31',
            'description': 'Fiscal framework concerns, BRL weakening, DI repricing.',
            'category': 'domestic',
        },
    }

    def __init__(self, backtest_records):
        """
        backtest_records: list of dicts from BacktestHarness.results
        """
        self.records = backtest_records
        self.results = {}

    def run_all(self):
        """Run stress analysis for all scenarios that overlap with backtest period."""
        if not self.records:
            return self

        bt_start = self.records[0]['date']
        bt_end = self.records[-1]['date']

        for scenario_id, scenario in self.SCENARIOS.items():
            # Check if scenario overlaps with backtest period
            if scenario['end'] < bt_start or scenario['start'] > bt_end:
                log(f"  Stress: {scenario['name']} outside backtest period, skipping")
                continue

            # Filter records within scenario window
            scenario_records = [
                r for r in self.records
                if scenario['start'] <= r['date'] <= scenario['end']
            ]

            if len(scenario_records) < 2:
                log(f"  Stress: {scenario['name']} insufficient data ({len(scenario_records)} months)")
                continue

            self.results[scenario_id] = self._analyze_scenario(scenario, scenario_records)
            log(f"  Stress: {scenario['name']} → overlay {self.results[scenario_id]['overlay_return']:.2f}%, max DD {self.results[scenario_id]['max_dd_overlay']:.2f}%")

        return self

    def _analyze_scenario(self, scenario, records):
        """Compute performance metrics for a specific stress scenario."""
        n = len(records)
        overlay_rets = [r['overlay_return'] for r in records]
        total_rets = [r['total_return'] for r in records]

        # Cumulative returns during scenario
        cum_overlay = 1.0
        cum_total = 1.0
        peak_overlay = 1.0
        max_dd = 0.0
        for r in records:
            cum_overlay *= (1 + r['overlay_return'])
            cum_total *= (1 + r['total_return'])
            peak_overlay = max(peak_overlay, cum_overlay)
            dd = (cum_overlay - peak_overlay) / peak_overlay
            max_dd = min(max_dd, dd)

        # Average weights during scenario
        avg_weights = {}
        for inst in ['fx', 'front', 'belly', 'long', 'hard', 'ntnb']:
            key = f'weight_{inst}'
            vals = [r.get(key, 0) for r in records]
            avg_weights[inst] = round(float(np.mean(vals)), 4)

        # Average regime probs during scenario
        avg_regime = {}
        for prob_key in ['P_carry', 'P_riskoff', 'P_stress', 'P_domestic_calm', 'P_domestic_stress']:
            vals = [r.get(prob_key, 0) for r in records]
            avg_regime[prob_key] = round(float(np.mean(vals)), 3)

        # PnL attribution during scenario
        attribution = {}
        for inst in ['fx', 'front', 'belly', 'long', 'hard', 'ntnb']:
            pnl_key = f'{inst}_pnl'
            total_pnl = sum(r.get(pnl_key, 0) for r in records)
            attribution[inst] = round(total_pnl, 3)

        # Monthly return stats
        mean_ret = float(np.mean(overlay_rets))
        vol_ret = float(np.std(overlay_rets)) if n > 1 else 0
        worst_month = min(records, key=lambda r: r['overlay_return'])
        best_month = max(records, key=lambda r: r['overlay_return'])

        return {
            'name': scenario['name'],
            'category': scenario['category'],
            'description': scenario['description'],
            'period': f"{records[0]['date']} → {records[-1]['date']}",
            'n_months': n,
            'overlay_return': round((cum_overlay - 1) * 100, 2),
            'total_return': round((cum_total - 1) * 100, 2),
            'max_dd_overlay': round(max_dd * 100, 2),
            'annualized_vol': round(vol_ret * np.sqrt(12) * 100, 2),
            'mean_monthly_return': round(mean_ret * 100, 3),
            'worst_month': {
                'date': worst_month['date'],
                'return_pct': round(worst_month['overlay_return'] * 100, 2),
            },
            'best_month': {
                'date': best_month['date'],
                'return_pct': round(best_month['overlay_return'] * 100, 2),
            },
            'avg_weights': avg_weights,
            'avg_regime': avg_regime,
            'attribution': attribution,
            'win_rate': round(sum(1 for r in overlay_rets if r > 0) / n * 100, 1),
        }

    def get_summary(self):
        """Return stress test results as a dict for JSON output."""
        return self.results


# ============================================================
# 10. MAIN ENTRY POINT
# ============================================================
def run_v2(config=None):
    """Run the full v2.3 system: backtest + stress tests + current state."""
    cfg = config or DEFAULT_CONFIG

    harness = BacktestHarness(cfg)
    harness.run()

    # Run stress tests on backtest results
    log("\n" + "=" * 60)
    log("STRESS TEST ENGINE")
    log("=" * 60)
    stress_engine = StressTestEngine(harness.results)
    stress_engine.run_all()

    # Build output compatible with dashboard
    output = {
        'version': 'v4.2',
        'framework': 'overlay_on_cdi',
        'backtest': {
            'timeseries': harness.results,
            'summary': harness.summary,
        },
        'stress_tests': stress_engine.get_summary(),
        'config': cfg,
    }

    # Add current state from production engine
    if harness.engine and harness.engine.alpha_models:
        engine = harness.engine
        ret_df = engine.data_layer.ret_df
        feat_df = engine.feature_engine.feature_df
        dl = engine.data_layer
        if len(ret_df) > 0:
            latest_date = ret_df.index[-1]
            mu = engine.alpha_models.predictions
            regime = engine.regime_model.get_probs_at(latest_date)
            last_row = harness.results[-1] if harness.results else {}

            # Determine direction from score
            score_total = last_row.get('score_total', 0)
            if score_total > 0.5:
                direction = 'LONG BRL (SHORT USD)'
            elif score_total < -0.5:
                direction = 'SHORT BRL (LONG USD)'
            else:
                direction = 'NEUTRAL'

            # Build state variables (latest Z-scores)
            # Column names in FeatureEngine use uppercase Z_ prefix
            state_variables = {}
            if feat_df is not None and len(feat_df) > 0:
                last_feat = feat_df.iloc[-1]
                z_map = {
                    'X1_diferencial_real': 'Z_real_diff',
                    'X2_surpresa_inflacao': 'Z_infl_surprise',
                    'X3_fiscal_risk': 'Z_fiscal',
                    'X4_termos_de_troca': 'Z_tot',
                    'X5_dolar_global': 'Z_dxy',
                    'X6_risk_global': 'Z_vix',
                    'X7_cds_brasil': 'Z_cds_br',
                    'X8_beer_misalignment': 'Z_beer',
                    'X9_reer_gap': 'Z_reer_gap',
                    'X10_term_premium': 'Z_term_premium',
                    'X11_cip_basis': 'Z_cip_basis',
                    'X12_iron_ore': 'Z_iron_ore',
                    # v4.0: Equilibrium-derived features
                    'X13_policy_gap': 'Z_policy_gap',
                    'X14_rstar_composite': 'Z_rstar_composite',
                    'X15_rstar_momentum': 'Z_rstar_momentum',
                    'X16_fiscal_component': 'Z_fiscal_component',
                    'X17_sovereign_component': 'Z_sovereign_component',
                    'X18_selic_star_gap': 'Z_selic_star_gap',
                }
                for key, col in z_map.items():
                    if col in last_feat.index:
                        val = last_feat[col]
                        if pd.notna(val):
                            state_variables[key] = round(float(val), 2)

            # Build positions from last backtest row
            # Compute per-instrument annualized volatility from rolling 36m returns
            instruments = ['fx', 'front', 'belly', 'long', 'hard', 'ntnb']
            inst_vol = {}
            vol_window = 36  # months for rolling vol estimation
            for inst in instruments:
                if inst in ret_df.columns:
                    avail = ret_df[inst].dropna()
                    if len(avail) >= 12:
                        recent = avail.iloc[-min(vol_window, len(avail)):]
                        ann_vol = float(recent.std() * np.sqrt(12))  # annualized vol (decimal)
                        inst_vol[inst] = max(ann_vol, 0.01)  # floor at 1%
                    else:
                        inst_vol[inst] = 0.10  # conservative default
                else:
                    inst_vol[inst] = 0.10  # conservative default

            positions = {}
            for inst in instruments:
                w = last_row.get(f'weight_{inst}', 0)
                mu_val = last_row.get(f'mu_{inst}', 0)  # mu is in PERCENTAGE (already *100 from records)
                # Convert back to decimal and annualize for Sharpe: mu_ann = (mu_pct/100) * 12
                mu_ann_decimal = (mu_val / 100.0) * 12  # annualized mu in decimal
                vol_ann = inst_vol.get(inst, 0.10)  # annualized vol in decimal
                sharpe_val = mu_ann_decimal / vol_ann if vol_ann > 0 else 0
                if inst == 'fx':
                    # FX instrument is defined as 'long USD': mu_fx > 0 means USD appreciates = SHORT BRL
                    dir_str = 'SHORT BRL' if mu_val > 0 else 'LONG BRL' if mu_val < 0 else 'NEUTRAL'
                else:
                    dir_str = 'LONG' if mu_val > 0 else 'SHORT' if mu_val < 0 else 'NEUTRAL'
                positions[inst] = {
                    'weight': round(w, 3),
                    'expected_return_3m': round(mu_val * 3, 2),  # mu_val is already in % (monthly), * 3 months
                    'expected_return_6m': round(mu_val * 6, 2),  # mu_val is already in % (monthly), * 6 months
                    'sharpe': round(sharpe_val, 2),
                    'annualized_vol': round(vol_ann * 100, 2),  # vol in % for display
                    'risk_unit': round(abs(w) * 0.01, 4),
                    'risk_contribution': round(abs(w) / max(sum(abs(last_row.get(f'weight_{i}', 0)) for i in instruments), 0.01), 3),
                    'direction': dir_str,
                }

            # Get current market data
            current_spot = 0
            selic_target = 0
            di_1y = 0
            di_5y = 0
            di_10y = 0
            ust_2y = 0
            ust_10y = 0
            embi_spread = 0
            # Cupom cambial and NTN-B fields initialized here, populated after _read_last is defined
            cupom_360 = None
            cupom_30 = None
            cip_basis = None
            ntnb_5y_yield = None
            ntnb_10y_yield = None
            vix_val = 0
            dxy_val = 0
            ppp_fair = 0
            beer_fair = 0
            fx_fair = 0
            fx_mis = 0
            term_premium = 0
            front_fair = 0
            long_fair = 0

            try:
                spot_path = os.path.join(DATA_DIR, 'USDBRL.csv')
                if os.path.exists(spot_path):
                    sdf = pd.read_csv(spot_path)
                    current_spot = float(sdf.iloc[-1, 1])
            except: pass
            try:
                ptax_path = os.path.join(DATA_DIR, 'PTAX.csv')
                if os.path.exists(ptax_path):
                    sdf = pd.read_csv(ptax_path)
                    current_spot = float(sdf.iloc[-1, 1]) if current_spot == 0 else current_spot
            except: pass

            # Read latest rates from data files
            def _read_last(fname):
                try:
                    p = os.path.join(DATA_DIR, fname)
                    if os.path.exists(p):
                        df = pd.read_csv(p)
                        return float(df.iloc[-1, 1])
                except: pass
                return 0

            selic_target = _read_last('SELIC_META.csv')
            if selic_target < 1:
                selic_target = selic_target * 100  # Convert from decimal
            selic_over = _read_last('SELIC_OVER.csv')
            if selic_over > 1:
                selic_target = selic_over  # Use SELIC_OVER if available and in %
            vix_val = _read_last('VIX_YF.csv')
            dxy_val = _read_last('DXY_YF.csv')
            ust_2y = _read_last('FMP_UST_2Y.csv') or _read_last('UST2Y_YF.csv')
            ust_10y = _read_last('FMP_UST_10Y.csv') or _read_last('UST10Y_YF.csv')

            # Read DI rates from B3 data
            di_1y = _read_last('DI_1Y.csv')
            di_5y = _read_last('DI_5Y.csv')
            di_10y = _read_last('DI_10Y.csv')

            # Read EMBI spread (from IPEADATA + FRED extension)
            embi_spread = _read_last('EMBI_SPREAD.csv')
            if embi_spread <= 0:
                embi_spread = _read_last('CDS_5Y.csv') / 0.7  # Reverse CDS proxy
            if embi_spread > 2000:
                embi_spread = embi_spread / 100  # Normalize if in wrong units
            # Populate cupom cambial and NTN-B fields (now that _read_last is defined)
            cupom_360 = _read_last('SWAP_DIXDOL_360D.csv') or None
            cupom_30 = _read_last('SWAP_DIXDOL_30D.csv') or _read_last('FX_CUPOM_1M.csv') or None
            if cupom_360 is not None and ust_10y > 0:
                if di_5y == 0:
                    di_5y = _read_last('DI_5Y.csv') or _read_last('SWAP_PRE_360D.csv') or 0
                cip_basis = di_5y - cupom_360 - ust_10y if di_5y else None
            ntnb_5y_yield = _read_last('TESOURO_NTNB_5Y.csv') or _read_last('NTNB_5Y.csv') or None
            ntnb_10y_yield = _read_last('TESOURO_NTNB_10Y.csv') or _read_last('NTNB_10Y.csv') or None
            # FX fair values from feature engine
            if hasattr(engine.feature_engine, '_ppp_fair'):
                ppp_fair = engine.feature_engine._ppp_fair
            if hasattr(engine.feature_engine, '_beer_fair'):
                beer_fair = engine.feature_engine._beer_fair
            if hasattr(engine.feature_engine, '_fx_fair'):
                fx_fair = engine.feature_engine._fx_fair
            fx_mis = round((current_spot / fx_fair - 1) * 100, 1) if fx_fair > 0 and current_spot > 0 else 0
            # New indicators: BS-PPP and FEER
            ppp_bs_fair = 0
            feer_fair = 0
            if hasattr(engine.feature_engine, '_ppp_bs_fair'):
                ppp_bs_fair = engine.feature_engine._ppp_bs_fair
            if hasattr(engine.feature_engine, '_feer_fair'):
                feer_fair = engine.feature_engine._feer_fair

            # Rates fair values from Taylor Rule (FeatureEngine)
            if hasattr(engine.feature_engine, '_front_fair'):
                front_fair = engine.feature_engine._front_fair
            if hasattr(engine.feature_engine, '_belly_fair'):
                belly_fair = engine.feature_engine._belly_fair
            else:
                belly_fair = 0
            if hasattr(engine.feature_engine, '_long_fair'):
                long_fair = engine.feature_engine._long_fair
            if hasattr(engine.feature_engine, '_taylor_selic_star'):
                taylor_star = engine.feature_engine._taylor_selic_star
                taylor_gap_val = round(float(selic_target - taylor_star.iloc[-1]), 2) if len(taylor_star) > 0 else 0
            else:
                taylor_gap_val = 0

            # Term premium from feature_df
            if feat_df is not None and len(feat_df) > 0:
                lf = feat_df.iloc[-1]
                for tp_col in ['term_premium_slope', 'term_premium', 'Z_term_premium']:
                    if tp_col in lf.index and pd.notna(lf[tp_col]):
                        term_premium = round(float(lf[tp_col]), 2)
                        break

            # Portfolio vol from backtest summary (annualized)
            port_vol = 0
            overlay_summary = harness.summary.get('overlay', {})
            if overlay_summary:
                port_vol = overlay_summary.get('annualized_vol', 0)
            if port_vol == 0:
                # Estimate from overlay returns
                overlay_rets = [r.get('overlay_return', 0) for r in harness.results[-12:]]
                if overlay_rets:
                    port_vol = float(np.std(overlay_rets) * np.sqrt(12))

            # Dominant regime
            max_prob = 0
            dominant_regime = 'carry'
            for state, prob in regime.items():
                if prob > max_prob:
                    max_prob = prob
                    dominant_regime = state.replace('P_', '')

            output['current'] = {
                'date': latest_date.strftime('%Y-%m-%d'),
                'mu': {k: round(v * 100, 3) for k, v in mu.items()},
                'regime': {k: round(v, 3) for k, v in regime.items()},
                'weights': last_row,
                'score_total': round(score_total, 2),
                'direction': direction,
                'current_spot': round(current_spot, 4),
                'current_regime': dominant_regime,
                'state_variables': state_variables,
                'positions': positions,
                'selic_target': round(selic_target, 2),
                'di_1y': round(di_1y, 2),
                'di_2y': round(_read_last('DI_2Y.csv'), 2),
                'di_5y': round(di_5y, 2),
                'di_10y': round(di_10y, 2),
                'ust_2y': round(ust_2y, 2),
                'ust_10y': round(ust_10y, 2),
                'embi_spread': round(embi_spread, 0),
                'vix': round(vix_val, 2),
                'dxy': round(dxy_val, 2),
                'ppp_fair': round(ppp_fair, 2),
                'ppp_bs_fair': round(ppp_bs_fair, 2),
                'beer_fair': round(beer_fair, 2),
                'feer_fair': round(feer_fair, 2),
                'fx_fair_value': round(fx_fair, 2),
                'fx_misalignment': round(fx_mis, 1),
                'front_fair': round(front_fair, 2),
                'belly_fair': round(belly_fair, 2) if belly_fair else 0,
                'long_fair': round(long_fair, 2),
                'term_premium': round(term_premium, 2),
                'taylor_gap': taylor_gap_val,
                'portfolio_vol': round(port_vol * 100, 2) if port_vol < 1 else round(port_vol, 2),
                # NTN-B yields
                'ntnb_5y_yield': round(ntnb_5y_yield, 2) if ntnb_5y_yield else 0,
                'ntnb_10y_yield': round(ntnb_10y_yield, 2) if ntnb_10y_yield else 0,
                # Cupom cambial
                'cupom_cambial_360d': round(cupom_360, 2) if cupom_360 else 0,
                'cupom_cambial_30d': round(cupom_30, 2) if cupom_30 else 0,
                'cip_basis': round(cip_basis, 2) if cip_basis else 0,
                # IPCA Expectations 12M
                'ipca_exp_12m': round(float(ipca_exp.iloc[-1]), 2) if hasattr(ipca_exp, 'iloc') and len(ipca_exp) > 0 else 0,
            }

    # ============================================================
    # BUILD TIMESERIES FOR FRONTEND CHARTS
    # ============================================================
    if harness.engine and harness.engine.feature_engine:
        fe = harness.engine.feature_engine

        # Add composite equilibrium breakdown if available
        log(f"  [EQ-DEBUG] has _compositor={hasattr(fe, '_compositor')}, is_not_None={getattr(fe, '_compositor', None) is not None}")
        log(f"  [EQ-DEBUG] has _composite_rstar={hasattr(fe, '_composite_rstar')}, has _eq_model_results={hasattr(fe, '_eq_model_results')}")
        log(f"  [EQ-DEBUG] output has 'current' key: {'current' in output}")
        try:
            if hasattr(fe, '_compositor') and fe._compositor is not None:
                compositor = fe._compositor
                eq_data = {
                    'composite_rstar': round(float(fe._composite_rstar.iloc[-1]), 2) if hasattr(fe, '_composite_rstar') and len(fe._composite_rstar) > 0 else None,
                    'model_contributions': compositor.model_contributions,
                    'method': 'composite_5model',
                }
                # Add individual model r* values
                if hasattr(fe, '_eq_model_results'):
                    for name, series in fe._eq_model_results.items():
                        if len(series) > 0:
                            eq_data[f'rstar_{name}'] = round(float(series.iloc[-1]), 2)
                # Add SELIC* (equilibrium policy rate)
                if hasattr(fe, '_taylor_selic_star') and len(fe._taylor_selic_star) > 0:
                    eq_data['selic_star'] = round(float(fe._taylor_selic_star.iloc[-1]), 2)
                # Add fiscal decomposition if available (serialize to last values only)
                if hasattr(fe, '_fiscal_decomposition') and fe._fiscal_decomposition:
                    fd = fe._fiscal_decomposition
                    eq_data['fiscal_decomposition'] = {
                        k: round(float(v.iloc[-1]), 2) if hasattr(v, 'iloc') and len(v) > 0 else v
                        for k, v in fd.items()
                    }
                # Add ACM term premium if available
                if hasattr(fe, '_acm_term_premium') and fe._acm_term_premium is not None and len(fe._acm_term_premium) > 0:
                    eq_data['acm_term_premium_5y'] = round(float(fe._acm_term_premium.iloc[-1]), 2)
                # Add regime weights info
                eq_data['regime_weights'] = {
                    'carry': compositor.REGIME_WEIGHTS.get('carry', {}),
                    'riskoff': compositor.REGIME_WEIGHTS.get('riskoff', {}),
                    'domestic_stress': compositor.REGIME_WEIGHTS.get('domestic_stress', {}),
                }
                if 'current' in output:
                    output['current']['equilibrium'] = eq_data
                    log(f"  [EQ-DEBUG] Successfully added equilibrium to output['current']")
                    # v4.3: Add feature selection results with stability + temporal tracking
                    if hasattr(harness.engine, 'alpha_models') and hasattr(harness.engine.alpha_models, 'feature_selection_results'):
                        fs_results = harness.engine.alpha_models.feature_selection_results
                        if fs_results:
                            output['current']['feature_selection'] = fs_results
                            output['feature_selection'] = fs_results
                            total_feats = sum(r.get('total_features', 0) for r in fs_results.values())
                            final_feats = sum(r.get('final', {}).get('n_features', 0) for r in fs_results.values())
                            log(f"  [FS] Feature selection: {final_feats}/{total_feats} features retained across all instruments")
                            
                            # v5.2: Add regime-adaptive FS metadata
                            alpha_models = harness.engine.alpha_models
                            if hasattr(alpha_models, '_fs_refit_count'):
                                output['feature_selection_regime_adaptive'] = {
                                    'regime_triggered_refits': alpha_models._fs_refit_count,
                                    'cooldown_months': alpha_models._fs_refit_cooldown,
                                    'current_dominant_regime': alpha_models._prev_dominant_regime,
                                    'total_steps': alpha_models._current_step,
                                }
                                log(f"  [FS] v5.2 Regime-adaptive: {alpha_models._fs_refit_count} regime-triggered refits "
                                    f"across {alpha_models._current_step} steps")
                            
                            # v4.3: Temporal tracking — save snapshot and detect changes
                            try:
                                from feature_selection import TemporalSelectionTracker
                                run_date = output.get('current', {}).get('date', datetime.now().strftime('%Y-%m-%d'))
                                TemporalSelectionTracker.save_snapshot(fs_results, run_date)
                                temporal_changes = TemporalSelectionTracker.detect_changes(fs_results)
                                temporal_summary = TemporalSelectionTracker.build_temporal_summary()
                                rolling_stability = TemporalSelectionTracker.build_rolling_stability(window_months=12)
                                output['feature_selection_temporal'] = {
                                    'changes': temporal_changes,
                                    'summary': temporal_summary,
                                    'rolling_stability': rolling_stability,
                                }
                                log(f"  [FS] Temporal tracking: {temporal_summary.get('n_snapshots', 0)} snapshots, rolling window: {rolling_stability.get('n_snapshots', 0)}")
                            except Exception as te:
                                log(f"  [FS] Temporal tracking failed: {te}")
                else:
                    log(f"  [EQ-DEBUG] WARNING: output['current'] does not exist!")
            else:
                log(f"  [EQ-DEBUG] _compositor not available, skipping equilibrium")
        except Exception as e:
            log(f"  [EQ-DEBUG] ERROR adding equilibrium: {e}")
        dl = harness.engine.data_layer
        feat_df = fe.feature_df
        m = dl.monthly

        # --- State Variables Timeseries (Z-scores over time) ---
        z_col_map = {
            'Z_X1_diferencial_real': 'Z_real_diff',
            'Z_X2_surpresa_inflacao': 'Z_infl_surprise',
            'Z_X3_fiscal_risk': 'Z_fiscal',
            'Z_X4_termos_de_troca': 'Z_tot',
            'Z_X5_dolar_global': 'Z_dxy',
            'Z_X6_risk_global': 'Z_vix',
            'Z_X7_hiato': 'Z_hiato',
            # v4.0: Equilibrium-derived features
            'Z_X13_policy_gap': 'Z_policy_gap',
            'Z_X14_rstar_composite': 'Z_rstar_composite',
            'Z_X15_rstar_momentum': 'Z_rstar_momentum',
            'Z_X16_fiscal_component': 'Z_fiscal_component',
            'Z_X17_sovereign_component': 'Z_sovereign_component',
            'Z_X18_selic_star_gap': 'Z_selic_star_gap',
        }
        if feat_df is not None and len(feat_df) > 0:
            state_vars_ts = []
            for idx in feat_df.index:
                row = feat_df.loc[idx]
                pt = {'date': idx.strftime('%Y-%m-%d')}
                for out_key, feat_col in z_col_map.items():
                    if feat_col in row.index and pd.notna(row[feat_col]):
                        pt[out_key] = round(float(row[feat_col]), 3)
                    else:
                        pt[out_key] = None
                state_vars_ts.append(pt)
            output['state_variables_ts'] = state_vars_ts
            log(f"  State variables timeseries: {len(state_vars_ts)} points")

        # --- Cyclical Factors Timeseries (raw macro) ---
        cyclical_map = {
            'DXY': 'dxy',
            'VIX': 'vix',
            'EMBI': 'embi_spread',
            'SELIC': 'selic_target',
            'DI_1Y': 'di_1y',
            'DI_5Y': 'di_5y',
            'IPCA_Exp': 'ipca_exp',
            'CDS_5Y': 'cds_5y',
        }
        # Find common dates across all cyclical series
        cyclical_series = {}
        for out_key, m_key in cyclical_map.items():
            s = m.get(m_key, pd.Series(dtype=float))
            if len(s) > 0:
                cyclical_series[out_key] = s

        if cyclical_series:
            # Use union of all dates, fill forward
            all_dates = sorted(set().union(*[set(s.index) for s in cyclical_series.values()]))
            cyclical_ts = []
            for dt in all_dates:
                pt = {'date': dt.strftime('%Y-%m-%d')}
                has_any = False
                for out_key, s in cyclical_series.items():
                    avail = s.loc[:dt]
                    if len(avail) > 0:
                        val = float(avail.iloc[-1])
                        pt[out_key] = round(val, 2)
                        has_any = True
                    else:
                        pt[out_key] = None
                if has_any:
                    cyclical_ts.append(pt)
            output['cyclical_ts'] = cyclical_ts
            log(f"  Cyclical factors timeseries: {len(cyclical_ts)} points")

        # --- Fair Value Timeseries (spot + PPP + PPP_BS + BEER + FEER + FX fair) ---
        spot_m = m.get('ptax', m.get('spot', pd.Series(dtype=float)))
        ppp_fair_ts = fe.features.get('ppp_fair_ts', pd.Series(dtype=float))
        ppp_bs_fair_ts = fe.features.get('ppp_bs_fair_ts', pd.Series(dtype=float))
        beer_fair_ts = fe.features.get('beer_fair_ts', pd.Series(dtype=float))
        feer_fair_ts = fe.features.get('feer_fair_ts', pd.Series(dtype=float))
        fx_fair_ts = fe.features.get('fx_fair_ts', pd.Series(dtype=float))

        if len(spot_m) > 0:
            # Reindex each component to spot dates with forward-fill for recent months
            ppp_reindexed = ppp_fair_ts.reindex(spot_m.index, method='ffill') if len(ppp_fair_ts) > 0 else pd.Series(dtype=float)
            ppp_bs_reindexed = ppp_bs_fair_ts.reindex(spot_m.index, method='ffill') if len(ppp_bs_fair_ts) > 0 else pd.Series(dtype=float)
            beer_reindexed = beer_fair_ts.reindex(spot_m.index, method='ffill') if len(beer_fair_ts) > 0 else pd.Series(dtype=float)
            feer_reindexed = feer_fair_ts.reindex(spot_m.index, method='ffill') if len(feer_fair_ts) > 0 else pd.Series(dtype=float)
            fx_reindexed = fx_fair_ts.reindex(spot_m.index, method='ffill') if len(fx_fair_ts) > 0 else pd.Series(dtype=float)

            fv_ts = []
            for dt in spot_m.index:
                pt = {
                    'date': dt.strftime('%Y-%m-%d'),
                    'spot': round(float(spot_m.loc[dt]), 4),
                }
                if len(ppp_reindexed) > 0:
                    val = ppp_reindexed.get(dt)
                    pt['ppp_fair'] = round(float(val), 4) if pd.notna(val) else None
                if len(ppp_bs_reindexed) > 0:
                    val = ppp_bs_reindexed.get(dt)
                    pt['ppp_bs_fair'] = round(float(val), 4) if pd.notna(val) else None
                if len(beer_reindexed) > 0:
                    val = beer_reindexed.get(dt)
                    pt['beer_fair'] = round(float(val), 4) if pd.notna(val) else None
                if len(feer_reindexed) > 0:
                    val = feer_reindexed.get(dt)
                    pt['feer_fair'] = round(float(val), 4) if pd.notna(val) else None
                if len(fx_reindexed) > 0:
                    val = fx_reindexed.get(dt)
                    pt['fx_fair'] = round(float(val), 4) if pd.notna(val) else None
                fv_ts.append(pt)
            output['fair_value_ts'] = fv_ts
            log(f"  Fair value timeseries: {len(fv_ts)} points")

        # --- Score Timeseries (from backtest results) ---
        score_ts = []
        for r in harness.results:
            score_ts.append({
                'date': r['date'],
                'score_total': round(r.get('score_total', 0), 3),
                'mu_fx': round(r.get('mu_fx', 0), 4),
                'mu_front': round(r.get('mu_front', 0), 4),
                'mu_belly': round(r.get('mu_belly', 0), 4),
                'mu_long': round(r.get('mu_long', 0), 4),
                'mu_hard': round(r.get('mu_hard', 0), 4),
            })
        output['score_ts'] = score_ts
        log(f"  Score timeseries: {len(score_ts)} points")

    # ============================================================
    # v3.8: SHAP FEATURE IMPORTANCE
    # ============================================================
    if harness.engine and harness.engine.alpha_models:
        try:
            ret_df = harness.engine.data_layer.ret_df
            if ret_df is not None and len(ret_df) > 0:
                latest_date = ret_df.index[-1]
                log(f"\n  Computing SHAP feature importance at {latest_date}...")
                shap_importance = harness.engine.alpha_models.compute_shap_importance(latest_date)
                if shap_importance:
                    output['shap_importance'] = shap_importance
                    for inst, feats in shap_importance.items():
                        n_feats = len(feats)
                        top3 = sorted(feats.items(), key=lambda x: abs(x[1].get('current', 0)), reverse=True)[:3]
                        top3_str = ', '.join(f"{f}={v['current']:.4f}" for f, v in top3)
                        log(f"    {inst}: {n_feats} features, top3: {top3_str}")
                else:
                    log("    SHAP: no importance computed")
                    output['shap_importance'] = {}
        except Exception as e:
            log(f"    SHAP computation failed: {e}")
            output['shap_importance'] = {}

    # ============================================================
    # v3.9: SHAP HISTORY (temporal evolution from backtest)
    # ============================================================
    shap_history = getattr(harness, 'shap_history', [])
    output['shap_history'] = shap_history
    if shap_history:
        n_dates = len(set(s['date'] for s in shap_history))
        n_instruments = len(set(s['instrument'] for s in shap_history))
        log(f"  SHAP history: {len(shap_history)} entries, {n_dates} dates, {n_instruments} instruments")

    # ============================================================
    # v5.7: r* TIMESERIES (composite equilibrium rate history)
    # ============================================================
    rstar_ts = []
    try:
        if harness.engine and harness.engine.feature_engine:
            fe = harness.engine.feature_engine
            if hasattr(fe, '_composite_rstar') and fe._composite_rstar is not None and len(fe._composite_rstar) > 0:
                composite = fe._composite_rstar
                selic_star_s = getattr(fe, '_taylor_selic_star', pd.Series(dtype=float))
                eq_models = getattr(fe, '_eq_model_results', {})
                m = fe.dl.monthly if hasattr(fe, 'dl') else {}
                # Use selic_over (annualized % p.a.) for selic_actual display
                # selic_meta/selic_target is daily rate in decimal (0.055 = 5.5% daily annualized)
                selic_s = m.get('selic_over', m.get('selic_target', pd.Series(dtype=float)))
                # If values are < 1, they're in decimal form → convert to %
                if len(selic_s) > 0 and selic_s.iloc[-1] < 1:
                    selic_s = selic_s * 100  # Convert decimal to %
                ipca_exp = m.get('ipca_exp_12m', m.get('ipca_exp', pd.Series(dtype=float)))

                for dt in composite.index:
                    dt_str = dt.strftime('%Y-%m') if hasattr(dt, 'strftime') else str(dt)[:7]
                    point = {
                        'date': dt_str,
                        'composite_rstar': round(float(composite.loc[dt]), 4),
                    }
                    if dt in selic_star_s.index:
                        point['selic_star'] = round(float(selic_star_s.loc[dt]), 4)
                    for name, series in eq_models.items():
                        if dt in series.index:
                            point[f'rstar_{name}'] = round(float(series.loc[dt]), 4)
                    if dt in selic_s.index:
                        point['selic_actual'] = round(float(selic_s.loc[dt]), 4)
                    if dt in ipca_exp.index:
                        point['ipca_exp'] = round(float(ipca_exp.loc[dt]), 4)
                    rstar_ts.append(point)

                log(f"  r* timeseries: {len(rstar_ts)} monthly points")
    except Exception as e:
        log(f"  r* timeseries generation failed: {e}")
    output['rstar_ts'] = rstar_ts

    return output


if __name__ == '__main__':
    result = run_v2()
    # Output JSON to stdout
    sys.stdout.write(json.dumps(result, default=str))
    sys.stdout.flush()
