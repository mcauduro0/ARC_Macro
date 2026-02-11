"""
Data Collection Module for BRLUSD Institutional FX Model
Sources: FRED, BCB, World Bank, Yahoo Finance, BIS
"""

import pandas as pd
import numpy as np
import yfinance as yf
import wbgapi as wb
import requests
import json
import os
from datetime import datetime, timedelta
import warnings
warnings.filterwarnings('ignore')

DATA_DIR = "/home/ubuntu/brlusd_model/data"
os.makedirs(DATA_DIR, exist_ok=True)

# ============================================================
# 1. FRED Data (no API key needed for public series via direct URL)
# ============================================================
def fetch_fred_series(series_id, start='2000-01-01'):
    """Fetch data from FRED via direct CSV download"""
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}&cosd={start}"
    try:
        df = pd.read_csv(url, parse_dates=['DATE'], index_col='DATE')
        df.columns = [series_id]
        df[series_id] = pd.to_numeric(df[series_id], errors='coerce')
        print(f"  FRED {series_id}: {len(df.dropna())} obs from {df.dropna().index.min().strftime('%Y-%m')} to {df.dropna().index.max().strftime('%Y-%m')}")
        return df
    except Exception as e:
        print(f"  FRED {series_id} FAILED: {e}")
        return pd.DataFrame()

def collect_fred_data():
    """Collect all FRED series needed"""
    print("\n=== FRED Data ===")
    series = {
        'CPIAUCSL': 'CPI_US',           # US CPI (monthly)
        'DEXBZUS': 'BRLUSD_FRED',       # BRL/USD exchange rate (daily)
        'DTWEXBGS': 'DXY_BROAD',        # Trade-weighted USD (broad)
        'DGS10': 'UST10Y',              # US 10Y Treasury yield
        'RBBRBIS': 'REER_BIS',          # Real Broad Effective Exchange Rate Brazil (BIS)
        'T10YIE': 'US_BREAKEVEN_10Y',   # US 10Y breakeven inflation
        'PCEPILFE': 'CORE_PCE',         # Core PCE
    }
    
    frames = {}
    for fred_id, name in series.items():
        df = fetch_fred_series(fred_id, '1995-01-01')
        if not df.empty:
            df.columns = [name]
            frames[name] = df
    
    return frames

# ============================================================
# 2. BCB (Banco Central do Brasil) Data via SGS API
# ============================================================
def fetch_bcb_series(code, name, start='01/01/2000'):
    """Fetch data from BCB SGS API"""
    url = f"https://api.bcb.gov.br/dados/serie/bcdata.sgs.{code}/dados?formato=json&dataInicial={start}"
    try:
        r = requests.get(url, timeout=30)
        data = r.json()
        df = pd.DataFrame(data)
        df['data'] = pd.to_datetime(df['data'], format='%d/%m/%Y')
        df['valor'] = pd.to_numeric(df['valor'], errors='coerce')
        df = df.set_index('data')
        df.columns = [name]
        print(f"  BCB {name} (code {code}): {len(df.dropna())} obs from {df.dropna().index.min().strftime('%Y-%m')} to {df.dropna().index.max().strftime('%Y-%m')}")
        return df
    except Exception as e:
        print(f"  BCB {name} FAILED: {e}")
        return pd.DataFrame()

def collect_bcb_data():
    """Collect all BCB series"""
    print("\n=== BCB Data ===")
    series = {
        433: 'IPCA_MONTHLY',          # IPCA monthly % change
        4390: 'PTAX_SELL',             # PTAX selling rate (BRL/USD)
        4189: 'SELIC_TARGET',          # SELIC target rate
        13005: 'SWAP_DI_PRE_360',      # DI x Pre swap 360 days
        11752: 'DIVIDA_BRUTA_PIB',     # Gross public debt / GDP
        22707: 'REER_BCB',             # Real Effective Exchange Rate (BCB)
        27574: 'TERMS_OF_TRADE',       # Terms of trade index
        22701: 'BOP_CURRENT_ACCOUNT',  # Current account balance (monthly USD mn)
    }
    
    frames = {}
    for code, name in series.items():
        df = fetch_bcb_series(code, name, '01/01/1995')
        if not df.empty:
            frames[name] = df
    
    return frames

# ============================================================
# 3. World Bank Data (PPP, NFA)
# ============================================================
def collect_worldbank_data():
    """Collect World Bank indicators"""
    print("\n=== World Bank Data ===")
    indicators = {
        'PA.NUS.PPP': 'PPP_FACTOR',           # PPP conversion factor
        'PA.NUS.PPPC.RF': 'PPP_PRICE_LEVEL',  # Price level ratio
        'NY.GDP.MKTP.CD': 'GDP_NOMINAL_USD',   # GDP nominal USD
        'BN.CAB.XOKA.GD.ZS': 'CA_GDP',        # Current account % GDP
    }
    
    frames = {}
    for ind_code, name in indicators.items():
        try:
            df = wb.data.DataFrame(ind_code, economy='BRA', time=range(1995, 2026))
            df = df.T
            df.columns = [name]
            # Parse year index
            df.index = pd.to_datetime([str(idx).replace('YR', '') for idx in df.index], format='%Y')
            df[name] = pd.to_numeric(df[name], errors='coerce')
            valid = df.dropna()
            if len(valid) > 0:
                print(f"  WB {name}: {len(valid)} obs from {valid.index.min().year} to {valid.index.max().year}")
            frames[name] = df
        except Exception as e:
            print(f"  WB {name} FAILED: {e}")
    
    return frames

# ============================================================
# 4. Yahoo Finance Data (DXY, Commodities, CDS proxy)
# ============================================================
def collect_yfinance_data():
    """Collect market data from Yahoo Finance"""
    print("\n=== Yahoo Finance Data ===")
    tickers = {
        'DX-Y.NYB': 'DXY',           # US Dollar Index
        'CL=F': 'WTI_OIL',           # WTI Crude Oil
        '^BCOM': 'BCOM',             # Bloomberg Commodity Index
        'BRL=X': 'BRLUSD_YF',        # BRL/USD
        'EWZ': 'EWZ',                # iShares MSCI Brazil ETF (risk proxy)
        'SB=F': 'SUGAR',             # Sugar futures
        'KC=F': 'COFFEE',            # Coffee futures
        'ZS=F': 'SOYBEANS',          # Soybeans futures
        'HG=F': 'COPPER',            # Copper futures
        'GC=F': 'GOLD',              # Gold futures
    }
    
    frames = {}
    for ticker, name in tickers.items():
        try:
            data = yf.download(ticker, start='2000-01-01', progress=False)
            if len(data) > 0:
                # Handle both single and multi-level columns
                if isinstance(data.columns, pd.MultiIndex):
                    close = data['Close'].iloc[:, 0]
                else:
                    close = data['Close']
                df = pd.DataFrame({name: close})
                df.index = pd.to_datetime(df.index)
                df.index = df.index.tz_localize(None) if df.index.tz else df.index
                valid = df.dropna()
                print(f"  YF {name}: {len(valid)} obs from {valid.index.min().strftime('%Y-%m')} to {valid.index.max().strftime('%Y-%m')}")
                frames[name] = df
        except Exception as e:
            print(f"  YF {name} FAILED: {e}")
    
    return frames

# ============================================================
# 5. Build Brazil Commodity Index
# ============================================================
def build_brazil_commodity_index(yf_frames):
    """Build a Brazil-weighted commodity index"""
    print("\n=== Building Brazil Commodity Index ===")
    # Weights based on Brazil export composition
    weights = {
        'SOYBEANS': 0.30,
        'WTI_OIL': 0.20,
        'SUGAR': 0.10,
        'COFFEE': 0.10,
        'COPPER': 0.15,
        'GOLD': 0.15,
    }
    
    available = {}
    for name, w in weights.items():
        if name in yf_frames:
            available[name] = (yf_frames[name], w)
    
    if not available:
        print("  No commodity data available!")
        return pd.DataFrame()
    
    # Normalize each to 100 at start, then weighted average
    normalized = {}
    for name, (df, w) in available.items():
        series = df.iloc[:, 0].dropna()
        normalized[name] = (series / series.iloc[0]) * 100
    
    combined = pd.DataFrame(normalized)
    combined = combined.dropna()
    
    total_w = sum(w for _, (_, w) in available.items())
    index = pd.Series(0.0, index=combined.index)
    for name, (_, w) in available.items():
        if name in combined.columns:
            index += combined[name] * (w / total_w)
    
    result = pd.DataFrame({'BRAZIL_COMM_IDX': index})
    print(f"  Brazil Commodity Index: {len(result)} obs")
    return result

# ============================================================
# 6. CDS Proxy via spread calculation
# ============================================================
def fetch_cds_proxy():
    """
    Fetch Brazil CDS 5Y proxy. 
    Use EMBI+ spread from BCB or compute from sovereign bond spread.
    """
    print("\n=== CDS Proxy ===")
    # BCB series 12461 = EMBI+ Brazil spread
    df = fetch_bcb_series(12461, 'EMBI_SPREAD', '01/01/2000')
    if not df.empty:
        print(f"  Using EMBI+ spread as CDS proxy")
        return df
    
    # Fallback: use EWZ implied vol as risk proxy
    print("  EMBI not available, will use EWZ as risk proxy")
    return pd.DataFrame()

# ============================================================
# MAIN COLLECTION
# ============================================================
def main():
    print("=" * 60)
    print("BRLUSD MODEL - DATA COLLECTION")
    print("=" * 60)
    
    all_data = {}
    
    # 1. FRED
    fred_frames = collect_fred_data()
    all_data.update(fred_frames)
    
    # 2. BCB
    bcb_frames = collect_bcb_data()
    all_data.update(bcb_frames)
    
    # 3. World Bank
    wb_frames = collect_worldbank_data()
    all_data.update(wb_frames)
    
    # 4. Yahoo Finance
    yf_frames = collect_yfinance_data()
    all_data.update(yf_frames)
    
    # 5. Brazil Commodity Index
    comm_idx = build_brazil_commodity_index(yf_frames)
    if not comm_idx.empty:
        all_data['BRAZIL_COMM_IDX'] = comm_idx
    
    # 6. CDS Proxy
    cds = fetch_cds_proxy()
    if not cds.empty:
        all_data['EMBI_SPREAD'] = cds
    
    # Save individual series
    print("\n=== Saving Data ===")
    for name, df in all_data.items():
        path = os.path.join(DATA_DIR, f"{name}.csv")
        df.to_csv(path)
        print(f"  Saved {name}: {path}")
    
    # Create summary
    summary = []
    for name, df in all_data.items():
        valid = df.dropna()
        if len(valid) > 0:
            summary.append({
                'Series': name,
                'Obs': len(valid),
                'Start': valid.index.min().strftime('%Y-%m-%d'),
                'End': valid.index.max().strftime('%Y-%m-%d'),
                'Last_Value': valid.iloc[-1, 0]
            })
    
    summary_df = pd.DataFrame(summary)
    summary_df.to_csv(os.path.join(DATA_DIR, 'data_summary.csv'), index=False)
    print(f"\n  Summary saved with {len(summary_df)} series")
    print("\n" + summary_df.to_string(index=False))
    
    return all_data

if __name__ == '__main__':
    main()
