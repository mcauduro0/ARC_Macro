"""Fix FRED data and EMBI spread collection"""
import pandas as pd
import numpy as np
import requests
import os
import io

DATA_DIR = "/home/ubuntu/brlusd_model/data"

# ============================================================
# Fix FRED - use observations API endpoint
# ============================================================
def fetch_fred_v2(series_id, start='1995-01-01'):
    """Fetch FRED data via observations API (no key needed for CSV)"""
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?bgcolor=%23e1e9f0&chart_type=line&drp=0&fo=open%20sans&graph_bgcolor=%23ffffff&height=450&mode=fred&recession_bars=on&txtcolor=%23444444&ts=12&tts=12&width=1168&nt=0&thu=0&trc=0&show_legend=yes&show_axis_titles=yes&show_tooltip=yes&id={series_id}&scale=left&cosd={start}&coed=2026-12-31&line_color=%234572a7&link_values=false&line_style=solid&mark_type=none&mw=3&lw=2&ost=-99999&oet=99999&mma=0&fml=a&fq=Daily&fam=avg&fgst=lin&fgsnd=2020-02-01&line_index=1&transformation=lin&vintage_date=2026-02-11&revision_date=2026-02-11&nd={start}"
    try:
        r = requests.get(url, timeout=30)
        df = pd.read_csv(io.StringIO(r.text))
        # First column is date, second is value
        date_col = df.columns[0]
        val_col = df.columns[1]
        df[date_col] = pd.to_datetime(df[date_col])
        df[val_col] = pd.to_numeric(df[val_col], errors='coerce')
        df = df.set_index(date_col)
        df.columns = [series_id]
        df = df.dropna()
        print(f"  FRED {series_id}: {len(df)} obs from {df.index.min().strftime('%Y-%m')} to {df.index.max().strftime('%Y-%m')}")
        return df
    except Exception as e:
        print(f"  FRED {series_id} FAILED: {e}")
        return pd.DataFrame()

print("=== Fixing FRED Data ===")
fred_series = {
    'CPIAUCSL': 'CPI_US',
    'DEXBZUS': 'BRLUSD_FRED',
    'DTWEXBGS': 'DXY_BROAD',
    'DGS10': 'UST10Y',
    'RBBRBIS': 'REER_BIS',
    'T10YIE': 'US_BREAKEVEN_10Y',
}

for fred_id, name in fred_series.items():
    df = fetch_fred_v2(fred_id)
    if not df.empty:
        df.columns = [name]
        path = os.path.join(DATA_DIR, f"{name}.csv")
        df.to_csv(path)
        print(f"  Saved {name}")

# ============================================================
# Fix EMBI Spread from BCB
# ============================================================
print("\n=== Fixing EMBI Spread ===")
url = "https://api.bcb.gov.br/dados/serie/bcdata.sgs.12461/dados?formato=json&dataInicial=01/01/2000"
try:
    r = requests.get(url, timeout=30)
    data = r.json()
    if isinstance(data, list) and len(data) > 0:
        df = pd.DataFrame(data)
        df['data'] = pd.to_datetime(df['data'], format='%d/%m/%Y')
        df['valor'] = pd.to_numeric(df['valor'], errors='coerce')
        df = df.dropna()
        df = df.set_index('data')
        df.columns = ['EMBI_SPREAD']
        df.to_csv(os.path.join(DATA_DIR, 'EMBI_SPREAD.csv'))
        print(f"  EMBI Spread: {len(df)} obs from {df.index.min().strftime('%Y-%m')} to {df.index.max().strftime('%Y-%m')}")
    else:
        print(f"  EMBI returned: {type(data)}, len={len(data) if isinstance(data, list) else 'N/A'}")
        print(f"  First items: {data[:3] if isinstance(data, list) else data}")
except Exception as e:
    print(f"  EMBI FAILED: {e}")

# Also try EMBI via different BCB code
print("\n=== Trying alternative risk indicators ===")
alt_codes = {
    3546: 'EMBI_PLUS_RISCO',  # EMBI+ Risco-Brasil
}
for code, name in alt_codes.items():
    url = f"https://api.bcb.gov.br/dados/serie/bcdata.sgs.{code}/dados?formato=json&dataInicial=01/01/2000"
    try:
        r = requests.get(url, timeout=30)
        data = r.json()
        if isinstance(data, list) and len(data) > 0:
            df = pd.DataFrame(data)
            df['data'] = pd.to_datetime(df['data'], format='%d/%m/%Y')
            df['valor'] = pd.to_numeric(df['valor'], errors='coerce')
            df = df.dropna()
            df = df.set_index('data')
            df.columns = [name]
            df.to_csv(os.path.join(DATA_DIR, f'{name}.csv'))
            print(f"  {name}: {len(df)} obs")
    except Exception as e:
        print(f"  {name} FAILED: {e}")

print("\n=== Final data inventory ===")
for f in sorted(os.listdir(DATA_DIR)):
    if f.endswith('.csv') and f != 'data_summary.csv':
        df = pd.read_csv(os.path.join(DATA_DIR, f), index_col=0, parse_dates=True)
        df = df.dropna()
        if len(df) > 0:
            print(f"  {f:30s} {len(df):6d} obs  {df.index.min().strftime('%Y-%m')} to {df.index.max().strftime('%Y-%m')}  last={df.iloc[-1,0]:.4f}")
