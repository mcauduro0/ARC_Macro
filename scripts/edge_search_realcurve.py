"""Phase 4.5 — edge search round 4: the NTN-B REAL CURVE, now that history exists.

The real-curve track was dead in Phase 4.4 (NTN-B CSVs held a single 2024 snapshot). Phase 4.5's
Tesouro connector collected 259 months of 5y/10y real yields (2004-2026), so we can finally gate it.
Economic priors (oriented to rate-receiver gain): a high real rate = tight policy = rates fall ahead;
disinflation (falling breakeven) = cuts ahead. Breakeven = nominal DI yield - NTN-B real yield.

Same gate (carry-neutral IC + half-sample decay + refit-OOS CPCV), carry-neutralized vs each instrument's
term carry, deflated for the cumulative count. Run: python scripts/edge_search_realcurve.py
"""

from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODEL_DIR = os.path.join(ROOT, "server", "model")
DATA_DIR = os.path.join(MODEL_DIR, "data")
for _k, _v in {
    "ARC_CAUSAL_WINSORIZE": "1", "ARC_FORWARD_TARGET": "1", "ARC_HMM_FILTERED": "1",
    "ARC_BOUNDED_FFILL": "1", "ARC_CAUSAL_RSTAR_REGIME": "1", "ARC_REGIME_PER_SERIES": "1",
    "ARC_FEAT_PER_SERIES": "1", "ARC_REGIME_POINT_IN_TIME": "1", "ARC_PUBLICATION_LAG": "1",
    "ARC_CAUSAL_INTERP": "1", "ARC_CARRY_HARD_SPREAD": "1",
}.items():
    os.environ.setdefault(_k, _v)
sys.path.insert(0, MODEL_DIR)
sys.path.insert(0, ROOT)

PRIOR_HYPOTHESES = 69  # cumulative rounds 1-3


def _czscore(s, min_periods=24):
    import numpy as np
    s = s.astype("float64")
    mu = s.expanding(min_periods=min_periods).mean()
    sd = s.expanding(min_periods=min_periods).std().replace(0.0, np.nan)
    return (s - mu) / sd


def _load_real(name, idx):
    import pandas as pd
    path = os.path.join(DATA_DIR, f"{name}.csv")
    if not os.path.exists(path):
        return pd.Series(index=idx, dtype="float64")
    s = pd.read_csv(path, index_col=0, header=None).iloc[:, 0]
    s.index = pd.to_datetime(s.index)
    return s.reindex(idx)


def main() -> None:
    import json
    import pandas as pd

    import macro_risk_os_v2 as eng
    from arc.eval import forward_returns
    from arc.research import rank_signals

    print("[realcurve] initializing engine (PIT features)...", file=sys.stderr)
    e = eng.ProductionEngine(eng.DEFAULT_CONFIG)
    e.initialize()
    feat_df = e.feature_engine.feature_df
    ret_df = e.data_layer.ret_df
    monthly = e.data_layer.monthly
    horizon = eng.DEFAULT_CONFIG.get("prediction_horizon_months", 1)
    idx = feat_df.index

    def m(key):
        s = monthly.get(key)
        return s.reindex(idx) if s is not None else pd.Series(index=idx, dtype="float64")

    real5 = _load_real("NTNB_REAL_5Y", idx)
    real10 = _load_real("NTNB_REAL_10Y", idx)
    print(f"[realcurve] NTN-B real 5y obs={real5.dropna().shape[0]} 10y obs={real10.dropna().shape[0]}",
          file=sys.stderr)
    # nominal DI yields for breakeven (engine monthly keys di_5y / di_10y are % yields)
    di5, di10 = m("di_5y"), m("di_10y")
    be5 = di5 - real5   # implied 5y breakeven inflation
    be10 = di10 - real10

    new = {}
    new["realrate_5y_z"] = _czscore(real5)               # high real rate -> receiver gain (+)
    new["realrate_10y_z"] = _czscore(real10)
    new["real_slope"] = (real10 - real5)                 # steep real curve -> long receiver (+)
    new["neg_real5_mom3"] = -real5.diff(3)               # falling real rate (easing underway) -> (+)?
    new["neg_be5_z"] = -_czscore(be5)                    # disinflation (low breakeven) -> cuts (+)
    new["neg_be10_z"] = -_czscore(be10)
    new["neg_be5_mom3"] = -be5.diff(3)                   # falling breakeven momentum -> (+)
    feat_df = feat_df.join(pd.DataFrame(new), how="outer")

    CANDIDATES = {
        "front": ["realrate_5y_z", "neg_be5_z", "neg_be5_mom3"],
        "belly": ["realrate_5y_z", "real_slope", "neg_be5_mom3"],
        "long":  ["realrate_10y_z", "real_slope", "neg_be10_z"],
    }
    fwd = {inst: forward_returns(ret_df[inst], horizon) for inst in CANDIDATES}
    carry = {inst: feat_df[f"carry_{inst}"] for inst in CANDIDATES if f"carry_{inst}" in feat_df.columns}

    out = rank_signals(CANDIDATES, feat_df, fwd, carry)
    cumulative = PRIOR_HYPOTHESES + out["n_hypotheses"]
    report_path = os.path.join(eng.OUTPUT_DIR, "edge_search_realcurve.json")
    out["cumulative_hypotheses"] = cumulative
    with open(report_path, "w") as f:
        json.dump(out, f, indent=2, default=float)

    print("\n" + "=" * 96)
    print("PHASE 4.5 — EDGE SEARCH ROUND 4: NTN-B REAL CURVE (now with 259mo history), gated")
    print("=" * 96)
    print(f"  new hypotheses={out['n_hypotheses']}  cumulative (rounds 1-4)={cumulative}")
    print(f"  {'inst':5s} {'feature':16s} {'n':>4s} {'IC':>7s} {'cnIC':>7s} {'H1':>7s} {'H2':>7s} "
          f"{'decay':>7s} {'OOSm':>7s} {'OOSmin':>7s}  verdict")
    print("  " + "-" * 96)
    for r in out["results"]:
        if r.get("n", 0) < 1 or "ic" not in r:
            print(f"  {r['instrument']:5s} {r['feature']:16s}  --  {'; '.join(r.get('reasons', []))}")
            continue
        v = "PASS" if r["passed"] else "fail: " + "; ".join(r["reasons"])
        print(f"  {r['instrument']:5s} {r['feature']:16s} {r['n']:>4d} {r['ic']:+.3f} "
              f"{r['carry_neutral_ic']:+.3f} {r['h1']:+.3f} {r['h2']:+.3f} {r['decay']:+.3f} "
              f"{r['refit_oos_mean']:+.3f} {r['refit_oos_min']:+.3f}  {v}")
    if out["survivors"]:
        print("\n  SURVIVORS (verify adversarially; NOT promotions):")
        for r in out["survivors"]:
            print(f"    {r['instrument']}/{r['feature']}: cnIC={r['carry_neutral_ic']:+.3f} "
                  f"H2={r['h2']:+.3f} refit-OOS={r['refit_oos_mean']:+.3f}")
        print(f"\n  NOTE: ~{cumulative} cumulative hypotheses => ~{cumulative*0.05:.0f} false positives at 5%.")
    else:
        print("\n  NO SURVIVORS — no real-curve / breakeven signal clears the gate.")
    print(f"\n  report: {report_path}")


if __name__ == "__main__":
    main()
