"""
Macro Risk OS - Data Collector v2
Collects all market and macro data with correct BCB series codes and normalization.
All yields are in % per annum. All spreads in basis points.
"""

import sys
import os
import json
import pandas as pd
import numpy as np
import requests
import warnings
warnings.filterwarnings('ignore')

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
os.makedirs(DATA_DIR, exist_ok=True)


def log(msg):
    print(msg, file=sys.stderr)


# ============================================================
# API HELPERS
# ============================================================

def fetch_bcb(code, name, start_year=2000):
    """Fetch series from BCB SGS API (chunked for large series)"""
    all_data = []
    for sy in range(start_year, 2027, 10):
        ey = min(sy + 9, 2026)
        url = f"https://api.bcb.gov.br/dados/serie/bcdata.sgs.{code}/dados?formato=json&dataInicial=01/01/{sy}&dataFinal=31/12/{ey}"
        try:
            r = requests.get(url, timeout=30)
            if r.status_code == 200:
                data = r.json()
                if data:
                    all_data.extend(data)
        except:
            pass
    
    if all_data:
        df = pd.DataFrame(all_data)
        df['date'] = pd.to_datetime(df['data'], format='%d/%m/%Y')
        df['value'] = pd.to_numeric(df['valor'], errors='coerce')
        df = df.set_index('date')['value'].dropna().sort_index()
        df = df[~df.index.duplicated(keep='last')]
        df.to_csv(os.path.join(DATA_DIR, f"{name}.csv"))
        log(f"  [BCB] {name}: {len(df)} pts, last={df.iloc[-1]:.4f}")
        return df
    log(f"  [BCB] {name}: NO DATA")
    return pd.Series(dtype=float)


def fetch_fred(series_id, name):
    """Fetch from FRED API"""
    api_key = os.environ.get('FRED_API_KEY', 'e63bf4ad4b21136be0b68c27e7e510d9')
    url = f"https://api.stlouisfed.org/fred/series/observations?series_id={series_id}&api_key={api_key}&file_type=json"
    try:
        r = requests.get(url, timeout=30)
        if r.status_code == 200:
            data = r.json()['observations']
            df = pd.DataFrame(data)
            df['date'] = pd.to_datetime(df['date'])
            df['value'] = pd.to_numeric(df['value'], errors='coerce')
            df = df.set_index('date')['value'].dropna()
            df.to_csv(os.path.join(DATA_DIR, f"{name}.csv"))
            log(f"  [FRED] {name}: {len(df)} pts, last={df.iloc[-1]:.4f}")
            return df
    except Exception as e:
        log(f"  [FRED] {name} FAILED: {e}")
    return pd.Series(dtype=float)


def fetch_yahoo(ticker, name):
    """Fetch from Yahoo Finance"""
    import yfinance as yf
    try:
        data = yf.download(ticker, period='max', progress=False)
        if len(data) > 0:
            s = data['Close'].dropna()
            if hasattr(s, 'columns'):
                s = s.iloc[:, 0]
            s.to_csv(os.path.join(DATA_DIR, f"{name}.csv"))
            log(f"  [YF] {name}: {len(s)} pts, last={s.iloc[-1]:.4f}")
            return s
    except Exception as e:
        log(f"  [YF] {name} FAILED: {e}")
    return pd.Series(dtype=float)


def fetch_ipeadata(code, name):
    """Fetch from IPEADATA API"""
    try:
        url = f"http://www.ipeadata.gov.br/api/odata4/ValoresSerie(SERCODIGO='{code}')"
        r = requests.get(url, timeout=30)
        if r.status_code == 200:
            data = r.json().get('value', [])
            if data:
                records = [(d['VALDATA'][:10], float(d['VALVALOR'])) for d in data if d.get('VALVALOR') is not None]
                df = pd.DataFrame(records, columns=['date', 'value'])
                df['date'] = pd.to_datetime(df['date'])
                df = df.set_index('date')['value'].sort_index()
                df = df[~df.index.duplicated(keep='last')]
                df.to_csv(os.path.join(DATA_DIR, f"{name}.csv"))
                log(f"  [IPEA] {name}: {len(df)} pts, last={df.iloc[-1]:.4f}")
                return df
    except Exception as e:
        log(f"  [IPEA] {name} FAILED: {e}")
    return pd.Series(dtype=float)


# ============================================================
# COLLECT ALL DATA
# ============================================================

def collect_all():
    """Collect all data for Macro Risk OS"""
    log("[DATA] Starting Macro Risk OS v2 data collection...")
    
    # ---- FX ----
    log("\n[FX]")
    fetch_yahoo('USDBRL=X', 'BRLUSD_YF')
    fetch_bcb(3697, 'PTAX_SELL')
    fetch_yahoo('DX-Y.NYB', 'DXY_YF')
    fetch_fred('DTWEXBGS', 'DXY_FRED')
    
    # FX cupom cambial (forward points proxy)
    fetch_bcb(3955, 'FX_CUPOM_1M')
    fetch_bcb(3956, 'FX_CUPOM_3M')
    fetch_bcb(3957, 'FX_CUPOM_12M')
    
    # ---- LOCAL RATES (yields in % a.a.) ----
    log("\n[LOCAL RATES]")
    # BCB 4189 = Swap DI x Pre 360d daily (% a.a.) - CONFIRMED CORRECT
    fetch_bcb(4189, 'DI_YIELD_1Y')
    
    # For longer tenors, use IPEADATA which has proper yield data
    # IPEADATA: BMF366_SWAPDI36012_D = Swap DI x Pre 360d
    # IPEADATA: BMF366_SWAPDI72012_D = Swap DI x Pre 720d  
    fetch_ipeadata('BMF366_SWAPDI72012', 'DI_YIELD_2Y_IPEA')
    fetch_ipeadata('BMF366_SWAPDI108012', 'DI_YIELD_3Y_IPEA')
    fetch_ipeadata('BMF366_SWAPDI180012', 'DI_YIELD_5Y_IPEA')
    
    # SELIC target and overnight
    fetch_bcb(432, 'SELIC_META')  # SELIC meta (target rate)
    fetch_bcb(4393, 'SELIC_OVERNIGHT')  # SELIC effective overnight
    
    # NTN-B real yields (ANBIMA indicative rates)
    # BCB 12466/12467 are PU not yields - use IPEADATA instead
    fetch_ipeadata('ANBIMA366_TJTLN1_D', 'NTNB_YIELD_5Y_IPEA')
    fetch_ipeadata('ANBIMA366_TJTLN2_D', 'NTNB_YIELD_10Y_IPEA')
    
    # ---- US RATES ----
    log("\n[US RATES]")
    fetch_fred('DGS2', 'UST_2Y')
    fetch_fred('DGS5', 'UST_5Y')
    fetch_fred('DGS10', 'UST_10Y')
    fetch_fred('DGS30', 'UST_30Y')
    fetch_fred('DFEDTARU', 'FED_FUNDS_UPPER')
    fetch_fred('EFFR', 'FED_FUNDS_EFFECTIVE')
    fetch_fred('DFII5', 'US_TIPS_5Y')
    fetch_fred('DFII10', 'US_TIPS_10Y')
    
    # ---- CREDIT / SOVEREIGN ----
    log("\n[CREDIT]")
    # EMBI+ Brazil spread (BCB 40940 - monthly, in bps)
    embi = fetch_bcb(40940, 'EMBI_PLUS')
    if len(embi) == 0:
        # Try IPEADATA
        fetch_ipeadata('JPM366_EMBI366', 'EMBI_PLUS_IPEA')
    
    # CDS 5Y Brazil
    fetch_fred('BRAZCDS5YUSDAM', 'CDS_5Y_BRAZIL')
    
    # ---- MACRO LOCAL ----
    log("\n[MACRO LOCAL]")
    fetch_bcb(433, 'IPCA_MONTHLY')
    fetch_bcb(13522, 'IPCA_EXP_12M')  # Focus IPCA 12m
    fetch_bcb(24364, 'DIVIDA_BRUTA_PIB')
    fetch_bcb(22707, 'BOP_CURRENT_ACCOUNT')
    fetch_bcb(11752, 'TERMS_OF_TRADE')
    fetch_bcb(27574, 'BRAZIL_COMM_IDX')
    fetch_bcb(5793, 'PRIMARY_BALANCE')
    fetch_bcb(24363, 'IBC_BR')
    
    # ---- MACRO GLOBAL ----
    log("\n[MACRO GLOBAL]")
    fetch_fred('CPIAUCSL', 'CPI_US')
    fetch_fred('T10YIE', 'US_BREAKEVEN_10Y')
    fetch_fred('VIXCLS', 'VIX')
    fetch_fred('NFCI', 'NFCI')
    fetch_fred('STLFSI2', 'FCI_STLFSI')
    fetch_fred('MICH', 'US_CPI_EXP_MICHIGAN')
    
    # ---- STRUCTURAL ----
    log("\n[STRUCTURAL]")
    try:
        url = "https://api.worldbank.org/v2/country/BRA/indicator/PA.NUS.PPP?format=json&per_page=100"
        r = requests.get(url, timeout=30)
        if r.status_code == 200:
            data = r.json()[1]
            records = [(f"{d['date']}-01-01", float(d['value'])) for d in data if d['value']]
            df = pd.DataFrame(records, columns=['date', 'value'])
            df['date'] = pd.to_datetime(df['date'])
            df = df.set_index('date')['value'].sort_index()
            df.to_csv(os.path.join(DATA_DIR, "PPP_FACTOR.csv"))
            log(f"  [WB] PPP_FACTOR: {len(df)} pts")
    except Exception as e:
        log(f"  [WB] PPP_FACTOR FAILED: {e}")
    
    # BIS REER
    try:
        url = "https://stats.bis.org/api/v2/data/dataflow/BIS/WS_EER/1.0/M.R.N.BR?format=csv"
        r = requests.get(url, timeout=30)
        if r.status_code == 200:
            from io import StringIO
            df = pd.read_csv(StringIO(r.text))
            if 'TIME_PERIOD' in df.columns and 'OBS_VALUE' in df.columns:
                df['date'] = pd.to_datetime(df['TIME_PERIOD'])
                df = df.set_index('date')['OBS_VALUE'].dropna().sort_index()
                df.to_csv(os.path.join(DATA_DIR, "REER_BIS.csv"))
                log(f"  [BIS] REER: {len(df)} pts")
    except Exception as e:
        log(f"  [BIS] REER FAILED: {e}")
    
    log("\n[DATA] Collection complete")


if __name__ == '__main__':
    collect_all()
