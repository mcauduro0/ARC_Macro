"""
Fetch PPP (Purchasing Power Parity) data for Brazil from multiple sources:
1. World Bank API (PA.NUS.PPP indicator)
2. FRED (PPPTTLBRA618NUPN - PPP over GDP for Brazil)
3. OECD Data Explorer
4. Extrapolation using CPI differentials for 2025-2026

Output: Updated PPP_FACTOR.csv with data through 2026
"""

import requests
import pandas as pd
import numpy as np
import json
import os
import sys
from datetime import datetime

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
FRED_API_KEY = "e63bf4ad4b21136be0b68c27e7e510d9"

def fetch_world_bank_ppp():
    """Fetch PA.NUS.PPP (PPP conversion factor, LCU per international $) for Brazil"""
    print("[WorldBank] Fetching PA.NUS.PPP for Brazil...")
    url = "https://api.worldbank.org/v2/country/BRA/indicator/PA.NUS.PPP"
    params = {
        "format": "json",
        "per_page": 100,
        "date": "1990:2026"
    }
    try:
        resp = requests.get(url, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        if len(data) < 2 or not data[1]:
            print("[WorldBank] No data returned")
            return pd.Series(dtype=float)
        
        records = {}
        for item in data[1]:
            year = int(item["date"])
            val = item["value"]
            if val is not None:
                records[year] = float(val)
        
        s = pd.Series(records).sort_index()
        print(f"[WorldBank] Got {len(s)} points: {s.index.min()}-{s.index.max()}")
        print(f"[WorldBank] Last 5 values:\n{s.tail()}")
        return s
    except Exception as e:
        print(f"[WorldBank] Error: {e}")
        return pd.Series(dtype=float)


def fetch_fred_ppp():
    """Fetch PPPTTLBRA618NUPN (PPP over GDP for Brazil) from FRED"""
    print("[FRED] Fetching PPPTTLBRA618NUPN...")
    url = "https://api.stlouisfed.org/fred/series/observations"
    params = {
        "series_id": "PPPTTLBRA618NUPN",
        "api_key": FRED_API_KEY,
        "file_type": "json",
        "observation_start": "1990-01-01",
        "observation_end": "2026-12-31"
    }
    try:
        resp = requests.get(url, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        
        records = {}
        for obs in data.get("observations", []):
            if obs["value"] != ".":
                year = int(obs["date"][:4])
                records[year] = float(obs["value"])
        
        s = pd.Series(records).sort_index()
        print(f"[FRED] Got {len(s)} points: {s.index.min()}-{s.index.max()}")
        print(f"[FRED] Last 5 values:\n{s.tail()}")
        return s
    except Exception as e:
        print(f"[FRED] Error: {e}")
        return pd.Series(dtype=float)


def fetch_fred_ppp_alt():
    """Fetch PPPGDPBRA624NUPN (PPP GDP for Brazil) from FRED as alternative"""
    print("[FRED-alt] Fetching PPPGDPBRA624NUPN...")
    url = "https://api.stlouisfed.org/fred/series/observations"
    params = {
        "series_id": "PPPGDPBRA624NUPN",
        "api_key": FRED_API_KEY,
        "file_type": "json",
        "observation_start": "1990-01-01",
        "observation_end": "2026-12-31"
    }
    try:
        resp = requests.get(url, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        
        records = {}
        for obs in data.get("observations", []):
            if obs["value"] != ".":
                year = int(obs["date"][:4])
                records[year] = float(obs["value"])
        
        s = pd.Series(records).sort_index()
        print(f"[FRED-alt] Got {len(s)} points: {s.index.min()}-{s.index.max()}")
        print(f"[FRED-alt] Last 5 values:\n{s.tail()}")
        return s
    except Exception as e:
        print(f"[FRED-alt] Error: {e}")
        return pd.Series(dtype=float)


def fetch_oecd_ppp():
    """Fetch PPP data from OECD for Brazil"""
    print("[OECD] Fetching PPP for Brazil...")
    # OECD SDMX API for PPP
    url = "https://sdmx.oecd.org/public/rest/data/OECD.SDD.NAD,DSD_NAMAIN10@DF_TABLE4,1.0/A.BRA.PPP_B1GQ..V"
    headers = {"Accept": "application/json"}
    try:
        resp = requests.get(url, headers=headers, timeout=30)
        if resp.status_code != 200:
            print(f"[OECD] HTTP {resp.status_code}, trying alternative URL...")
            # Try alternative OECD PPP endpoint
            url2 = "https://stats.oecd.org/SDMX-JSON/data/PPP_2017/BRA.XRAT+PPP/all"
            resp = requests.get(url2, headers=headers, timeout=30)
            if resp.status_code != 200:
                print(f"[OECD] Alternative also failed: HTTP {resp.status_code}")
                return pd.Series(dtype=float)
        
        data = resp.json()
        # Parse SDMX-JSON format
        records = {}
        if "dataSets" in data:
            for ds in data["dataSets"]:
                for series_key, series_data in ds.get("series", {}).items():
                    for obs_key, obs_val in series_data.get("observations", {}).items():
                        if obs_val and len(obs_val) > 0 and obs_val[0] is not None:
                            # Get time period from dimensions
                            time_idx = int(obs_key)
                            time_periods = data.get("structure", {}).get("dimensions", {}).get("observation", [])
                            if time_periods:
                                for dim in time_periods:
                                    if dim.get("id") == "TIME_PERIOD":
                                        year = int(dim["values"][time_idx]["id"][:4])
                                        records[year] = float(obs_val[0])
        
        s = pd.Series(records).sort_index()
        print(f"[OECD] Got {len(s)} points")
        if len(s) > 0:
            print(f"[OECD] Range: {s.index.min()}-{s.index.max()}")
            print(f"[OECD] Last 5 values:\n{s.tail()}")
        return s
    except Exception as e:
        print(f"[OECD] Error: {e}")
        return pd.Series(dtype=float)


def fetch_cpi_data():
    """Fetch CPI data for Brazil (IPCA) and US (CPI-U) to extrapolate PPP"""
    print("[CPI] Fetching CPI data for PPP extrapolation...")
    
    # Brazil IPCA from BCB (series 433 - IPCA monthly)
    brazil_cpi = {}
    try:
        url = "https://api.bcb.gov.br/dados/serie/bcdata.sgs.433/dados"
        params = {"formato": "json", "dataInicial": "01/01/2020", "dataFinal": "31/12/2026"}
        resp = requests.get(url, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        
        # Accumulate monthly IPCA to get annual CPI index
        monthly_rates = {}
        for item in data:
            dt = pd.Timestamp(item["data"].replace("/", "-")[:10])
            # BCB returns dd/mm/yyyy format
            parts = item["data"].split("/")
            dt = pd.Timestamp(f"{parts[2]}-{parts[1]}-{parts[0]}")
            year = dt.year
            rate = float(item["valor"]) / 100.0
            if year not in monthly_rates:
                monthly_rates[year] = []
            monthly_rates[year].append(rate)
        
        # Calculate annual inflation for each year
        for year, rates in monthly_rates.items():
            annual = 1.0
            for r in rates:
                annual *= (1 + r)
            brazil_cpi[year] = annual - 1.0  # Annual inflation rate
        
        print(f"[CPI-BR] Annual inflation rates:")
        for y in sorted(brazil_cpi.keys()):
            print(f"  {y}: {brazil_cpi[y]*100:.2f}%")
    except Exception as e:
        print(f"[CPI-BR] Error: {e}")
    
    # US CPI from FRED (CPIAUCSL)
    us_cpi = {}
    try:
        url = "https://api.stlouisfed.org/fred/series/observations"
        params = {
            "series_id": "FPCPITOTLZGUSA",  # CPI annual % change for US
            "api_key": FRED_API_KEY,
            "file_type": "json",
            "observation_start": "2020-01-01",
            "observation_end": "2026-12-31"
        }
        resp = requests.get(url, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        
        for obs in data.get("observations", []):
            if obs["value"] != ".":
                year = int(obs["date"][:4])
                us_cpi[year] = float(obs["value"]) / 100.0  # Convert % to decimal
        
        print(f"[CPI-US] Annual inflation rates:")
        for y in sorted(us_cpi.keys()):
            print(f"  {y}: {us_cpi[y]*100:.2f}%")
    except Exception as e:
        print(f"[CPI-US] Error: {e}")
    
    return brazil_cpi, us_cpi


def extrapolate_ppp(existing_ppp, brazil_cpi, us_cpi, target_years):
    """
    Extrapolate PPP using relative CPI differentials.
    PPP(t+1) = PPP(t) * (1 + inflation_BR(t)) / (1 + inflation_US(t))
    This is the standard relative PPP adjustment.
    """
    print("\n[Extrapolation] Extending PPP using CPI differentials...")
    
    last_year = existing_ppp.index.max()
    last_ppp = existing_ppp.iloc[-1]
    print(f"  Base: PPP({last_year}) = {last_ppp:.6f}")
    
    extrapolated = {}
    current_ppp = last_ppp
    
    for year in target_years:
        if year <= last_year:
            continue
        
        br_inf = brazil_cpi.get(year)
        us_inf = us_cpi.get(year)
        
        if br_inf is not None and us_inf is not None:
            # Standard relative PPP formula
            current_ppp = current_ppp * (1 + br_inf) / (1 + us_inf)
            extrapolated[year] = current_ppp
            print(f"  PPP({year}) = {current_ppp:.6f} [BR CPI: {br_inf*100:.2f}%, US CPI: {us_inf*100:.2f}%]")
        elif br_inf is not None:
            # Use Brazil CPI only with estimated US CPI
            us_est = 0.025  # Estimate 2.5% US inflation
            current_ppp = current_ppp * (1 + br_inf) / (1 + us_est)
            extrapolated[year] = current_ppp
            print(f"  PPP({year}) = {current_ppp:.6f} [BR CPI: {br_inf*100:.2f}%, US CPI est: {us_est*100:.2f}%]")
        else:
            # Use historical average differential
            avg_growth = existing_ppp.pct_change().dropna().tail(5).mean()
            current_ppp = current_ppp * (1 + avg_growth)
            extrapolated[year] = current_ppp
            print(f"  PPP({year}) = {current_ppp:.6f} [avg growth: {avg_growth*100:.2f}%]")
    
    return pd.Series(extrapolated)


def main():
    print("=" * 60)
    print("PPP_FACTOR Update - Multi-Source Data Collection")
    print("=" * 60)
    
    # 1. Load existing data
    ppp_path = os.path.join(DATA_DIR, "PPP_FACTOR.csv")
    existing = pd.read_csv(ppp_path, parse_dates=["date"])
    existing["year"] = existing["date"].dt.year
    existing_series = existing.set_index("year")["value"]
    print(f"\nExisting PPP_FACTOR: {len(existing)} points, {existing_series.index.min()}-{existing_series.index.max()}")
    print(f"Last value: PPP({existing_series.index.max()}) = {existing_series.iloc[-1]:.6f}")
    
    # 2. Fetch from multiple sources
    wb_ppp = fetch_world_bank_ppp()
    fred_ppp = fetch_fred_ppp()
    fred_alt_ppp = fetch_fred_ppp_alt()
    oecd_ppp = fetch_oecd_ppp()
    
    # 3. Find the most recent data from any source
    all_sources = {
        "WorldBank": wb_ppp,
        "FRED": fred_ppp,
        "FRED-alt": fred_alt_ppp,
        "OECD": oecd_ppp,
        "Existing": existing_series
    }
    
    print("\n" + "=" * 60)
    print("Source Comparison (last available year)")
    print("=" * 60)
    for name, s in all_sources.items():
        if len(s) > 0:
            print(f"  {name}: {s.index.max()} -> {s.iloc[-1]:.6f}")
        else:
            print(f"  {name}: No data")
    
    # 4. Determine the best base series
    # Use existing as base (it's from World Bank PA.NUS.PPP)
    # Check if any source has newer data
    best_series = existing_series.copy()
    best_max_year = best_series.index.max()
    
    for name, s in all_sources.items():
        if name == "Existing":
            continue
        if len(s) > 0 and s.index.max() > best_max_year:
            # Check if values are consistent (within 20% of existing for overlap years)
            overlap = set(s.index) & set(existing_series.index)
            if overlap:
                overlap_years = sorted(overlap)[-3:]  # Last 3 overlap years
                ratios = [s[y] / existing_series[y] for y in overlap_years if y in existing_series.index and y in s.index]
                avg_ratio = np.mean(ratios) if ratios else 1.0
                print(f"\n  {name} vs Existing ratio (last 3 overlap): {avg_ratio:.4f}")
                
                if 0.8 < avg_ratio < 1.2:
                    # Consistent - use newer data points
                    for year in s.index:
                        if year > best_max_year:
                            best_series[year] = s[year]
                            print(f"  Added {name} data for {year}: {s[year]:.6f}")
                            best_max_year = year
                else:
                    # Scale and use
                    for year in s.index:
                        if year > best_max_year:
                            scaled_val = s[year] / avg_ratio
                            best_series[year] = scaled_val
                            print(f"  Added scaled {name} data for {year}: {scaled_val:.6f} (raw: {s[year]:.6f})")
                            best_max_year = year
    
    # 5. Extrapolate missing years using CPI differentials
    brazil_cpi, us_cpi = fetch_cpi_data()
    
    target_years = list(range(2024, 2027))
    missing_years = [y for y in target_years if y not in best_series.index]
    
    if missing_years:
        print(f"\nMissing years to extrapolate: {missing_years}")
        extrapolated = extrapolate_ppp(best_series, brazil_cpi, us_cpi, missing_years)
        for year, val in extrapolated.items():
            best_series[year] = val
    else:
        print(f"\nAll target years already covered!")
    
    # 6. Save updated PPP_FACTOR.csv
    best_series = best_series.sort_index()
    
    print("\n" + "=" * 60)
    print("Final PPP_FACTOR Series (last 10 years)")
    print("=" * 60)
    for year in sorted(best_series.index)[-10:]:
        source = "existing" if year <= existing_series.index.max() else "new"
        print(f"  {year}: {best_series[year]:.6f} [{source}]")
    
    # Write to CSV
    output_df = pd.DataFrame({
        "date": [f"{y}-01-01" for y in best_series.index],
        "value": best_series.values
    })
    
    # Backup existing
    backup_path = ppp_path + ".bak"
    if os.path.exists(ppp_path):
        import shutil
        shutil.copy2(ppp_path, backup_path)
        print(f"\nBackup saved to {backup_path}")
    
    output_df.to_csv(ppp_path, index=False)
    print(f"Updated PPP_FACTOR.csv: {len(output_df)} points, {best_series.index.min()}-{best_series.index.max()}")
    
    return best_series


if __name__ == "__main__":
    main()
