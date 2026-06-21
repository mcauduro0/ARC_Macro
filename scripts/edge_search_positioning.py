"""Phase 4.5 — edge search round 5: POSITIONING & FLOWS, gated with data that EXISTS today.

CFTC BRL net speculative positioning (weekly, 1995-2026) is already collected. Positioning is primarily
an FX signal and secondarily a risk-channel signal for rates. Economic priors: extreme LONG-BRL spec
positioning (crowded) -> mean-reversion / vulnerable BRL -> SHORT-BRL (negative); positioning momentum
can be trend-confirming -> test both signs (the gate carry-neutralizes + deflates, so we let it decide).

BCB foreign-flow series (IDP / portfolio flows) are included as extra FX candidates: the BCB SGS API is
502, but scripts/collect_flows.py collected them via a provenance-verified IPEADATA fallback (same BPM6
series, 376 monthly obs each). If the CSVs are absent the script still runs and simply skips those signals.

Same gate (carry-neutral IC + half-sample decay + refit-OOS CPCV), carry-neutralized vs each instrument's
term carry, deflated for the cumulative count. Run: python scripts/edge_search_positioning.py
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

PRIOR_HYPOTHESES = 78  # cumulative rounds 1-4 (69 after round 3 + 9 tested in the realcurve round 4)


def _czscore(s, min_periods=24):
    import numpy as np
    s = s.astype("float64")
    mu = s.expanding(min_periods=min_periods).mean()
    sd = s.expanding(min_periods=min_periods).std().replace(0.0, np.nan)
    return (s - mu) / sd


def _load_monthly(name, idx):
    """Best-effort load of a weekly/irregular "YYYY-MM-DD,value" CSV; resample to MONTH-END
    (last obs per month) and reindex to idx. Returns an all-NaN series if the file is absent."""
    import pandas as pd
    path = os.path.join(DATA_DIR, f"{name}.csv")
    if not os.path.exists(path):
        return None
    s = pd.read_csv(path, index_col=0, header=None).iloc[:, 0]
    s.index = pd.to_datetime(s.index)
    s = s.sort_index().resample("ME").last()
    return s.reindex(idx)


def main() -> None:
    import json
    import pandas as pd

    import macro_risk_os_v2 as eng
    from arc.eval import forward_returns
    from arc.research import rank_signals

    print("[positioning] initializing engine (PIT features)...", file=sys.stderr)
    e = eng.ProductionEngine(eng.DEFAULT_CONFIG)
    e.initialize()
    feat_df = e.feature_engine.feature_df
    ret_df = e.data_layer.ret_df
    horizon = eng.DEFAULT_CONFIG.get("prediction_horizon_months", 1)
    idx = feat_df.index

    cot_net = _load_monthly("CFTC_BRL_NET_SPEC", idx)
    if cot_net is None:
        print("[positioning] FATAL: CFTC_BRL_NET_SPEC.csv absent — nothing to gate.", file=sys.stderr)
        return
    print(f"[positioning] CFTC BRL net spec obs={cot_net.dropna().shape[0]}", file=sys.stderr)

    new = {}
    new["cot_net_z"] = _czscore(cot_net)              # crowding level (LONG-BRL extreme); fade -> test both
    new["neg_cot_net_z"] = -_czscore(cot_net)         # fade crowding: extreme long BRL -> short BRL (prior +)
    new["cot_mom3"] = cot_net.diff(3)                 # positioning momentum (trend-confirming?)
    new["cot_mom3_z"] = _czscore(cot_net.diff(3))     # standardized positioning momentum

    fx_feats = ["cot_net_z", "neg_cot_net_z", "cot_mom3", "cot_mom3_z"]

    # Best-effort foreign-flow candidates (BCB API is 502 today -> files absent -> skipped).
    for flow_name, tag in (("IDP_FLOW", "idp"), ("PORTFOLIO_FLOW", "portfolio")):
        flow = _load_monthly(flow_name, idx)
        if flow is None:
            print(f"[positioning] {flow_name}.csv absent — skipping {tag} flow signals.", file=sys.stderr)
            continue
        print(f"[positioning] {flow_name} obs={flow.dropna().shape[0]}", file=sys.stderr)
        new[f"{tag}_flow_z"] = _czscore(flow)              # inflows -> BRL support (prior +)
        new[f"{tag}_flow_mom3_z"] = _czscore(flow.diff(3))  # accelerating inflows -> BRL support (prior +)
        fx_feats += [f"{tag}_flow_z", f"{tag}_flow_mom3_z"]

    feat_df = feat_df.join(pd.DataFrame(new), how="outer")

    # Positioning is primarily an FX signal; secondarily a risk-channel signal for rates (hard, long).
    risk_subset = ["cot_net_z", "neg_cot_net_z", "cot_mom3_z"]
    CANDIDATES = {
        "fx":   fx_feats,
        "hard": risk_subset,
        "long": risk_subset,
    }
    fwd = {inst: forward_returns(ret_df[inst], horizon) for inst in CANDIDATES}
    carry = {inst: feat_df[f"carry_{inst}"] for inst in CANDIDATES if f"carry_{inst}" in feat_df.columns}

    out = rank_signals(CANDIDATES, feat_df, fwd, carry)
    cumulative = PRIOR_HYPOTHESES + out["n_hypotheses"]
    report_path = os.path.join(eng.OUTPUT_DIR, "edge_search_positioning.json")
    out["cumulative_hypotheses"] = cumulative
    with open(report_path, "w") as f:
        json.dump(out, f, indent=2, default=float)

    print("\n" + "=" * 96)
    print("PHASE 4.5 — EDGE SEARCH ROUND 5: POSITIONING & FLOWS (CFTC BRL net spec), gated")
    print("=" * 96)
    print(f"  new hypotheses={out['n_hypotheses']}  cumulative (rounds 1-5)={cumulative}")
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
        print("\n  NO SURVIVORS — no positioning / flow signal clears the gate.")
    print(f"\n  report: {report_path}")


if __name__ == "__main__":
    main()
