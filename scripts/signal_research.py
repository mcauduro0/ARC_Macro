"""Phase 4 — honest edge search: is ANY pre-registered, orthogonal-to-carry signal predictive
out of sample, stationary, and surviving the gate?

We do NOT screen all 58 features against all instruments (that is data mining). We pre-register a
small, economically-motivated set of single-feature hypotheses per instrument and run each through the
gate battery (carry-neutralized IC, half-sample H1/H2 decay, true refit-OOS CPCV). The bar is the
SECOND half (~0.10), not the inflated first half. Survivors are hypotheses to adversarially re-verify,
never auto-promotions.

Uses the PIT feature_df from ProductionEngine.initialize() (proven as-of-invariant in Phase 3) — no
25-minute walk-forward needed. Run: python scripts/signal_research.py
"""

from __future__ import annotations

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODEL_DIR = os.path.join(ROOT, "server", "model")

# Causal fixes ON (the honest configuration).
for _k, _v in {
    "ARC_CAUSAL_WINSORIZE": "1", "ARC_FORWARD_TARGET": "1", "ARC_HMM_FILTERED": "1",
    "ARC_BOUNDED_FFILL": "1", "ARC_CAUSAL_RSTAR_REGIME": "1", "ARC_REGIME_PER_SERIES": "1",
    "ARC_FEAT_PER_SERIES": "1", "ARC_REGIME_POINT_IN_TIME": "1", "ARC_PUBLICATION_LAG": "1",
    "ARC_CAUSAL_INTERP": "1",
}.items():
    os.environ.setdefault(_k, _v)

sys.path.insert(0, MODEL_DIR)
sys.path.insert(0, ROOT)

# Pre-registered, economically-motivated single-feature hypotheses (decision -> forward return).
# Rates are RECEIVER positions (gain when rates fall); fx is long USD; hard is sovereign spread.
CANDIDATES = {
    "front": ["Z_policy_gap", "Z_selic_star_gap", "Z_rstar_momentum", "Z_real_diff", "term_premium_slope"],
    "belly": ["Z_policy_gap", "Z_rstar_composite", "Z_term_premium", "Z_fiscal_premium", "Z_pb_momentum"],
    "long":  ["Z_fiscal_premium", "Z_debt_accel", "term_premium_5y", "Z_rstar_curve_gap", "Z_pb_momentum"],
    "fx":    ["reer_gap", "beer_misalignment", "val_fx", "Z_cip_basis", "Z_tot", "Z_iron_ore"],
    "hard":  ["Z_cds_br", "Z_fiscal_premium", "Z_bop", "Z_hy_spread", "sovereign_component"],
}


def main() -> None:
    import macro_risk_os_v2 as eng  # noqa: E402
    from arc.eval import forward_returns  # noqa: E402
    from arc.research import rank_signals  # noqa: E402

    print("[research] initializing engine (PIT features, no walk-forward)...", file=sys.stderr)
    e = eng.ProductionEngine(eng.DEFAULT_CONFIG)
    e.initialize()
    feat_df = e.feature_engine.feature_df
    ret_df = e.data_layer.ret_df
    horizon = eng.DEFAULT_CONFIG.get("prediction_horizon_months", 1)

    fwd = {inst: forward_returns(ret_df[inst], horizon) for inst in ret_df.columns}

    # Carry-neutralization must use each instrument's TRUE return-carry, not a mismatched feature.
    # front/belly/long carry_* = (DI_tenor - Selic) term carry (correct for rate receivers); carry_fx
    # = cupom FX carry (correct for the USD position). BUT carry_hard is the cupom cambial (FX), while
    # the `hard` sovereign-spread return earns the SPREAD carry (embi/10000/12). Using carry_hard would
    # neutralize against the wrong series (corr~0 with sovereign signals) and overstate the edge — the
    # defect that made hard/Z_cds_br look like alpha when it was spread carry. Use the spread carry.
    carry = {}
    for inst in ret_df.columns:
        if inst == "hard":
            embi = e.data_layer.monthly.get("embi_spread", None)
            if embi is not None and len(embi) > 12:
                carry["hard"] = embi / 10000.0 / 12.0
        elif f"carry_{inst}" in feat_df.columns:
            carry[inst] = feat_df[f"carry_{inst}"]

    out = rank_signals(CANDIDATES, feat_df, fwd, carry)

    report_path = os.path.join(eng.OUTPUT_DIR, "signal_research.json")
    with open(report_path, "w") as f:
        json.dump(out, f, indent=2, default=float)

    print("\n" + "=" * 84)
    print("PHASE 4 — HONEST EDGE SEARCH (pre-registered signals, gated)")
    print("=" * 84)
    print(f"  hypotheses tested = {out['n_hypotheses']}   survivors = {out['n_survivors']}   "
          f"(bar: carry-neutral IC>=0.05, 2nd-half IC>=0.03, decay<=0.15, refit-OOS>=0.03)")
    print(f"  {'inst':5s} {'feature':20s} {'n':>4s} {'IC':>7s} {'cnIC':>7s} {'H1':>7s} {'H2':>7s} "
          f"{'decay':>7s} {'OOSm':>7s} {'OOSmin':>7s}  verdict")
    print("  " + "-" * 92)
    for r in out["results"]:
        if r.get("n", 0) < 1 or "ic" not in r:
            print(f"  {r['instrument']:5s} {r['feature']:20s}  --  {'; '.join(r.get('reasons', []))}")
            continue
        v = "PASS" if r["passed"] else "fail: " + "; ".join(r["reasons"])
        print(f"  {r['instrument']:5s} {r['feature']:20s} {r['n']:>4d} {r['ic']:+.3f} "
              f"{r['carry_neutral_ic']:+.3f} {r['h1']:+.3f} {r['h2']:+.3f} {r['decay']:+.3f} "
              f"{r['refit_oos_mean']:+.3f} {r['refit_oos_min']:+.3f}  {v}")

    print("\n  SURVIVORS:" if out["survivors"] else "\n  NO SURVIVORS — no pre-registered signal clears the gate.")
    for r in out["survivors"]:
        print(f"    {r['instrument']}/{r['feature']}: cnIC={r['carry_neutral_ic']:+.3f} "
              f"H2={r['h2']:+.3f} refit-OOS={r['refit_oos_mean']:+.3f}")
    if out["n_survivors"]:
        print(f"\n  NOTE: {out['n_hypotheses']} hypotheses tested — survivors are candidates to "
              f"adversarially re-verify, NOT promotions. Expect ~{out['n_hypotheses']*0.05:.0f} false "
              f"positive(s) at the 5% level.")
    print(f"\n  report: {report_path}")


if __name__ == "__main__":
    main()
