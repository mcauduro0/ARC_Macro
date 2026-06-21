"""Re-examination harness for fiscal_hard's WEAK RECENT THIRD — baseline today, re-runnable as months accrue.

fiscal_hard (signal pb_mom6 = primary_balance.diff(6) on instrument 'hard', carry = embi_spread/10000/12)
was promoted as a candidate but with a DOCUMENTED CAVEAT: in verify_hard_pb_v2 §D the RAW-IC thirds were
~[+0.16, +0.30, +0.08] — the recent third weak. The owner wants to re-examine this "as recent months
accrue". This script quantifies the recency trajectory NOW (baseline) on a CARRY-NEUTRAL basis and is
DESIGNED to be re-run unchanged as the sample grows, with a PRE-COMMITTED flag rule (computed, not hardcoded).
The binding recency measure is the rolling-36m / last-36m carry-neutral IC (coarse thirds can mask it).

It deliberately mirrors scripts/verify_hard_pb_v2.py (engine preamble + the _partial_ic helper, kept verbatim)
and does NOT modify v2. The carry-neutral IC = corr of residuals of (signal, fwd) on [carry].

Sections:
  A. Sub-period (halves + thirds) CARRY-NEUTRAL IC baseline (the doc'd [.16,.30,.08] were RAW IC, so these differ).
  B. ROLLING carry-neutral IC trajectory: windows W in {36, 48} mo, slide _partial_ic(sig,fwd,[carry]);
     print the LAST 6-8 rolling values + (min,max,last) and the count of windows < 0.
  C. LAST-K carry-neutral IC for K in {24, 36, 48, 60} ("as-of-today" recent strength at several horizons), each with n.
  D. TREND: OLS slope (numpy lstsq) of the rolling-36m cn-IC series vs time — DECLINING / flat / recovering.
  E. PRE-COMMITTED RECENCY FLAG (computed): recency_ok = (last-36m cn-IC >= 0.05) AND (last-36m cn-IC sign positive)
     AND (rolling-36 trend not strongly negative). Each sub-check printed Y/N.

HONEST VERDICT computed from the numbers; explicit that this is the BASELINE today — the SAME script re-run as
forward months accrue will let the recent windows include genuinely new out-of-time data.

Writes a JSON report to OUT/reexamine_fiscal_hard.json.

Run: python scripts/reexamine_fiscal_hard.py
"""

from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODEL_DIR = os.path.join(ROOT, "server", "model")
for _k, _v in {
    "ARC_CAUSAL_WINSORIZE": "1", "ARC_FORWARD_TARGET": "1", "ARC_HMM_FILTERED": "1",
    "ARC_BOUNDED_FFILL": "1", "ARC_CAUSAL_RSTAR_REGIME": "1", "ARC_REGIME_PER_SERIES": "1",
    "ARC_FEAT_PER_SERIES": "1", "ARC_REGIME_POINT_IN_TIME": "1", "ARC_PUBLICATION_LAG": "1",
    "ARC_CAUSAL_INTERP": "1", "ARC_CARRY_HARD_SPREAD": "1",
}.items():
    os.environ.setdefault(_k, _v)
sys.path.insert(0, MODEL_DIR)
sys.path.insert(0, ROOT)

SURVIVOR_L = 6           # diff window of the promoted signal (pb_mom6)
ROLL_WINDOWS = [36, 48]  # rolling carry-neutral-IC window lengths (months)
LASTK = [24, 36, 48, 60] # "as-of-today" recent-strength horizons (months)
TREND_W = 36             # window whose rolling cn-IC series the trend (D) + flag (E) use
N_MIN = 18               # min overlapping obs for a cn-IC point estimate (below this -> NaN)
# PRE-COMMITTED recency-flag thresholds (fixed once, here — never hardcoded per-result):
RECENCY_IC_MIN = 0.05          # last-TREND_W cn-IC must clear this floor
TREND_NEG_TOL = -0.02          # rolling-TREND_W trend "strongly negative" if slope-per-year < this


def _partial_ic(signal, fwd, controls):
    """Partial IC of `signal` vs `fwd`, both residualized on `controls` (+ intercept).

    Returns (ic, n). Returns (nan, n) when n < 40 or a residual is degenerate. (kept verbatim from v2)
    """
    import numpy as np
    import pandas as pd
    cols = {"s": signal, "r": fwd}
    for i, c in enumerate(controls):
        cols[f"c{i}"] = c
    df = pd.concat(cols, axis=1).dropna()
    if len(df) < 40:
        return float("nan"), len(df)
    X = np.column_stack([np.ones(len(df))] + [df[f"c{i}"].values for i in range(len(controls))])
    def resid(y):
        b, *_ = np.linalg.lstsq(X, y, rcond=None)
        return y - X @ b
    rs, rr = resid(df["s"].values), resid(df["r"].values)
    if rs.std() < 1e-12 or rr.std() < 1e-12:
        return float("nan"), len(df)
    return float(np.corrcoef(rs, rr)[0, 1]), len(df)


def _cn_ic_on(d):
    """Carry-neutral IC on an already-aligned 3-col frame [signal, fwd, carry] (no n<40 floor).

    Mirrors _partial_ic's residual math but lets short sub-windows estimate (guarded by N_MIN at call sites),
    so sub-period / rolling / last-K windows can be measured even when shorter than the 40-obs partial-IC floor.
    """
    import numpy as np
    if len(d) < N_MIN:
        return float("nan")
    y_s = d.iloc[:, 0].values
    y_r = d.iloc[:, 1].values
    X = np.column_stack([np.ones(len(d)), d.iloc[:, 2].values])
    def resid(y):
        b, *_ = np.linalg.lstsq(X, y, rcond=None)
        return y - X @ b
    rs, rr = resid(y_s), resid(y_r)
    if rs.std() < 1e-12 or rr.std() < 1e-12:
        return float("nan")
    return float(np.corrcoef(rs, rr)[0, 1])


def main() -> None:
    import json

    import numpy as np
    import pandas as pd

    import macro_risk_os_v2 as eng
    from arc.eval import forward_returns

    print("[reexamine-fiscal-hard] initializing engine...", file=sys.stderr)
    e = eng.ProductionEngine(eng.DEFAULT_CONFIG)
    e.initialize()
    ret_df = e.data_layer.ret_df
    monthly = e.data_layer.monthly
    feat_df = e.feature_engine.feature_df
    idx = feat_df.index
    horizon = eng.DEFAULT_CONFIG.get("prediction_horizon_months", 1)

    # signal / target / carry — exactly the promoted fiscal_hard recipe
    sig = monthly.get("primary_balance").reindex(idx).diff(SURVIVOR_L)
    fwd = forward_returns(ret_df["hard"], horizon)
    carry = (monthly.get("embi_spread").reindex(idx)) / 10000.0 / 12.0

    aligned = pd.concat({"s": sig, "r": fwd, "c": carry}, axis=1).dropna()
    n = len(aligned)
    span = (
        f"{aligned.index[0].date()}..{aligned.index[-1].date()}" if n else "EMPTY"
    )
    print(f"[reexamine-fiscal-hard] aligned cn-IC sample: n={n}  span={span}", file=sys.stderr)

    report: dict = {
        "signal": f"primary_balance.diff({SURVIVOR_L})",
        "instrument": "hard",
        "carry": "embi_spread/10000/12",
        "horizon": int(horizon),
        "n_aligned": int(n),
        "span": span,
        "is_baseline_today": True,
        "note": (
            "BASELINE as-of run date. Re-run this SAME script unchanged as forward months accrue: the "
            "recent rolling/last-K windows will then include genuinely new out-of-time data."
        ),
        "params": {
            "SURVIVOR_L": SURVIVOR_L, "ROLL_WINDOWS": ROLL_WINDOWS, "LASTK": LASTK,
            "TREND_W": TREND_W, "N_MIN": N_MIN,
            "RECENCY_IC_MIN": RECENCY_IC_MIN, "TREND_NEG_TOL": TREND_NEG_TOL,
        },
    }

    # ---------------------------------------------------------------------------------------
    print("\n" + "=" * 84)
    print("A. SUB-PERIOD carry-neutral IC — halves + thirds (baseline)")
    print("   NOTE: the documented thirds ~[.16,.30,.08] were RAW IC (verify_hard_pb_v2 §D); these are")
    print("   CARRY-NEUTRAL thirds, so they differ. The BINDING recency measure is the rolling-36m / last-36m below.")
    print("=" * 84)
    halves = []
    if n:
        halves = [_cn_ic_on(aligned.iloc[a:b]) for a, b in [(0, n // 2), (n // 2, n)]]
    thirds = []
    if n:
        thirds = [_cn_ic_on(aligned.iloc[a:b])
                  for a, b in [(0, n // 3), (n // 3, 2 * n // 3), (2 * n // 3, n)]]
    cn_full = _cn_ic_on(aligned) if n else float("nan")
    print(f"  full-sample cn-IC = {cn_full:+.3f}  (n={n})")
    print(f"  halves cn-IC = [{', '.join(f'{t:+.3f}' for t in halves)}]")
    print(f"  thirds cn-IC = [{', '.join(f'{t:+.3f}' for t in thirds)}]")
    recent_third = float(thirds[-1]) if thirds and np.isfinite(thirds[-1]) else float("nan")
    mid_third = float(thirds[1]) if len(thirds) >= 2 and np.isfinite(thirds[1]) else float("nan")
    print(f"  -> middle third = {mid_third:+.3f}   recent third (cn-IC) = {recent_third:+.3f}  "
          f"(NB: carry-neutral; the recent weakness shows in the rolling-36m/last-36m windows, not this coarse third)")
    report["A_subperiods"] = {
        "full_cn_ic": cn_full,
        "halves_cn_ic": [float(x) for x in halves],
        "thirds_cn_ic": [float(x) for x in thirds],
        "middle_third": mid_third,
        "recent_third": recent_third,
    }

    # ---------------------------------------------------------------------------------------
    print("\n" + "=" * 84)
    print("B. ROLLING carry-neutral IC trajectory — windows W in {36, 48} months")
    print("=" * 84)
    roll_report: dict = {}
    for W in ROLL_WINDOWS:
        series = []  # (end_date, cn_ic)
        for end in range(W, n + 1):
            cn = _cn_ic_on(aligned.iloc[end - W:end])
            series.append((aligned.index[end - 1], cn))
        vals = [v for _, v in series if np.isfinite(v)]
        n_neg = sum(1 for v in vals if v < 0)
        rmin = float(min(vals)) if vals else float("nan")
        rmax = float(max(vals)) if vals else float("nan")
        rlast = float(vals[-1]) if vals else float("nan")
        tail = series[-8:]
        print(f"  W={W}: windows={len(series)}  finite={len(vals)}  "
              f"(min={rmin:+.3f}, max={rmax:+.3f}, last={rlast:+.3f})  count<0={n_neg}")
        print(f"    last {len(tail)} rolling cn-IC: " +
              "  ".join(f"{d.date()}:{(v if np.isfinite(v) else float('nan')):+.3f}" for d, v in tail))
        roll_report[f"W{W}"] = {
            "n_windows": len(series),
            "n_finite": len(vals),
            "min": rmin, "max": rmax, "last": rlast,
            "count_lt_0": int(n_neg),
            "tail": [{"end": str(d.date()), "cn_ic": (float(v) if np.isfinite(v) else None)} for d, v in tail],
        }
    report["B_rolling"] = roll_report

    # ---------------------------------------------------------------------------------------
    print("\n" + "=" * 84)
    print("C. LAST-K carry-neutral IC — K in {24, 36, 48, 60} ('as-of-today' recent strength)")
    print("=" * 84)
    lastk_report: dict = {}
    for K in LASTK:
        sub = aligned.iloc[-K:] if n >= 1 else aligned
        cn = _cn_ic_on(sub)
        print(f"  last-{K:>2d}: cn-IC = {cn:+.3f}  (n={len(sub)})")
        lastk_report[f"K{K}"] = {"cn_ic": (float(cn) if np.isfinite(cn) else None), "n": int(len(sub))}
    report["C_lastk"] = lastk_report

    # ---------------------------------------------------------------------------------------
    print("\n" + "=" * 84)
    print(f"D. TREND — OLS slope (numpy lstsq) of the rolling-{TREND_W}m cn-IC series vs time")
    print("=" * 84)
    # rebuild the rolling-TREND_W series (x = month index 0..m-1; convert slope to per-year for readability)
    tser = []
    for end in range(TREND_W, n + 1):
        cn = _cn_ic_on(aligned.iloc[end - TREND_W:end])
        if np.isfinite(cn):
            tser.append(cn)
    slope_per_month = float("nan")
    slope_per_year = float("nan")
    if len(tser) >= 6:
        x = np.arange(len(tser), dtype=float)
        A = np.column_stack([np.ones(len(x)), x])
        coef, *_ = np.linalg.lstsq(A, np.asarray(tser, dtype=float), rcond=None)
        slope_per_month = float(coef[1])
        slope_per_year = slope_per_month * 12.0
    if not np.isfinite(slope_per_year):
        direction = "indeterminate"
    elif slope_per_year > 0.02:
        direction = "recovering"
    elif slope_per_year < TREND_NEG_TOL:
        direction = "declining"
    else:
        direction = "flat"
    sign = "+" if (np.isfinite(slope_per_year) and slope_per_year >= 0) else "-"
    print(f"  rolling-{TREND_W}m cn-IC points used = {len(tser)}")
    print(f"  slope = {slope_per_month:+.5f}/mo  ({slope_per_year:+.4f}/yr)  sign={sign}  -> {direction}")
    report["D_trend"] = {
        "n_points": len(tser),
        "slope_per_month": slope_per_month,
        "slope_per_year": slope_per_year,
        "sign": sign,
        "direction": direction,
    }

    # ---------------------------------------------------------------------------------------
    print("\n" + "=" * 84)
    print("E. PRE-COMMITTED RECENCY FLAG (computed — thresholds fixed before the result)")
    print("=" * 84)
    last_trend_ic = lastk_report.get(f"K{TREND_W}", {}).get("cn_ic")
    last_trend_ic = float(last_trend_ic) if last_trend_ic is not None else float("nan")
    chk_floor = bool(np.isfinite(last_trend_ic) and last_trend_ic >= RECENCY_IC_MIN)
    chk_sign = bool(np.isfinite(last_trend_ic) and last_trend_ic > 0)
    chk_trend = bool(np.isfinite(slope_per_year) and slope_per_year >= TREND_NEG_TOL)
    recency_ok = chk_floor and chk_sign and chk_trend
    print(f"  rule: recency_ok = (last-{TREND_W}m cn-IC >= {RECENCY_IC_MIN:+.2f}) AND (last-{TREND_W}m cn-IC > 0) "
          f"AND (rolling-{TREND_W} trend/yr >= {TREND_NEG_TOL:+.2f})")
    print(f"  last-{TREND_W}m cn-IC = {last_trend_ic:+.3f}")
    print(f"    [Y/N] floor (>= {RECENCY_IC_MIN:+.2f})          = {'Y' if chk_floor else 'N'}")
    print(f"    [Y/N] sign positive (> 0)            = {'Y' if chk_sign else 'N'}")
    print(f"    [Y/N] trend not strongly negative    = {'Y' if chk_trend else 'N'}  "
          f"(slope/yr={slope_per_year:+.4f} vs tol {TREND_NEG_TOL:+.2f})")
    print(f"  -> recency_ok = {recency_ok}")
    report["E_recency_flag"] = {
        "rule": (
            f"(last-{TREND_W}m cn-IC >= {RECENCY_IC_MIN}) AND (last-{TREND_W}m cn-IC > 0) "
            f"AND (rolling-{TREND_W} slope/yr >= {TREND_NEG_TOL})"
        ),
        "last_trend_ic": last_trend_ic,
        "check_floor": chk_floor,
        "check_sign_positive": chk_sign,
        "check_trend_not_strongly_negative": chk_trend,
        "recency_ok": recency_ok,
    }

    # ---------------------------------------------------------------------------------------
    # HONEST VERDICT — computed from the measured numbers above, never hardcoded.
    # ---------------------------------------------------------------------------------------
    print("\n" + "=" * 84)
    print("HONEST VERDICT")
    print("=" * 84)
    # "still supports" = the pre-committed recency flag holds; "decaying further" = recent third fell
    # below the documented +0.08 AND the rolling trend is declining.
    weak_third_decaying = bool(
        np.isfinite(recent_third) and recent_third < 0.08 and direction == "declining"
    )
    if recency_ok:
        verdict = (
            f"RECENT performance STILL SUPPORTS fiscal_hard as a candidate: last-{TREND_W}m cn-IC="
            f"{last_trend_ic:+.3f} clears the pre-committed floor with positive sign and a non-declining "
            f"rolling-{TREND_W} trend ({direction}, slope/yr={slope_per_year:+.4f})."
        )
    elif weak_third_decaying:
        verdict = (
            f"WEAK RECENT THIRD IS DECAYING FURTHER: recent third={recent_third:+.3f} (< doc'd +0.08) and the "
            f"rolling-{TREND_W} trend is DECLINING (slope/yr={slope_per_year:+.4f}); last-{TREND_W}m cn-IC="
            f"{last_trend_ic:+.3f} fails the pre-committed recency flag. Do NOT lean on recent strength."
        )
    else:
        verdict = (
            f"RECENT performance does NOT clear the pre-committed recency flag (recency_ok=False): last-{TREND_W}m "
            f"cn-IC={last_trend_ic:+.3f}, trend {direction} (slope/yr={slope_per_year:+.4f}). The weak recent "
            f"third has not recovered; treat the recency caveat as UNRESOLVED."
        )
    print(f"  {verdict}")
    print(f"  NOTE: this is the BASELINE today (span {span}, n={n}). Re-run the SAME script as forward months "
          f"accrue — the recent rolling/last-K windows will then include genuinely new out-of-time data.")
    report["verdict"] = {
        "recency_ok": recency_ok,
        "weak_third_decaying_further": weak_third_decaying,
        "text": verdict,
    }

    report_path = os.path.join(eng.OUTPUT_DIR, "reexamine_fiscal_hard.json")
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2, default=float)
    print(f"\n[reexamine-fiscal-hard] wrote {report_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
