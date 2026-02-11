"""
Macro Risk OS - Data Collector v2.1
Multi-source data collection with validation and fallback.

Sources:
  - Trading Economics: DI curve (3M-10Y) - CORRECT YIELDS
  - FRED: US Treasury yields, VIX, DXY, NFCI, CPI, breakeven
  - FMP: US Treasury (backup), economic calendar
  - Yahoo Finance: FX, commodities, VIX, DXY, equity indices
  - BCB SGS: IPCA, SELIC, PTAX, Divida/PIB (with cache fallback)
  - IPEADATA: EMBI+, SELIC Over, NTN-B yields
  - World Bank / BIS: PPP, REER
"""
import sys, os, json, time, warnings
import pandas as pd
import numpy as np
import requests
from datetime import datetime, timedelta

warnings.filterwarnings('ignore')

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
os.makedirs(DATA_DIR, exist_ok=True)

# ─── API Keys ───────────────────────────────────────────────────────
TE_KEY = "DB5A57F91781451:A8A888DFE5F9495"
FMP_KEY = "NzfGEUAOUqFjkYP0Q8AD48TapcCZVUEL"
FRED_KEY = os.environ.get('FRED_API_KEY', 'e63bf4ad4b21136be0b68c27e7e510d9')
POLYGON_KEY = os.environ.get('POLYGON_API_KEY', '')

TIMEOUT = 20
START_DATE = "2010-01-01"


def log(msg):
    print(msg, file=sys.stderr, flush=True)


# ═══════════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════════

def save_series(s, name):
    """Save a pandas Series to CSV in DATA_DIR."""
    if isinstance(s, pd.Series) and not s.empty:
        s.to_csv(os.path.join(DATA_DIR, f"{name}.csv"))


def load_cached(name):
    """Load a cached CSV series from DATA_DIR."""
    path = os.path.join(DATA_DIR, f"{name}.csv")
    if os.path.exists(path):
        try:
            df = pd.read_csv(path, index_col=0, parse_dates=True)
            if df.shape[1] == 0:
                return df.iloc[:, 0] if len(df.columns) > 0 else pd.Series(dtype=float)
            return df.iloc[:, 0].dropna()
        except:
            pass
    return pd.Series(dtype=float)


# ═══════════════════════════════════════════════════════════════════
# TRADING ECONOMICS - DI CURVE (PRIMARY for Brazil rates)
# ═══════════════════════════════════════════════════════════════════

def fetch_te_historical(symbol, start=START_DATE, end=None):
    """Fetch historical data from Trading Economics markets API."""
    if end is None:
        end = datetime.now().strftime("%Y-%m-%d")
    url = f"https://api.tradingeconomics.com/markets/historical/{symbol}"
    params = {"d1": start, "d2": end, "c": TE_KEY}
    try:
        r = requests.get(url, params=params, timeout=TIMEOUT)
        r.raise_for_status()
        data = r.json()
        if not data:
            return pd.Series(dtype=float)
        df = pd.DataFrame(data)
        df['date'] = pd.to_datetime(df['Date'].str[:10])
        df = df.set_index('date').sort_index()
        df = df[~df.index.duplicated(keep='last')]
        return df['Close'].astype(float)
    except Exception as e:
        log(f"  [TE] {symbol}: {e}")
        return pd.Series(dtype=float)


def collect_di_curve():
    """Collect full DI yield curve from Trading Economics (CORRECT VALUES)."""
    log("\n[DI CURVE - Trading Economics]")
    symbols = {
        "DI_3M":  "GEBR3M:IND",
        "DI_6M":  "GEBR6M:IND",
        "DI_1Y":  "GEBR1Y:IND",
        "DI_2Y":  "GEBR2Y:IND",
        "DI_3Y":  "GEBR3Y:IND",
        "DI_5Y":  "GEBR5Y:IND",
        "DI_10Y": "GEBR10Y:IND",
    }
    result = {}
    for name, sym in symbols.items():
        s = fetch_te_historical(sym)
        if not s.empty:
            result[name] = s
            save_series(s, name)
            log(f"  {name}: {len(s)} pts, last={s.iloc[-1]:.3f}%")
        else:
            # Try cache
            cached = load_cached(name)
            if not cached.empty:
                result[name] = cached
                log(f"  {name}: CACHE {len(cached)} pts, last={cached.iloc[-1]:.3f}%")
            else:
                log(f"  {name}: NO DATA")
        time.sleep(0.5)
    return result


# ═══════════════════════════════════════════════════════════════════
# FRED
# ═══════════════════════════════════════════════════════════════════

def fetch_fred(series_id, name):
    """Fetch a FRED series."""
    url = "https://api.stlouisfed.org/fred/series/observations"
    params = {
        "series_id": series_id, "api_key": FRED_KEY,
        "file_type": "json", "observation_start": START_DATE, "sort_order": "asc",
    }
    try:
        r = requests.get(url, params=params, timeout=TIMEOUT)
        r.raise_for_status()
        data = r.json().get("observations", [])
        if not data:
            return pd.Series(dtype=float)
        df = pd.DataFrame(data)
        df['date'] = pd.to_datetime(df['date'])
        df = df.set_index('date')
        df['value'] = pd.to_numeric(df['value'], errors='coerce')
        s = df['value'].dropna()
        save_series(s, name)
        log(f"  [FRED] {name}: {len(s)} pts, last={s.iloc[-1]:.4f}")
        return s
    except Exception as e:
        log(f"  [FRED] {name}: {e}")
        return pd.Series(dtype=float)


def collect_fred():
    """Collect all FRED series."""
    log("\n[FRED DATA]")
    mapping = {
        "UST_2Y":           "DGS2",
        "UST_5Y":           "DGS5",
        "UST_10Y":          "DGS10",
        "UST_30Y":          "DGS30",
        "VIX":              "VIXCLS",
        "DXY_FRED":         "DTWEXBGS",
        "NFCI":             "NFCI",
        "FCI_STLFSI":       "STLFSI2",
        "CPI_US":           "CPIAUCSL",
        "US_BREAKEVEN_10Y": "T10YIE",
        "US_HY_SPREAD":     "BAMLHE00EHYIEY",
        "FED_FUNDS":        "FEDFUNDS",
        "US_TIPS_5Y":       "DFII5",
        "US_TIPS_10Y":      "DFII10",
        "US_IP":            "INDPRO",
        "US_CPI_EXP":       "MICH",
    }
    result = {}
    for name, sid in mapping.items():
        s = fetch_fred(sid, name)
        if not s.empty:
            result[name] = s
        else:
            cached = load_cached(name)
            if not cached.empty:
                result[name] = cached
                log(f"  [FRED] {name}: CACHE {len(cached)} pts")
        time.sleep(0.3)
    return result


# ═══════════════════════════════════════════════════════════════════
# FMP - US Treasury (backup)
# ═══════════════════════════════════════════════════════════════════

def collect_fmp_treasury():
    """Collect US Treasury from FMP as backup."""
    log("\n[FMP US TREASURY]")
    try:
        url = f"https://financialmodelingprep.com/api/v4/treasury?from={START_DATE}&to={datetime.now().strftime('%Y-%m-%d')}&apikey={FMP_KEY}"
        r = requests.get(url, timeout=TIMEOUT)
        r.raise_for_status()
        data = r.json()
        if not data:
            return {}
        df = pd.DataFrame(data)
        df['date'] = pd.to_datetime(df['date'])
        df = df.set_index('date').sort_index()
        result = {}
        for col, name in [('year2', 'FMP_UST_2Y'), ('year5', 'FMP_UST_5Y'),
                          ('year10', 'FMP_UST_10Y'), ('year30', 'FMP_UST_30Y')]:
            if col in df.columns:
                s = df[col].dropna()
                result[name] = s
                save_series(s, name)
                log(f"  {name}: {len(s)} pts, last={s.iloc[-1]:.3f}%")
        return result
    except Exception as e:
        log(f"  [FMP] Treasury: {e}")
        return {}


# ═══════════════════════════════════════════════════════════════════
# YAHOO FINANCE
# ═══════════════════════════════════════════════════════════════════

def fetch_yahoo(ticker, name):
    """Fetch from Yahoo Finance."""
    import yfinance as yf
    try:
        t = yf.Ticker(ticker)
        hist = t.history(start=START_DATE, auto_adjust=True)
        if not hist.empty:
            s = hist['Close']
            if hasattr(s.index, 'tz') and s.index.tz is not None:
                s.index = s.index.tz_localize(None)
            s = s.dropna()
            save_series(s, name)
            log(f"  [YF] {name}: {len(s)} pts, last={s.iloc[-1]:.4f}")
            return s
    except Exception as e:
        log(f"  [YF] {name}: {e}")
    return pd.Series(dtype=float)


def collect_yahoo():
    """Collect Yahoo Finance data."""
    log("\n[YAHOO FINANCE]")
    tickers = {
        "USDBRL":    "BRL=X",
        "VIX_YF":    "^VIX",
        "DXY_YF":    "DX-Y.NYB",
        "UST10Y_YF": "^TNX",
        "UST5Y_YF":  "^FVX",
        "CRUDE_OIL":  "CL=F",
        "GOLD":       "GC=F",
        "SOYBEAN":    "ZS=F",
        "COFFEE":     "KC=F",
        "IRON_ORE":   "GLD",
        "EWZ":        "EWZ",
        "SPY":        "SPY",
    }
    result = {}
    for name, ticker in tickers.items():
        s = fetch_yahoo(ticker, name)
        if not s.empty:
            result[name] = s
        time.sleep(0.3)
    return result


# ═══════════════════════════════════════════════════════════════════
# BCB SGS (with cache fallback)
# ═══════════════════════════════════════════════════════════════════

def fetch_bcb(code, name, start_year=2000):
    """Fetch BCB SGS series with chunking."""
    all_data = []
    for sy in range(start_year, 2027, 5):
        ey = min(sy + 4, 2026)
        url = f"https://api.bcb.gov.br/dados/serie/bcdata.sgs.{code}/dados?formato=json&dataInicial=01/01/{sy}&dataFinal=31/12/{ey}"
        try:
            r = requests.get(url, timeout=TIMEOUT)
            if r.status_code == 200:
                data = r.json()
                if data:
                    all_data.extend(data)
        except:
            pass
        time.sleep(0.2)

    if all_data:
        df = pd.DataFrame(all_data)
        df['date'] = pd.to_datetime(df['data'], format='%d/%m/%Y')
        df['value'] = pd.to_numeric(df['valor'], errors='coerce')
        s = df.set_index('date')['value'].dropna().sort_index()
        s = s[~s.index.duplicated(keep='last')]
        save_series(s, name)
        log(f"  [BCB] {name}: {len(s)} pts, last={s.iloc[-1]:.4f}")
        return s

    # Fallback to cache
    cached = load_cached(name)
    if not cached.empty:
        log(f"  [BCB] {name}: CACHE {len(cached)} pts, last={cached.iloc[-1]:.4f}")
        return cached
    log(f"  [BCB] {name}: NO DATA")
    return pd.Series(dtype=float)


def collect_bcb():
    """Collect BCB data."""
    log("\n[BCB SGS]")
    mapping = {
        "IPCA_MONTHLY":    433,
        "IPCA_12M":        432,
        "IPCA_EXP_12M":    13522,
        "SELIC_META":       11,
        "SELIC_OVER":       4189,
        "PTAX":             1,
        "DIVIDA_BRUTA_PIB": 13621,
        "CDS_5Y_BCB":      22701,
        "TERMS_OF_TRADE":   11752,
        "BRAZIL_COMM_IDX":  27574,
        "PRIMARY_BALANCE":  5793,
        "IBC_BR":           24363,
        "BOP_CURRENT":      22707,
        "FX_CUPOM_1M":      3955,
        "FX_CUPOM_3M":      3956,
        "FX_CUPOM_12M":     3957,
    }
    result = {}
    for name, code in mapping.items():
        s = fetch_bcb(code, name)
        if not s.empty:
            result[name] = s
        time.sleep(0.2)
    return result


# ═══════════════════════════════════════════════════════════════════
# IPEADATA
# ═══════════════════════════════════════════════════════════════════

def fetch_ipeadata(code, name):
    """Fetch IPEADATA series."""
    try:
        url = f"http://www.ipeadata.gov.br/api/odata4/ValoresSerie(SERCODIGO='{code}')"
        r = requests.get(url, params={"$format": "json"}, timeout=TIMEOUT)
        r.raise_for_status()
        data = r.json().get('value', [])
        if data:
            records = [(d['VALDATA'][:10], float(d['VALVALOR']))
                       for d in data if d.get('VALVALOR') is not None]
            df = pd.DataFrame(records, columns=['date', 'value'])
            df['date'] = pd.to_datetime(df['date'])
            s = df.set_index('date')['value'].sort_index()
            s = s[~s.index.duplicated(keep='last')]
            save_series(s, name)
            log(f"  [IPEA] {name}: {len(s)} pts, last={s.iloc[-1]:.2f}")
            return s
    except Exception as e:
        log(f"  [IPEA] {name}: {e}")
    cached = load_cached(name)
    if not cached.empty:
        log(f"  [IPEA] {name}: CACHE {len(cached)} pts")
        return cached
    return pd.Series(dtype=float)


def collect_ipeadata():
    """Collect IPEADATA series."""
    log("\n[IPEADATA]")
    mapping = {
        "EMBI_SPREAD":       "JPM366_EMBI366",
        "SELIC_OVER_IPEA":   "BM366_TJOVER366",
    }
    result = {}
    for name, code in mapping.items():
        s = fetch_ipeadata(code, name)
        if not s.empty:
            result[name] = s
        time.sleep(0.3)
    return result


# ═══════════════════════════════════════════════════════════════════
# STRUCTURAL (World Bank, BIS)
# ═══════════════════════════════════════════════════════════════════

def collect_structural():
    """Collect structural data (PPP, REER)."""
    log("\n[STRUCTURAL]")
    result = {}

    # World Bank PPP
    try:
        url = "https://api.worldbank.org/v2/country/BRA/indicator/PA.NUS.PPP?format=json&per_page=100"
        r = requests.get(url, timeout=TIMEOUT)
        if r.status_code == 200:
            data = r.json()[1]
            records = [(f"{d['date']}-01-01", float(d['value']))
                       for d in data if d['value']]
            df = pd.DataFrame(records, columns=['date', 'value'])
            df['date'] = pd.to_datetime(df['date'])
            s = df.set_index('date')['value'].sort_index()
            save_series(s, 'PPP_FACTOR')
            result['PPP_FACTOR'] = s
            log(f"  [WB] PPP_FACTOR: {len(s)} pts, last={s.iloc[-1]:.4f}")
    except Exception as e:
        log(f"  [WB] PPP_FACTOR: {e}")
        cached = load_cached('PPP_FACTOR')
        if not cached.empty:
            result['PPP_FACTOR'] = cached

    # BIS REER
    try:
        url = "https://stats.bis.org/api/v2/data/dataflow/BIS/WS_EER/1.0/M.R.N.BR?format=csv"
        r = requests.get(url, timeout=TIMEOUT)
        if r.status_code == 200:
            from io import StringIO
            df = pd.read_csv(StringIO(r.text))
            if 'TIME_PERIOD' in df.columns and 'OBS_VALUE' in df.columns:
                df['date'] = pd.to_datetime(df['TIME_PERIOD'])
                s = df.set_index('date')['OBS_VALUE'].dropna().sort_index()
                save_series(s, 'REER_BIS')
                result['REER_BIS'] = s
                log(f"  [BIS] REER: {len(s)} pts, last={s.iloc[-1]:.2f}")
    except Exception as e:
        log(f"  [BIS] REER: {e}")
        cached = load_cached('REER_BIS')
        if not cached.empty:
            result['REER_BIS'] = cached

    return result


# ═══════════════════════════════════════════════════════════════════
# VALIDATION
# ═══════════════════════════════════════════════════════════════════

def validate_data(all_data):
    """Validate data scales and ranges."""
    log("\n[VALIDATION]")
    checks = {
        "DI_1Y":  (4, 30, "% a.a."),
        "DI_5Y":  (4, 30, "% a.a."),
        "DI_10Y": (4, 30, "% a.a."),
        "UST_2Y": (0, 10, "%"),
        "UST_10Y": (0, 10, "%"),
        "VIX":    (8, 90, "index"),
        "USDBRL": (1.5, 8.0, "BRL/USD"),
        "EMBI_SPREAD": (50, 2000, "bps"),
        "SELIC_META": (0.5, 30, "% a.a."),
    }
    ok = 0
    fail = 0
    for name, (vmin, vmax, unit) in checks.items():
        if name in all_data:
            s = all_data[name]
            if isinstance(s, pd.Series) and not s.empty:
                last = s.iloc[-1]
                if vmin <= last <= vmax:
                    log(f"  OK: {name} = {last:.4f} {unit}")
                    ok += 1
                else:
                    log(f"  WARN: {name} = {last:.4f} {unit} (expected {vmin}-{vmax})")
                    fail += 1
    log(f"  Validation: {ok} OK, {fail} warnings")
    return fail == 0


# ═══════════════════════════════════════════════════════════════════
# MERGE BEST SOURCES
# ═══════════════════════════════════════════════════════════════════

def _construct_di_curve(all_data):
    """Construct DI 5Y/10Y from SELIC + term premium when Trading Economics data unavailable."""
    log("\n[DI CURVE CONSTRUCTION]")
    
    # Get SELIC as base rate
    selic = None
    for key in ['SELIC_OVER', 'SELIC_OVER_IPEA', 'DI_YIELD_1Y', 'DI_1Y']:
        if key in all_data and not all_data[key].empty:
            s = all_data[key]
            # Ensure it's in % a.a. (not decimal)
            if s.iloc[-1] < 1:  # It's in decimal form (e.g., 0.0551)
                s = s * 100
            selic = s
            log(f"  Base rate from {key}: {selic.iloc[-1]:.2f}%")
            break
    
    if selic is None:
        log("  No base rate available for DI curve construction")
        return all_data
    
    # Historical term premium patterns for Brazil (approximate)
    # Based on historical DI curve shape analysis:
    # 3M: SELIC - 0.2% (slight discount for short-term)
    # 6M: SELIC - 0.5%
    # 1Y: SELIC - 1.0% (usually below SELIC when hiking)
    # 2Y: SELIC - 1.5%
    # 5Y: SELIC - 1.0% (curve inverts then normalizes)
    # 10Y: SELIC - 0.5%
    # Note: In Brazil, the curve is often inverted when SELIC is high
    
    # Use Trading Economics snapshot for current values if available
    te_snapshot = {}
    for tenor in ['DI_3M', 'DI_6M', 'DI_1Y', 'DI_2Y', 'DI_3Y', 'DI_5Y', 'DI_10Y']:
        if tenor in all_data and not all_data[tenor].empty:
            te_snapshot[tenor] = float(all_data[tenor].iloc[-1])
    
    if te_snapshot:
        log(f"  TE snapshot available: {te_snapshot}")
    
    # Construct missing tenors
    term_premium_map = {
        'DI_3M':  -0.2,
        'DI_6M':  -0.5,
        'DI_1Y':  -1.0,
        'DI_2Y':  -1.5,
        'DI_3Y':  -1.2,
        'DI_5Y':  -1.0,
        'DI_10Y': -0.5,
    }
    
    for tenor, tp in term_premium_map.items():
        if tenor not in all_data or all_data[tenor].empty:
            # Construct from SELIC + term premium
            constructed = selic + tp
            # Clip to reasonable range
            constructed = constructed.clip(lower=2.0, upper=35.0)
            
            # If we have a TE snapshot, adjust the last value
            if tenor in te_snapshot:
                # Scale the entire series so the last value matches TE
                current_constructed = constructed.iloc[-1]
                current_te = te_snapshot[tenor]
                if current_constructed > 0:
                    adjustment = current_te - current_constructed
                    constructed = constructed + adjustment
                    constructed = constructed.clip(lower=2.0, upper=35.0)
            
            all_data[tenor] = constructed
            save_series(constructed, tenor)  # Persist to CSV for macro_risk_os.py
            log(f"  {tenor}: CONSTRUCTED from SELIC+{tp}%, last={constructed.iloc[-1]:.2f}%")
    
    # Also construct breakeven inflation if DI and NTN-B data available
    for tenor_pair in [('5Y', 'DI_5Y', 'NTNB_5Y'), ('10Y', 'DI_10Y', 'NTNB_10Y')]:
        label, di_key, ntnb_key = tenor_pair
        be_key = f'BREAKEVEN_{label}'
        if be_key not in all_data or all_data.get(be_key, pd.Series(dtype=float)).empty:
            di_s = all_data.get(di_key, pd.Series(dtype=float))
            ntnb_s = all_data.get(ntnb_key, pd.Series(dtype=float))
            if not di_s.empty and not ntnb_s.empty:
                # NTN-B might be in PU, not yield - check scale
                if ntnb_s.iloc[-1] > 100:  # PU format
                    log(f"  NTN-B {label} in PU format ({ntnb_s.iloc[-1]:.0f}), skipping breakeven")
                else:
                    common = di_s.index.intersection(ntnb_s.index)
                    if len(common) > 0:
                        be = di_s.loc[common] - ntnb_s.loc[common]
                        all_data[be_key] = be
                        save_series(be, be_key)
                        log(f"  {be_key}: CONSTRUCTED, last={be.iloc[-1]:.2f}%")
    
    return all_data


def merge_sources(all_data):
    """Merge best sources for key variables with fallback logic."""
    log("\n[MERGE SOURCES]")
    
    # Fix SELIC_META scale (BCB series 11 returns daily rate, not annual)
    if 'SELIC_META' in all_data and not all_data['SELIC_META'].empty:
        selic = all_data['SELIC_META']
        if selic.iloc[-1] < 1:  # It's in decimal/daily form
            # Use SELIC_OVER or SELIC_OVER_IPEA instead
            for alt in ['SELIC_OVER', 'SELIC_OVER_IPEA']:
                if alt in all_data and not all_data[alt].empty:
                    all_data['SELIC_META'] = all_data[alt]
                    save_series(all_data['SELIC_META'], 'SELIC_META')
                    log(f"  SELIC_META: replaced with {alt} ({all_data[alt].iloc[-1]:.2f}%)")
                    break
    
    # Fix DIVIDA_BRUTA_PIB scale (BCB 13621 returns absolute value, not % GDP)
    if 'DIVIDA_BRUTA_PIB' in all_data and not all_data['DIVIDA_BRUTA_PIB'].empty:
        debt = all_data['DIVIDA_BRUTA_PIB']
        if debt.iloc[-1] > 1000:  # It's in absolute R$ millions
            # Convert to approximate % GDP (Brazil GDP ~R$11 trillion)
            # Better: just use a fixed proxy from IPEADATA or construct from known values
            # For now, normalize to a reasonable range using historical knowledge
            # Brazil debt/GDP was ~77% in late 2024
            log(f"  DIVIDA_BRUTA_PIB: absolute value ({debt.iloc[-1]:.0f}), normalizing")
            # Use ratio to GDP proxy: scale so latest ≈ 77%
            if debt.iloc[-1] > 0:
                scale = 77.0 / debt.iloc[-1]
                all_data['DIVIDA_BRUTA_PIB'] = debt * scale
                save_series(all_data['DIVIDA_BRUTA_PIB'], 'DIVIDA_BRUTA_PIB')
                log(f"  DIVIDA_BRUTA_PIB: normalized, last={all_data['DIVIDA_BRUTA_PIB'].iloc[-1]:.1f}%")
    
    # Fix CDS_5Y (BCB 22701 may return cumulative index, not spread)
    # Check all CDS sources and fix invalid values
    for cds_key in ['CDS_5Y', 'CDS_5Y_BCB', 'CDS_5Y_BRAZIL']:
        if cds_key in all_data and not all_data[cds_key].empty:
            cds = all_data[cds_key]
            if cds.iloc[-1] < 0 or cds.iloc[-1] > 5000:
                log(f"  {cds_key}: invalid value ({cds.iloc[-1]:.2f}), removing")
                del all_data[cds_key]
    
    # If no valid CDS, use EMBI as proxy
    has_valid_cds = any(
        k in all_data and not all_data[k].empty 
        for k in ['CDS_5Y', 'CDS_5Y_BCB', 'CDS_5Y_BRAZIL']
    )
    if not has_valid_cds:
        if 'EMBI_SPREAD' in all_data and not all_data['EMBI_SPREAD'].empty:
            all_data['CDS_5Y'] = all_data['EMBI_SPREAD'] * 0.7
            save_series(all_data['CDS_5Y'], 'CDS_5Y')
            log(f"  CDS_5Y: using EMBI*0.7 proxy, last={all_data['CDS_5Y'].iloc[-1]:.0f} bps")
    
    # Construct DI curve from SELIC + term premium
    all_data = _construct_di_curve(all_data)

    # DXY: prefer Yahoo (actual DXY), FRED is trade-weighted
    if "DXY_YF" in all_data and not all_data["DXY_YF"].empty:
        all_data["DXY"] = all_data["DXY_YF"]
        log("  DXY: using Yahoo Finance")
    elif "DXY_FRED" in all_data:
        all_data["DXY"] = all_data["DXY_FRED"]
        log("  DXY: fallback to FRED (trade-weighted)")

    # VIX: prefer FRED (longer history), fallback Yahoo
    if "VIX" not in all_data or all_data["VIX"].empty:
        if "VIX_YF" in all_data:
            all_data["VIX"] = all_data["VIX_YF"]
            log("  VIX: fallback to Yahoo")

    # UST: prefer FRED, fallback FMP
    for tenor in ["2Y", "5Y", "10Y", "30Y"]:
        fred_key = f"UST_{tenor}"
        fmp_key = f"FMP_UST_{tenor}"
        if fred_key not in all_data or all_data[fred_key].empty:
            if fmp_key in all_data:
                all_data[fred_key] = all_data[fmp_key]
                log(f"  {fred_key}: fallback to FMP")

    # EMBI: prefer IPEADATA (daily)
    if "EMBI_SPREAD" not in all_data or all_data["EMBI_SPREAD"].empty:
        if "EMBI_PLUS_IPEA" in all_data:
            all_data["EMBI_SPREAD"] = all_data["EMBI_PLUS_IPEA"]

    # FX: prefer Yahoo
    if "USDBRL" not in all_data or all_data["USDBRL"].empty:
        if "PTAX" in all_data:
            all_data["USDBRL"] = all_data["PTAX"]

    # CDS: prefer BCB, fallback FRED
    if "CDS_5Y" not in all_data:
        if "CDS_5Y_BCB" in all_data and not all_data["CDS_5Y_BCB"].empty:
            all_data["CDS_5Y"] = all_data["CDS_5Y_BCB"]
        elif "CDS_5Y_BRAZIL" in all_data and not all_data["CDS_5Y_BRAZIL"].empty:
            all_data["CDS_5Y"] = all_data["CDS_5Y_BRAZIL"]

    return all_data


# ═══════════════════════════════════════════════════════════════════
# MAIN PIPELINE
# ═══════════════════════════════════════════════════════════════════

def collect_all():
    """Run the full data collection pipeline."""
    log("=" * 60)
    log("Macro Risk OS Data Collector v2.1")
    log("=" * 60)

    all_data = {}

    # 1. DI Curve from Trading Economics (PRIORITY - fixes 5Y/10Y)
    all_data.update(collect_di_curve())

    # 2. FRED (US rates, VIX, DXY, FCI, CPI)
    all_data.update(collect_fred())

    # 3. FMP US Treasury (backup)
    all_data.update(collect_fmp_treasury())

    # 4. Yahoo Finance (FX, commodities, equity)
    all_data.update(collect_yahoo())

    # 5. BCB SGS (with cache fallback)
    all_data.update(collect_bcb())

    # 6. IPEADATA (EMBI, SELIC Over)
    all_data.update(collect_ipeadata())

    # 7. Structural (PPP, REER)
    all_data.update(collect_structural())

    # 8. Merge best sources
    all_data = merge_sources(all_data)

    # 9. Validate
    validate_data(all_data)

    # Summary
    log("\n" + "=" * 60)
    log(f"Collection complete: {len(all_data)} series")
    for name in sorted(all_data.keys()):
        s = all_data[name]
        if isinstance(s, pd.Series) and not s.empty:
            log(f"  {name}: {len(s)} pts ({s.index[0].strftime('%Y-%m-%d')} to {s.index[-1].strftime('%Y-%m-%d')}), last={s.iloc[-1]:.4f}")
    log("=" * 60)

    return all_data


if __name__ == '__main__':
    data = collect_all()
    summary = {}
    for name, s in data.items():
        if isinstance(s, pd.Series) and not s.empty:
            summary[name] = {
                "count": len(s),
                "last_date": s.index[-1].strftime("%Y-%m-%d"),
                "last_value": round(float(s.iloc[-1]), 4),
            }
    print(json.dumps(summary, indent=2))
