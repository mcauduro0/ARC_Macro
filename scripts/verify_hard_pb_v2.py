"""Phase 4.5 (RE-TEST) — pb_momentum (fiscal primary balance) with MORE data + a LONG global-risk control.

v1 (scripts/verify_hard_pb.py) left two threads dangling:
  - LOOKBACK FRAGILITY: diff(6) passed but diff(9)/diff(12) collapsed → maybe a single-window artifact.
  - INCONCLUSIVE GLOBAL-RISK CONTROL: section B used US HY spread, whose history is too short
    (us_hy_spread starts 2023-06 → n=35 < 40 after alignment), so the partial-IC test never ran.

This v2 mirrors v1 section-for-section (A..F) and keeps the _partial_ic helper, but upgrades:
  B. Replaces the short US-HY control with a PANEL of LONG-history global-risk controls so n >> 40:
        vix (~169 mo), nfci (Chicago Fed FCI, ~196 mo), US term spread = ust_10y - ust_2y (long),
        and the CHANGE in Brazil risk (d_cds = cds_5y.diff(), with embi_spread.diff() fallback if cds short).
     Reports IC(carry) then IC(carry + vix + nfci + us_term + d_cds) with its n.
  A. EXPANDED lookback grid diff(1,2,3,6,9,12) so the fragility verdict is crisp.
  D. LONGER sub-period split: HALVES *and* THIRDS (was thirds only).

Target instrument stays 'hard'; carry = embi_spread/10000/12 (true spread carry); signal = primary_balance.

It is 1 of many cumulative hypotheses — RED-FLAG discipline: try to break it before calling it an edge.
The bar to beat is what front/mom3 and the activity nowcast cleared: robust across lookbacks
+ survives the LONG global-risk control + not period-concentrated.

Run: python scripts/verify_hard_pb_v2.py
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

ACTIVITY_KEYS = ["ibc_br", "ewz", "iron_ore", "tot", "bcom"]
LOOKBACKS = [1, 2, 3, 6, 9, 12]  # EXPANDED grid (v1 was 3,6,9,12)
SURVIVOR_L = 6                    # the diff window that passed in v1


def _partial_ic(signal, fwd, controls):
    """Partial IC of `signal` vs `fwd`, both residualized on `controls` (+ intercept).

    Returns (ic, n). Returns (nan, n) when n < 40 or a residual is degenerate. (kept verbatim from v1)
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


def main() -> None:
    import numpy as np
    import pandas as pd

    import macro_risk_os_v2 as eng
    from arc.eval import forward_returns
    from arc.eval.metrics import information_coefficient
    from arc.features.nowcast import activity_nowcast
    from arc.research import evaluate_signal

    print("[verify-hard-v2] initializing engine...", file=sys.stderr)
    e = eng.ProductionEngine(eng.DEFAULT_CONFIG)
    e.initialize()
    ret_df = e.data_layer.ret_df
    monthly = e.data_layer.monthly
    idx = e.feature_engine.feature_df.index
    horizon = eng.DEFAULT_CONFIG.get("prediction_horizon_months", 1)

    pb = monthly.get("primary_balance").reindex(idx)
    fwd = forward_returns(ret_df["hard"], horizon)
    carry = (monthly.get("embi_spread").reindex(idx)) / 10000.0 / 12.0

    # ---- LONG global-risk control panel (replaces the short US-HY control) ------------------
    vix = monthly.get("vix", pd.Series(dtype=float)).reindex(idx)
    nfci = monthly.get("nfci", pd.Series(dtype=float)).reindex(idx)
    ust2 = monthly.get("ust_2y", pd.Series(dtype=float)).reindex(idx)
    ust10 = monthly.get("ust_10y", pd.Series(dtype=float)).reindex(idx)
    us_term = (ust10 - ust2)  # US 10y-2y term spread (long history)
    cds = monthly.get("cds_5y", pd.Series(dtype=float)).reindex(idx)
    embi = monthly.get("embi_spread", pd.Series(dtype=float)).reindex(idx)
    # Brazil risk CHANGE; prefer cds_5y.diff(), fall back to embi_spread.diff() if cds too short.
    d_cds = cds.diff()
    cds_used = "d_cds(cds_5y)"
    if d_cds.dropna().shape[0] < 40:
        d_cds = embi.diff()
        cds_used = "d_cds(embi_spread fallback)"
    panel = [carry, vix, nfci, us_term, d_cds]
    panel_names = ["carry", "vix", "nfci", "us_term(10y-2y)", cds_used]

    # report each control's own raw length so the n upgrade is auditable
    print("[verify-hard-v2] control history lengths (non-NaN months):", file=sys.stderr)
    for nm, s in zip(panel_names, panel):
        print(f"    {nm:<28s} {int(s.dropna().shape[0]):>4d}", file=sys.stderr)

    print("\n" + "=" * 84)
    print("A. LOOKBACK ROBUSTNESS — pb_momentum = primary_balance.diff(L)  [EXPANDED grid 1,2,3,6,9,12]")
    print("=" * 84)
    a_pass = {}
    a_cnic = {}
    for L in LOOKBACKS:
        r = evaluate_signal(pb.diff(L), fwd, carry)
        a_pass[L] = bool(r.get("passed"))
        a_cnic[L] = float(r.get("carry_neutral_ic", float("nan")))
        print(f"  diff({L:>2d}): cnIC={r.get('carry_neutral_ic', float('nan')):+.3f} "
              f"H1={r.get('h1', float('nan')):+.3f} H2={r.get('h2', float('nan')):+.3f} "
              f"OOSm={r.get('refit_oos_mean', float('nan')):+.3f} OOSmin={r.get('refit_oos_min', float('nan')):+.3f} "
              f"{'PASS' if r.get('passed') else 'fail'}")
    # robustness = the SURVIVOR window passes AND its IC sign holds across the grid
    grid_ic = [a_cnic[L] for L in LOOKBACKS if np.isfinite(a_cnic[L])]
    sign_consistent = bool(grid_ic) and (all(v >= 0 for v in grid_ic) or all(v <= 0 for v in grid_ic))
    n_pass = sum(1 for L in LOOKBACKS if a_pass[L])
    robust_lookback = bool(a_pass.get(SURVIVOR_L)) and sign_consistent and (n_pass >= 3)
    print(f"  -> windows passing={n_pass}/{len(LOOKBACKS)}  sign-consistent across grid={sign_consistent}  "
          f"robust_lookback={robust_lookback}")

    sig = pb.diff(SURVIVOR_L)  # the survivor
    print("\n" + "=" * 84)
    print("B. PARTIAL IC vs carry + LONG global-risk panel (VIX, NFCI, US term, d_BR-risk) — beyond risk-on/off?")
    print("=" * 84)
    ic_c, n_c = _partial_ic(sig, fwd, [carry])
    ic_m, n_m = _partial_ic(sig, fwd, panel)
    print(f"  controls = {panel_names}")
    print(f"  pb_mom{SURVIVOR_L}: IC(carry)={ic_c:+.3f} (n={n_c})  "
          f"IC(carry+VIX+NFCI+us_term+d_cds)={ic_m:+.3f} (n={n_m})")
    b_conclusive = (n_m >= 40) and np.isfinite(ic_m)
    # "survives" = still meaningfully predictive after neutralizing the whole risk panel
    b_survives = b_conclusive and (abs(ic_m) >= 0.10) and (np.sign(ic_m) == np.sign(ic_c) if np.isfinite(ic_c) else True)
    print(f"  -> conclusive (n>=40)={b_conclusive}  survives_long_risk_control={b_survives}")

    print("\n" + "=" * 84)
    print("C. LAG SCAN (predictive vs coincident/leaky)")
    print("=" * 84)
    row = []
    c_ics = {}
    for L in [-1, 0, 1, 2]:
        r = fwd.shift(-(L - 1)) if L != 1 else fwd
        d = pd.concat([sig, r], axis=1).dropna()
        ic = information_coefficient(d.iloc[:, 0], d.iloc[:, 1]) if len(d) > 30 else float("nan")
        c_ics[L] = float(ic)
        row.append(f"L={L:+d}:{ic:+.3f}")
    print(f"  pb_mom{SURVIVOR_L}  " + "  ".join(row))
    # predictive (not leaky): the forward (L=+1) IC should not be dwarfed by a coincident/backward spike
    fwd_ic = c_ics.get(1, float("nan"))
    other = [abs(c_ics[k]) for k in (-1, 0, 2) if np.isfinite(c_ics.get(k, float("nan")))]
    not_leaky = np.isfinite(fwd_ic) and (not other or abs(fwd_ic) >= 0.6 * max(other))
    print(f"  -> forward IC={fwd_ic:+.3f}  not_leaky={not_leaky}")

    print("\n" + "=" * 84)
    print("D. SUB-PERIODS — HALVES *and* THIRDS (longer split; v1 was thirds only)")
    print("=" * 84)
    d = pd.concat([sig, fwd, carry], axis=1).dropna()
    n = len(d)
    halves = [information_coefficient(d.iloc[a:b, 0], d.iloc[a:b, 1])
              for a, b in [(0, n // 2), (n // 2, n)]]
    thirds = [information_coefficient(d.iloc[a:b, 0], d.iloc[a:b, 1])
              for a, b in [(0, n // 3), (n // 3, 2 * n // 3), (2 * n // 3, n)]]
    print(f"  pb_mom{SURVIVOR_L} halves = [{', '.join(f'{t:+.3f}' for t in halves)}]  (n={n})")
    print(f"  pb_mom{SURVIVOR_L} thirds = [{', '.join(f'{t:+.3f}' for t in thirds)}]")
    seg = [float(x) for x in (halves + thirds) if np.isfinite(x)]
    # not period-concentrated = same sign in every sub-window (halves and thirds)
    not_concentrated = bool(seg) and (all(v >= 0 for v in seg) or all(v <= 0 for v in seg))
    print(f"  -> sign-consistent across halves+thirds (not period-concentrated)={not_concentrated}")

    print("\n" + "=" * 84)
    print("E. ORTHOGONALITY to existing edges (front/mom3, activity nowcast)")
    print("=" * 84)
    front_mom3 = ret_df["front"].rolling(3).sum().reindex(idx)
    factor = activity_nowcast(monthly, ACTIVITY_KEYS, ref_col="ibc_br").reindex(idx)
    c_fm = pd.concat([sig, front_mom3], axis=1).dropna()
    c_nc = pd.concat([sig, factor], axis=1).dropna()
    corr_fm = float(np.corrcoef(c_fm.iloc[:, 0], c_fm.iloc[:, 1])[0, 1]) if len(c_fm) > 12 else float("nan")
    corr_nc = float(np.corrcoef(c_nc.iloc[:, 0], c_nc.iloc[:, 1])[0, 1]) if len(c_nc) > 12 else float("nan")
    ic_x_fm, _ = _partial_ic(sig, fwd, [carry, front_mom3])
    ic_x_nc, _ = _partial_ic(sig, fwd, [carry, factor])
    print(f"  corr(pb_mom{SURVIVOR_L}, front_mom3)={corr_fm:+.2f}  corr(pb_mom{SURVIVOR_L}, nowcast)={corr_nc:+.2f}")
    print(f"  IC pb_mom{SURVIVOR_L} | carry+front_mom3 = {ic_x_fm:+.3f}   "
          f"IC pb_mom{SURVIVOR_L} | carry+nowcast = {ic_x_nc:+.3f}")
    orthogonal = (
        (abs(corr_fm) < 0.5 if np.isfinite(corr_fm) else True)
        and (abs(corr_nc) < 0.5 if np.isfinite(corr_nc) else True)
        and (abs(ic_x_fm) >= 0.10 if np.isfinite(ic_x_fm) else False)
        and (abs(ic_x_nc) >= 0.10 if np.isfinite(ic_x_nc) else False)
    )
    print(f"  -> orthogonal_to_existing_edges={orthogonal}")

    print("\n" + "=" * 84)
    print("F. PLACEBO (random must FAIL)")
    print("=" * 84)
    rng = np.random.default_rng(0)
    rp = evaluate_signal(pd.Series(rng.normal(size=len(idx)), index=idx), fwd, carry)
    placebo_fails = not bool(rp.get("passed"))
    print(f"  random/hard: cnIC={rp.get('carry_neutral_ic', float('nan')):+.3f} "
          f"OOSm={rp.get('refit_oos_mean', float('nan')):+.3f}  "
          f"{'PASS(!?)' if rp.get('passed') else 'fail (good)'}")
    print(f"  -> placebo_fails={placebo_fails}")

    # ---------------------------------------------------------------------------------------
    # HONEST VERDICT — computed from the measured numbers above, never hardcoded.
    # Bar to clear (same as front/mom3 + nowcast): robust across lookbacks AND survives the
    # LONG global-risk control AND not period-concentrated. (orthogonality + placebo are guards.)
    # ---------------------------------------------------------------------------------------
    clears_bar = (
        robust_lookback
        and b_conclusive
        and b_survives
        and not_concentrated
        and not_leaky
        and orthogonal
        and placebo_fails
    )
    print("\n" + "=" * 84)
    print("HONEST VERDICT")
    print("=" * 84)
    checks = {
        "robust_lookback(A)": robust_lookback,
        "long-risk-control conclusive (B,n>=40)": b_conclusive,
        "survives_long_risk_control(B)": b_survives,
        "not_period_concentrated(D)": not_concentrated,
        "not_leaky(C)": not_leaky,
        "orthogonal_to_edges(E)": orthogonal,
        "placebo_fails(F)": placebo_fails,
    }
    print("  " + "  ".join(f"{k}={'Y' if v else 'N'}" for k, v in checks.items()))
    failed = [k for k, v in checks.items() if not v]
    if clears_bar:
        print(f"  VERDICT: pb_momentum (diff{SURVIVOR_L}) NOW CLEARS the bar — robust across an expanded "
              f"lookback grid, survives the LONG global-risk panel (n={n_m}>>40), and is not "
              f"period-concentrated. Promote to a candidate edge.")
    else:
        print(f"  VERDICT: pb_momentum (diff{SURVIVOR_L}) does NOT clear the bar. Failing checks: {failed}. "
              f"Long-risk-control n={n_m} (conclusive={b_conclusive}). Treat as not-an-edge / shelve.")


if __name__ == "__main__":
    main()
