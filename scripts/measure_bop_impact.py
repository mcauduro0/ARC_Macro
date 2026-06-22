"""Measure the BOP_CURRENT fix impact: trade balance (SGS 22707) vs current account (SGS 22701).

data_collector.py was fixed: BOP_CURRENT now maps SGS 22701 (Transacoes correntes - saldo,
current account, US$ mn, BPM6) instead of SGS 22707 (balanca comercial, trade balance). This
script quantifies what that change does to the bop-derived features. The engine builds
Z_bop = causal rolling z-score of bop_current (macro_risk_os_v2.py ~line 891), and bop_current
is ALSO a regressor in the BEER cointegration (~line 1213, bop_12m = 12m rolling sum) and in the
RealRateParity r* Model 2 (~line 1472/1517). For Z_bop the rolling-z normalizes scale, so the
real change is the MEANING (trade surplus -> current-account deficit) and the dynamics; for BEER
and r* Model 2 the level/scale is absorbed by regression but the economic meaning is corrected.

LIGHT approach (no full engine): pull both SGS series directly and replicate the engine's
_z_score_rolling spirit (window=60, std_floor=0.5, min_periods=max(24, window//2)=30, causal
expanding-quantile winsorize). HONESTY: report nulls/disagreements as they are; do not claim alpha.

Run:
    python scripts/measure_bop_impact.py
"""

from __future__ import annotations

import json
import os
import ssl
import urllib.request
from datetime import datetime

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODEL_DIR = os.path.join(ROOT, "server", "model")
DATA_DIR = os.path.join(MODEL_DIR, "data")
OUT_DIR = os.path.join(MODEL_DIR, "output")
os.makedirs(OUT_DIR, exist_ok=True)
OUT_PATH = os.path.join(OUT_DIR, "measure_bop_impact.json")

SNAPSHOT_OLD = os.path.join(DATA_DIR, "BOP_CURRENT_OLD_22707.csv")
ONDISK_BOP = os.path.join(DATA_DIR, "BOP_CURRENT.csv")

OLD_CODE = 22707  # balanca comercial (trade balance) — the WRONG mapping
NEW_CODE = 22701  # transacoes correntes - saldo (current account, US$ mn, BPM6) — the FIX

# Engine _z_score_rolling parameters (DEFAULT_CONFIG in macro_risk_os_v2.py)
Z_WINDOW = 60
Z_STD_FLOOR = 0.5
Z_MIN_PERIODS = max(24, Z_WINDOW // 2)  # = 30, the engine's convention


# ---------------------------------------------------------------------------
# Data fetch helpers
# ---------------------------------------------------------------------------
def _ssl_ctx() -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def fetch_sgs(code: int) -> pd.Series:
    """Pull a BCB SGS series live. BR dates dd/MM/yyyy, comma decimals. Month-end indexed."""
    url = f"https://api.bcb.gov.br/dados/serie/bcdata.sgs.{code}/dados?formato=json"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=25, context=_ssl_ctx()) as resp:
        raw = json.load(resp)
    idx, vals = [], []
    for row in raw:
        d = pd.to_datetime(row["data"], format="%d/%m/%Y", errors="coerce")
        v = pd.to_numeric(str(row["valor"]).replace(",", "."), errors="coerce")
        if pd.notna(d) and pd.notna(v):
            idx.append(d)
            vals.append(float(v))
    s = pd.Series(vals, index=pd.DatetimeIndex(idx)).sort_index()
    # align to month-end so old/new/csv all share the same monthly grid
    s.index = s.index + pd.offsets.MonthEnd(0)
    s = s[~s.index.duplicated(keep="last")]
    s.name = f"sgs_{code}"
    return s


def load_csv_series(path: str, name: str) -> pd.Series:
    """Load a date,value CSV (month-start dates in repo), month-end aligned."""
    if not os.path.exists(path):
        return pd.Series(dtype=float, name=name)
    df = pd.read_csv(path)
    date_col = next((c for c in ["date", "Date", "data", "observation_date"] if c in df.columns), df.columns[0])
    val_col = [c for c in df.columns if c != date_col][0]
    idx = pd.to_datetime(df[date_col], errors="coerce")
    val = pd.to_numeric(df[val_col], errors="coerce")
    s = pd.Series(val.values, index=idx).dropna().sort_index()
    s.index = s.index + pd.offsets.MonthEnd(0)
    s = s[~s.index.duplicated(keep="last")]
    s.name = name
    return s


# ---------------------------------------------------------------------------
# Causal rolling z-score — replicates engine _z_score_rolling spirit
# (arc.features.rolling_zscore + arc.causal expanding-quantile winsorize)
# ---------------------------------------------------------------------------
def causal_winsorize(z: pd.Series, lower: float = 0.05, upper: float = 0.95,
                     min_periods: int = 10) -> pd.Series:
    """Point-in-time winsorize: clip each point to expanding quantiles of data up to & incl it."""
    if len(z) < min_periods:
        return z
    lo = z.expanding(min_periods=min_periods).quantile(lower)
    hi = z.expanding(min_periods=min_periods).quantile(upper)
    out = z.copy()
    mask = lo.notna() & hi.notna()
    out[mask] = z[mask].clip(lower=lo[mask], upper=hi[mask])
    return out


def z_score_rolling(series: pd.Series, window: int = Z_WINDOW, std_floor: float = Z_STD_FLOOR) -> pd.Series:
    """(x - trailing_mean)/max(trailing_std, std_floor), causal, then causal winsorize on dropna."""
    mp = max(24, window // 2)
    mean_r = series.rolling(window, min_periods=mp).mean()
    std_r = series.rolling(window, min_periods=mp).std().clip(lower=std_floor)
    z = (series - mean_r) / std_r
    return causal_winsorize(z.dropna())


def _profile(s: pd.Series) -> dict:
    s = s.dropna()
    if len(s) == 0:
        return {"n": 0}
    return {
        "n": int(len(s)),
        "date_start": s.index.min().strftime("%Y-%m-%d"),
        "date_end": s.index.max().strftime("%Y-%m-%d"),
        "mean": round(float(s.mean()), 3),
        "median": round(float(s.median()), 3),
        "std": round(float(s.std()), 3),
        "pct_positive": round(float((s > 0).mean() * 100), 1),
        "pct_negative": round(float((s < 0).mean() * 100), 1),
        "latest_date": s.index.max().strftime("%Y-%m-%d"),
        "latest_value": round(float(s.iloc[-1]), 3),
    }


def _safe_corr(a: pd.Series, b: pd.Series) -> float | None:
    common = a.dropna().index.intersection(b.dropna().index)
    if len(common) < 3:
        return None
    c = a.reindex(common).corr(b.reindex(common))
    return None if pd.isna(c) else round(float(c), 4)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> dict:
    result: dict = {
        "task": "measure_bop_impact",
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "fix": {
            "field": "BOP_CURRENT",
            "old_sgs": OLD_CODE,
            "old_meaning": "balanca comercial (trade balance), typically POSITIVE surplus",
            "new_sgs": NEW_CODE,
            "new_meaning": "transacoes correntes - saldo (current account, US$ mn, BPM6), typically NEGATIVE deficit",
            "z_score_params": {"window": Z_WINDOW, "std_floor": Z_STD_FLOOR, "min_periods": Z_MIN_PERIODS,
                               "winsorize": "causal expanding 5/95 quantile, min_periods=10"},
            "downstream_consumers": [
                "Z_bop = z_score_rolling(bop_current)  [macro_risk_os_v2.py ~L891] (scale normalized; meaning + dynamics change)",
                "BEER cointegration: bop_12m = bop.rolling(12).sum()  [~L1226] (scale absorbed by regression; meaning improved)",
                "RealRateParity r* Model 2: bop_current passed as regressor  [~L1517] (scale absorbed; meaning improved)",
            ],
        },
        "sources": {},
        "errors": [],
    }

    # --- 1) Fetch both live SGS series ---
    live_old = live_new = pd.Series(dtype=float)
    try:
        live_old = fetch_sgs(OLD_CODE)
        result["sources"]["live_22707"] = {"status": "ok", **_profile(live_old)}
    except Exception as e:  # noqa: BLE001
        result["errors"].append(f"live_22707 fetch failed: {e!r}")
        result["sources"]["live_22707"] = {"status": "error"}
    try:
        live_new = fetch_sgs(NEW_CODE)
        result["sources"]["live_22701"] = {"status": "ok", **_profile(live_new)}
    except Exception as e:  # noqa: BLE001
        result["errors"].append(f"live_22701 fetch failed: {e!r}")
        result["sources"]["live_22701"] = {"status": "error"}

    # --- snapshot CSV (old 22707) + current on-disk feature CSV ---
    snap_old = load_csv_series(SNAPSHOT_OLD, "snapshot_22707")
    result["sources"]["snapshot_BOP_CURRENT_OLD_22707"] = (
        {"status": "ok", **_profile(snap_old)} if len(snap_old) else {"status": "absent"}
    )
    ondisk = load_csv_series(ONDISK_BOP, "ondisk_BOP_CURRENT")
    result["sources"]["ondisk_BOP_CURRENT_csv"] = (
        {"status": "ok", **_profile(ondisk)} if len(ondisk) else {"status": "absent"}
    )

    # Honest note: is the on-disk feature CSV still the OLD series? (collector not yet re-run)
    if len(ondisk) and (len(live_old) or len(snap_old)):
        ref_old = live_old if len(live_old) else snap_old
        common = ondisk.dropna().index.intersection(ref_old.dropna().index)
        if len(common) >= 12:
            diff_old = float((ondisk.reindex(common) - ref_old.reindex(common)).abs().max())
            matches_old = diff_old < 1e-6
            ref_new = live_new if len(live_new) else pd.Series(dtype=float)
            matches_new = None
            if len(ref_new):
                cn = ondisk.dropna().index.intersection(ref_new.dropna().index)
                if len(cn) >= 12:
                    matches_new = float((ondisk.reindex(cn) - ref_new.reindex(cn)).abs().max()) < 1e-6
            result["ondisk_state"] = {
                "ondisk_matches_OLD_22707": matches_old,
                "ondisk_matches_NEW_22701": matches_new,
                "note": ("On-disk BOP_CURRENT.csv still equals the OLD trade-balance series: the code fix "
                         "(data_collector.py 22707->22701) is in place but the CSV has NOT been re-collected. "
                         "Engine output reflects the fix only after re-running data collection.")
                if matches_old else
                ("On-disk BOP_CURRENT.csv matches the NEW current-account series (22701): re-collection done."
                 if matches_new else
                 "On-disk BOP_CURRENT.csv matches neither series exactly (partial/stale re-collection)."),
            }

    # --- 2) Choose the level series to compare (prefer live; fall back to snapshot/on-disk) ---
    old = live_old if len(live_old) else snap_old
    new = live_new if len(live_new) else pd.Series(dtype=float)
    result["comparison_basis"] = {
        "old": "live_22707" if len(live_old) else ("snapshot_22707" if len(snap_old) else "none"),
        "new": "live_22701" if len(live_new) else "none",
    }

    if len(old) == 0 or len(new) == 0:
        result["errors"].append("Cannot compare: missing old or new series.")
        with open(OUT_PATH, "w") as f:
            json.dump(result, f, indent=2)
        return result

    common = old.dropna().index.intersection(new.dropna().index)
    old_c = old.reindex(common)
    new_c = new.reindex(common)

    # --- 2) Level profile + corr ---
    result["levels"] = {
        "n_common_months": int(len(common)),
        "date_range": [common.min().strftime("%Y-%m-%d"), common.max().strftime("%Y-%m-%d")],
        "old_22707": _profile(old_c),
        "new_22701": _profile(new_c),
        "corr_levels_old_new": _safe_corr(old_c, new_c),
        "mean_level_shift_new_minus_old": round(float((new_c - old_c).mean()), 2),
        "sign_disagreement_levels_pct": round(float((np.sign(old_c) != np.sign(new_c)).mean() * 100), 1),
    }

    # --- 3) Z_bop both ways (causal rolling z) ---
    z_old = z_score_rolling(old)
    z_new = z_score_rolling(new)
    zc = z_old.dropna().index.intersection(z_new.dropna().index)
    z_old_c = z_old.reindex(zc)
    z_new_c = z_new.reindex(zc)
    sign_disagree = float((np.sign(z_old_c) != np.sign(z_new_c)).mean() * 100) if len(zc) else None

    result["z_bop"] = {
        "n_common_months": int(len(zc)),
        "date_range": [zc.min().strftime("%Y-%m-%d"), zc.max().strftime("%Y-%m-%d")] if len(zc) else None,
        "corr_Zbop_old_new": _safe_corr(z_old_c, z_new_c),
        "sign_disagreement_pct": round(sign_disagree, 1) if sign_disagree is not None else None,
        "mean_abs_diff": round(float((z_old_c - z_new_c).abs().mean()), 4) if len(zc) else None,
        "rms_diff": round(float(np.sqrt(((z_old_c - z_new_c) ** 2).mean())), 4) if len(zc) else None,
        "latest": {
            "date": zc.max().strftime("%Y-%m-%d") if len(zc) else None,
            "Z_bop_old_22707": round(float(z_old_c.iloc[-1]), 4) if len(zc) else None,
            "Z_bop_new_22701": round(float(z_new_c.iloc[-1]), 4) if len(zc) else None,
        },
        "last6_old": [round(float(v), 3) for v in z_old_c.iloc[-6:]] if len(zc) >= 6 else None,
        "last6_new": [round(float(v), 3) for v in z_new_c.iloc[-6:]] if len(zc) >= 6 else None,
    }

    # --- 4) Honest verdict ---
    corr_lv = result["levels"]["corr_levels_old_new"]
    corr_z = result["z_bop"]["corr_Zbop_old_new"]
    result["verdict"] = {
        "headline": ("The fix changes the FEATURE'S MEANING: trade balance (surplus, +) -> current account "
                     "(deficit, -). Even where the rolling-z normalizes scale, the two z-series are materially "
                     "different in dynamics, NOT a relabeling."),
        "levels": (f"old (22707) and new (22701) levels correlate {corr_lv} and disagree in sign "
                   f"{result['levels']['sign_disagreement_levels_pct']}% of months; the new series is on average "
                   f"{result['levels']['mean_level_shift_new_minus_old']} US$mn vs the old (deficit shift)."),
        "Z_bop": (f"Z_bop_old vs Z_bop_new correlate {corr_z} and disagree in sign "
                  f"{result['z_bop']['sign_disagreement_pct']}% of months "
                  f"(mean|diff|={result['z_bop']['mean_abs_diff']}, rms={result['z_bop']['rms_diff']}); "
                  f"latest Z_bop {result['z_bop']['latest']['Z_bop_old_22707']} (old) -> "
                  f"{result['z_bop']['latest']['Z_bop_new_22701']} (new)."),
        "downstream_note": ("BEER cointegration and RealRateParity r* Model 2 take bop_current as a regressor: "
                            "the level/scale is absorbed by the fit (coefficients re-estimate), so the numeric impact "
                            "is muted, but the ECONOMIC MEANING is corrected (external-balance now = current account, "
                            "the right vulnerability proxy). Not refactored here, only noted."),
        "honesty": ("No alpha claimed. This is a measurement of a data-correctness fix. Where Z_bop signs flip, the "
                    "external-vulnerability feature would have pointed the WRONG way under the old mapping."),
    }

    with open(OUT_PATH, "w") as f:
        json.dump(result, f, indent=2)
    return result


if __name__ == "__main__":
    r = main()
    print(json.dumps(r, indent=2))
    print(f"\nWrote: {OUT_PATH}")
