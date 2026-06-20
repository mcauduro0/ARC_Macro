"""Promotion gate runner — does the overlay carry real alpha, or is it carry + leakage?

Runs ONE walk-forward backtest with the causal fixes ON (filtered HMM, bounded ffill, causal r*,
forward target, causal winsorize) and ARC_DUMP_DIAGNOSTICS=1, then feeds the per-instrument
(prediction, realized forward return, decision-time carry) panels and the overlay return stream into
``arc.eval.gate.promotion_report``. The gate deflates the Sharpe against the real trial count,
carry-neutralizes the IC, and compares the overlay to a carry-only benchmark.

Usage:
    python scripts/promotion_gate.py

Env:
    ARC_GATE_TRIALS   number of trials for Deflated Sharpe (default 30 — the audit's documented
                      re-scored tuning iterations on the same sample).
    ARC_GATE_SR_STD   across-trials Sharpe dispersion for DSR (default 1.0, the standard assumption).

Honest by construction: it prints whatever the run produces and a PASS/FAIL with explicit reasons.
A FAIL here is the expected, correct outcome if the apparent edge is carry — that is the point.
"""

from __future__ import annotations

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODEL_DIR = os.path.join(ROOT, "server", "model")

# Causal fixes ON; capture gate diagnostics. Set BEFORE importing the engine.
os.environ.setdefault("ARC_CAUSAL_WINSORIZE", "1")
os.environ.setdefault("ARC_FORWARD_TARGET", "1")
os.environ.setdefault("ARC_HMM_FILTERED", "1")
os.environ.setdefault("ARC_BOUNDED_FFILL", "1")
os.environ.setdefault("ARC_CAUSAL_RSTAR_REGIME", "1")
os.environ.setdefault("ARC_REGIME_PER_SERIES", "1")
os.environ.setdefault("ARC_FEAT_PER_SERIES", "1")
os.environ.setdefault("ARC_REGIME_POINT_IN_TIME", "1")
os.environ.setdefault("ARC_PUBLICATION_LAG", "1")
os.environ["ARC_DUMP_DIAGNOSTICS"] = "1"

sys.path.insert(0, MODEL_DIR)
sys.path.insert(0, ROOT)

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from arc.eval.gate import promotion_report  # noqa: E402


def _panels(diag: dict):
    """Build aligned (pred, realized, carry) panels [date x instrument] from the diagnostics dump."""
    pred, realized, carry = {}, {}, {}
    for inst, rows in diag.items():
        if not rows:
            continue
        s = pd.DataFrame(rows)
        s["date"] = pd.to_datetime(s["date"])
        s = s.set_index("date").sort_index()
        pred[inst] = s["pred"]
        realized[inst] = s["realized"]
        carry[inst] = s["carry"]
    return (pd.DataFrame(pred), pd.DataFrame(realized), pd.DataFrame(carry))


def main() -> None:
    import macro_risk_os_v2 as eng

    n_trials = int(os.environ.get("ARC_GATE_TRIALS", "30"))
    _sr_std_env = os.environ.get("ARC_GATE_SR_STD", "auto")  # 'auto' => Lo (2002) per-period Sharpe SE
    sr_std = None if _sr_std_env.lower() == "auto" else float(_sr_std_env)

    print("[gate] running walk-forward backtest with causal fixes ON ...", file=sys.stderr)
    harness = eng.BacktestHarness(eng.DEFAULT_CONFIG)
    harness.run()

    records = harness.results or []
    overlay_returns = np.array([r.get("overlay_return", 0.0) for r in records], dtype="float64")

    diag_path = os.path.join(eng.OUTPUT_DIR, "gate_diagnostics.json")
    if not os.path.exists(diag_path):
        raise RuntimeError(f"diagnostics not written at {diag_path}; backtest may have produced no steps")
    with open(diag_path) as f:
        diag = json.load(f)

    pred_panel, realized_panel, carry_panel = _panels(diag)
    # keep only instruments that actually have a carry signal (else carry-neutralization is vacuous)
    insts = [c for c in pred_panel.columns
             if c in carry_panel.columns and carry_panel[c].notna().sum() >= 12]
    dropped = [c for c in pred_panel.columns if c not in insts]
    if dropped:
        print(f"[gate] NOTE: instruments without a usable carry series (excluded): {dropped}", file=sys.stderr)

    verdict = promotion_report(
        pred_panel=pred_panel[insts],
        realized_panel=realized_panel[insts],
        carry_panel=carry_panel[insts],
        overlay_returns=overlay_returns,
        n_trials=n_trials,
        sr_std=sr_std,
    )

    # Refit-OOS CPCV (gate hardening): re-fit a ridge INSIDE each purged fold on the instrument's
    # actual features vs forward returns — a TRUE out-of-sample probe of period-concentration /
    # overfitting, unlike the post-hoc IC-stability CPCV in promotion_report (which inherits the
    # upstream fit). It still cannot detect a leak baked into the features themselves.
    refit_oos = {}
    try:
        from arc.eval import forward_returns, refit_oos_cpcv
        feat_df = harness.engine.feature_engine.feature_df
        ret_df = harness.engine.data_layer.ret_df
        feature_map = eng.EnsembleAlphaModels.FEATURE_MAP
        horizon = eng.DEFAULT_CONFIG.get("prediction_horizon_months", 1)
        for inst in insts:
            if inst not in ret_df.columns:
                continue
            feats = [f for f in feature_map.get(inst, []) if f in feat_df.columns]
            if len(feats) < 2:
                continue
            Xi = feat_df[feats]
            Xi, feats = eng._select_covered_features(Xi, 24)
            if Xi.shape[1] < 1:
                continue
            yi = forward_returns(ret_df[inst], horizon)
            common = Xi.index.intersection(yi.index)
            Xi, yi = Xi.reindex(common), yi.reindex(common)
            mask = ~(Xi.isna().any(axis=1) | yi.isna())
            Xi, yi = Xi[mask], yi[mask]
            if len(yi) >= 30:
                refit_oos[inst] = refit_oos_cpcv(Xi.values, yi.values)
    except Exception as e:
        print(f"[gate] refit-OOS CPCV skipped: {e}", file=sys.stderr)

    out = verdict.to_dict()
    out["refit_oos_cpcv"] = refit_oos
    out["meta"] = {
        "n_trials": n_trials, "sr_std": sr_std,
        "n_months": len(overlay_returns), "instruments": insts, "excluded": dropped,
        "toggles": {k: os.environ.get(k) for k in
                    ["ARC_CAUSAL_WINSORIZE", "ARC_FORWARD_TARGET", "ARC_HMM_FILTERED",
                     "ARC_BOUNDED_FFILL", "ARC_CAUSAL_RSTAR_REGIME", "ARC_REGIME_PER_SERIES",
                     "ARC_FEAT_PER_SERIES", "ARC_REGIME_POINT_IN_TIME", "ARC_PUBLICATION_LAG"]},
    }
    report_path = os.path.join(eng.OUTPUT_DIR, "promotion_gate_report.json")
    with open(report_path, "w") as f:
        json.dump(out, f, indent=2)

    # ---- human-readable summary ----
    ov, ca, agg = out["overlay"], out["carry_only"], out["aggregate"]
    print("\n" + "=" * 64)
    print("PROMOTION GATE — overlay vs carry, deflated")
    print("=" * 64)
    print(f"  months={out['meta']['n_months']}  trials(DSR)={n_trials}  instruments={insts}")
    print(f"  overlay   Sharpe(ann)={ov.get('sr_annual'):.2f}  PSR(>0)={ov.get('psr_vs_0'):.3f}  DSR={ov.get('dsr'):.3f}")
    print(f"  carry-only Sharpe(ann)={ca.get('sr_annual'):.2f}")
    print(f"  mean carry-neutralized IC={agg.get('mean_carry_neutral_ic'):.4f}  "
          f"t={agg.get('carry_neutral_ic_t'):.2f}  worst CPCV IC={agg.get('worst_cpcv_ic'):.3f}")
    print(f"  half-sample carry-neutral IC: H1(median)={agg.get('median_cn_ic_h1', float('nan')):.3f}  "
          f"H2(median)={agg.get('median_cn_ic_h2', float('nan')):.3f}  "
          f"decay={agg.get('median_cn_ic_decay', float('nan')):.3f}  (steep drop = contamination)")
    print("\n  per-instrument:")
    for inst, v in out["per_instrument"].items():
        ro = out.get("refit_oos_cpcv", {}).get(inst, {})
        ro_m, ro_lo = ro.get("mean", float("nan")), ro.get("min", float("nan"))
        hs = v.get("half_sample", {})
        print(f"    {inst:6s} n={v['n']:>3}  IC={v['ic']:+.3f}  carry-neutral IC={v['carry_neutral_ic']:+.3f}  "
              f"carry-only IC={v['carry_only_ic']:+.3f}  CPCV(mean/min)="
              f"{v['cpcv'].get('mean', float('nan')):+.3f}/{v['cpcv'].get('min', float('nan')):+.3f}  "
              f"H1/H2={hs.get('h1', float('nan')):+.3f}/{hs.get('h2', float('nan')):+.3f}  "
              f"refit-OOS(mean/min)={ro_m:+.3f}/{ro_lo:+.3f}")
    print(f"\n  VERDICT: {'PASS' if out['passed'] else 'FAIL'}")
    for r in out["reasons"]:
        print(f"    - {r}")
    print(f"\n  report: {report_path}")


if __name__ == "__main__":
    main()
