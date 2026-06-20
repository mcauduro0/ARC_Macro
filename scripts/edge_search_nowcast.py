"""Phase 4.4 — honest edge search, round 2: real-curve (NTN-B / breakeven) + activity-nowcast signals.

Round 1 (scripts/signal_research.py) screened 45 pre-registered macro + momentum hypotheses; only
front/mom3 survived. This round adds two fresh, economically-motivated families that carry information
NOT in the round-1 set:

  (1) REAL CURVE — NTN-B real yields + breakevens (already collected, previously ungated). Economic
      prior: a high real rate = tight policy = rates fall ahead => rate-receiver gains; disinflation
      (falling breakeven) => cuts => receiver gains.
  (2) ACTIVITY NOWCAST — a strictly point-in-time mixed-frequency factor (arc.features.nowcast) that
      reads current-month activity from timelier series (Brazil equity, commodities, terms of trade)
      while IBC-Br is still 1-2 months stale. Economic prior: weakening activity => cuts => receiver
      gains. Closes the documented IBC-Br blindspot.

Each candidate is ORIENTED to its economic prior (so "higher signal => higher forward receiver return")
and run through the SAME gate (carry-neutralized IC, half-sample H1/H2 decay, refit-OOS CPCV), carry-
neutralized against each instrument's TRUE carry. Multiple testing is cumulative: any survivor must be
read against ~55 total hypotheses screened across rounds 1+2 (≈3 false positives expected at 5%).

Run: python scripts/edge_search_nowcast.py
"""

from __future__ import annotations

import json
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

PRIOR_HYPOTHESES = 45  # round 1 (signal_research.py) — for cumulative multiple-testing context
ACTIVITY_KEYS = ["ibc_br", "ewz", "iron_ore", "tot", "bcom"]


def _czscore(s, min_periods=24):
    import numpy as np
    s = s.astype("float64")
    mu = s.expanding(min_periods=min_periods).mean()
    sd = s.expanding(min_periods=min_periods).std().replace(0.0, np.nan)
    return (s - mu) / sd


def main() -> None:
    import numpy as np  # noqa: E402
    import pandas as pd  # noqa: E402

    import macro_risk_os_v2 as eng  # noqa: E402
    from arc.eval import forward_returns  # noqa: E402
    from arc.features.nowcast import activity_nowcast, nowcast_surprise  # noqa: E402
    from arc.research import rank_signals  # noqa: E402

    print("[edge2] initializing engine (PIT features)...", file=sys.stderr)
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

    # ---- (1) real-curve features (oriented to the receiver-gain prior) ----
    new = {}
    ntnb5, ntnb10 = m("ntnb_5y"), m("ntnb_10y")
    be5, be10 = m("breakeven_5y"), m("breakeven_10y")
    new["realrate_5y_z"] = _czscore(ntnb5)                 # high real rate -> receiver gain (+)
    new["realrate_10y_z"] = _czscore(ntnb10)
    new["real_slope"] = (ntnb10 - ntnb5)                   # steep real curve -> long receiver gain (+)
    new["neg_breakeven_5y_z"] = -_czscore(be5)             # disinflation (low breakeven) -> cuts (+)
    new["neg_breakeven_10y_z"] = -_czscore(be10)

    # ---- (2) activity nowcast (strictly PIT) ----
    have = [k for k in ACTIVITY_KEYS if k in monthly and monthly[k] is not None and len(monthly[k].dropna())]
    print(f"[edge2] nowcast inputs available: {have}", file=sys.stderr)
    factor = activity_nowcast(monthly, ACTIVITY_KEYS, ref_col="ibc_br").reindex(idx)
    surprise = nowcast_surprise(factor)
    new["neg_nowcast"] = -factor                           # weak activity -> cuts -> receiver gain (+)
    new["neg_nowcast_surprise"] = -surprise
    new["neg_nowcast_mom3"] = -factor.diff(3)              # decelerating activity -> receiver gain (+)
    # sanity: does the nowcast even track IBC-Br? (honesty check, reported not gated)
    ibc = m("ibc_br")
    cov = pd.concat([factor.diff(), ibc.diff()], axis=1).dropna()
    nowcast_vs_ibc = float(np.corrcoef(cov.iloc[:, 0], cov.iloc[:, 1])[0, 1]) if len(cov) > 12 else float("nan")

    feat_df = feat_df.join(pd.DataFrame(new), how="outer")

    # ---- pre-registered candidates (NOT a full cross-product — economically motivated) ----
    CANDIDATES = {
        "front": ["realrate_5y_z", "neg_breakeven_5y_z", "neg_nowcast_surprise"],
        "belly": ["realrate_5y_z", "real_slope", "neg_nowcast"],
        "long":  ["realrate_10y_z", "real_slope", "neg_breakeven_10y_z", "neg_nowcast_mom3"],
    }
    n_new = sum(len(v) for v in CANDIDATES.values())

    fwd = {inst: forward_returns(ret_df[inst], horizon) for inst in CANDIDATES}
    carry = {inst: feat_df[f"carry_{inst}"] for inst in CANDIDATES if f"carry_{inst}" in feat_df.columns}

    out = rank_signals(CANDIDATES, feat_df, fwd, carry)
    cumulative = PRIOR_HYPOTHESES + out["n_hypotheses"]

    report_path = os.path.join(eng.OUTPUT_DIR, "edge_search_nowcast.json")
    out["nowcast_vs_ibc_corr"] = nowcast_vs_ibc
    out["cumulative_hypotheses"] = cumulative
    with open(report_path, "w") as f:
        json.dump(out, f, indent=2, default=float)

    print("\n" + "=" * 92)
    print("PHASE 4.4 — EDGE SEARCH ROUND 2: REAL CURVE + ACTIVITY NOWCAST (gated, carry-neutral)")
    print("=" * 92)
    print(f"  nowcast tracks IBC-Br (corr of m/m changes): {nowcast_vs_ibc:+.2f}   "
          f"new hypotheses={n_new}  cumulative (rounds 1+2)={cumulative}")
    print(f"  {'inst':5s} {'feature':22s} {'n':>4s} {'IC':>7s} {'cnIC':>7s} {'H1':>7s} {'H2':>7s} "
          f"{'decay':>7s} {'OOSm':>7s} {'OOSmin':>7s}  verdict")
    print("  " + "-" * 100)
    for r in out["results"]:
        if r.get("n", 0) < 1 or "ic" not in r:
            print(f"  {r['instrument']:5s} {r['feature']:22s}  --  {'; '.join(r.get('reasons', []))}")
            continue
        v = "PASS" if r["passed"] else "fail: " + "; ".join(r["reasons"])
        print(f"  {r['instrument']:5s} {r['feature']:22s} {r['n']:>4d} {r['ic']:+.3f} "
              f"{r['carry_neutral_ic']:+.3f} {r['h1']:+.3f} {r['h2']:+.3f} {r['decay']:+.3f} "
              f"{r['refit_oos_mean']:+.3f} {r['refit_oos_min']:+.3f}  {v}")

    if out["survivors"]:
        print("\n  SURVIVORS (candidates to adversarially re-verify, NOT promotions):")
        for r in out["survivors"]:
            print(f"    {r['instrument']}/{r['feature']}: cnIC={r['carry_neutral_ic']:+.3f} "
                  f"H2={r['h2']:+.3f} refit-OOS={r['refit_oos_mean']:+.3f}")
        print(f"\n  NOTE: ~{cumulative} cumulative hypotheses => expect ~{cumulative*0.05:.0f} false "
              f"positives at 5%. A survivor must clear deflation on a single-use forward holdout (paper).")
    else:
        print("\n  NO SURVIVORS — no real-curve or nowcast signal clears the gate.")
    print(f"\n  report: {report_path}")


if __name__ == "__main__":
    main()
