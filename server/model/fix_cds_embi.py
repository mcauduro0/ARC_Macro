"""Fix CDS_5Y and EMBI_SPREAD data.
BCB 22701 is NOT CDS - it's primary balance. Need to use IPEADATA or FRED.
"""
import sys, os, requests, time
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.dirname(os.path.abspath(__file__)))

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")

def save_series(s, name):
    if isinstance(s, pd.Series) and not s.empty:
        s.to_csv(os.path.join(DATA_DIR, f"{name}.csv"))

# 1. Try IPEADATA for EMBI+ (daily)
print("Fetching EMBI from IPEADATA...")
url = "http://www.ipeadata.gov.br/api/odata4/ValoresSerie(SERCODIGO='JPM366_EMBI366')"
try:
    r = requests.get(url, params={"$format": "json"}, timeout=30)
    r.raise_for_status()
    data = r.json().get('value', [])
    if data:
        records = [(d['VALDATA'][:10], float(d['VALVALOR']))
                   for d in data if d.get('VALVALOR') is not None]
        df = pd.DataFrame(records, columns=['date', 'value'])
        df['date'] = pd.to_datetime(df['date'])
        s = df.set_index('date')['value'].sort_index()
        s = s[~s.index.duplicated(keep='last')]
        # Filter valid values (EMBI should be 50-2000 bps)
        s = s[(s > 50) & (s < 2000)]
        save_series(s, 'EMBI_SPREAD')
        print(f"  EMBI_SPREAD: {len(s)} pts, last={s.iloc[-1]:.2f} ({s.index[-1].strftime('%Y-%m-%d')})")
    else:
        print("  EMBI: no data from IPEADATA")
except Exception as e:
    print(f"  EMBI error: {e}")

# 2. Try FRED for EMBI (BAMLEMCBPIOAS)
print("\nFetching EMBI from FRED...")
FRED_KEY = os.environ.get('FRED_API_KEY', 'e63bf4ad4b21136be0b68c27e7e510d9')
try:
    url = f"https://api.stlouisfed.org/fred/series/observations?series_id=BAMLEMCBPIOAS&api_key={FRED_KEY}&file_type=json&observation_start=2000-01-01"
    r = requests.get(url, timeout=20)
    if r.status_code == 200:
        obs = r.json().get('observations', [])
        if obs:
            records = [(o['date'], float(o['value'])) for o in obs if o['value'] != '.']
            df = pd.DataFrame(records, columns=['date', 'value'])
            df['date'] = pd.to_datetime(df['date'])
            s = df.set_index('date')['value'].sort_index()
            # This is ICE BofA EM Corporate spread in % - convert to bps
            s_bps = s * 100
            print(f"  FRED BAMLEMCBPIOAS: {len(s)} pts, last={s.iloc[-1]:.2f}% = {s_bps.iloc[-1]:.0f}bps ({s.index[-1].strftime('%Y-%m-%d')})")
except Exception as e:
    print(f"  FRED EMBI error: {e}")

# 3. Try Yahoo Finance for Brazil CDS proxy (no direct CDS ticker)
# Use US HY spread as a proxy check
print("\nChecking US HY spread from FRED (BAMLH0A0HYM2)...")
try:
    url = f"https://api.stlouisfed.org/fred/series/observations?series_id=BAMLH0A0HYM2&api_key={FRED_KEY}&file_type=json&observation_start=2020-01-01"
    r = requests.get(url, timeout=20)
    if r.status_code == 200:
        obs = r.json().get('observations', [])
        if obs:
            records = [(o['date'], float(o['value'])) for o in obs if o['value'] != '.']
            df = pd.DataFrame(records, columns=['date', 'value'])
            df['date'] = pd.to_datetime(df['date'])
            s = df.set_index('date')['value'].sort_index()
            print(f"  US HY spread: {len(s)} pts, last={s.iloc[-1]:.2f}% ({s.index[-1].strftime('%Y-%m-%d')})")
except Exception as e:
    print(f"  US HY error: {e}")

# 4. For CDS_5Y, use IPEADATA CDS series
print("\nFetching CDS from IPEADATA...")
# Try different IPEADATA codes for CDS
for code_name, code in [("CDS_5Y_BRAZIL", "JPM366_CDSEMBI366")]:
    try:
        url = f"http://www.ipeadata.gov.br/api/odata4/ValoresSerie(SERCODIGO='{code}')"
        r = requests.get(url, params={"$format": "json"}, timeout=30)
        data = r.json().get('value', [])
        if data:
            records = [(d['VALDATA'][:10], float(d['VALVALOR']))
                       for d in data if d.get('VALVALOR') is not None]
            df = pd.DataFrame(records, columns=['date', 'value'])
            df['date'] = pd.to_datetime(df['date'])
            s = df.set_index('date')['value'].sort_index()
            s = s[~s.index.duplicated(keep='last')]
            s = s[(s > 20) & (s < 3000)]
            if not s.empty:
                save_series(s, 'CDS_5Y')
                print(f"  {code_name}: {len(s)} pts, last={s.iloc[-1]:.2f} ({s.index[-1].strftime('%Y-%m-%d')})")
            else:
                print(f"  {code_name}: empty after filtering")
        else:
            print(f"  {code_name}: no data")
    except Exception as e:
        print(f"  {code_name} error: {e}")

# 5. If CDS still stale, construct from EMBI
embi_path = os.path.join(DATA_DIR, 'EMBI_SPREAD.csv')
cds_path = os.path.join(DATA_DIR, 'CDS_5Y.csv')

embi = pd.read_csv(embi_path, index_col=0, parse_dates=True).iloc[:, 0]
cds = pd.read_csv(cds_path, index_col=0, parse_dates=True).iloc[:, 0]

print(f"\nFinal EMBI_SPREAD: {len(embi)} pts, last date={embi.index[-1].strftime('%Y-%m-%d')}, value={embi.iloc[-1]:.2f}")
print(f"Final CDS_5Y: {len(cds)} pts, last date={cds.index[-1].strftime('%Y-%m-%d')}, value={cds.iloc[-1]:.2f}")

# If CDS ends before EMBI, extend CDS using EMBI * ratio
if cds.index[-1] < embi.index[-1]:
    # Find overlapping period to compute ratio
    overlap = cds.index.intersection(embi.index)
    if len(overlap) > 100:
        ratio = (cds.reindex(overlap) / embi.reindex(overlap)).median()
        print(f"\nCDS/EMBI ratio: {ratio:.4f}")
        # Extend CDS with EMBI * ratio for dates after CDS ends
        missing_dates = embi.index[embi.index > cds.index[-1]]
        extension = embi.reindex(missing_dates) * ratio
        cds_extended = pd.concat([cds, extension]).sort_index()
        cds_extended = cds_extended[~cds_extended.index.duplicated(keep='last')]
        save_series(cds_extended, 'CDS_5Y')
        print(f"CDS_5Y extended: {len(cds_extended)} pts, last={cds_extended.iloc[-1]:.2f} ({cds_extended.index[-1].strftime('%Y-%m-%d')})")
