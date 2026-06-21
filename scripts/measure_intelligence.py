"""Phase 5 — the HONEST measurement: does intelligence sizing help the booked candidates?

Engine-touching entrypoint (imports the heavy monolith, so NOT run in CI; the pure ``arc.intelligence``
modules + their tests carry the CI guarantees). It applies the Phase 5 intelligence layer —
``uncertainty`` (predictive vol, split-conformal intervals, interval confidence), ``sizing``
(confidence-scaled, inverse-vol), and ``meta_labeling`` (predict whether the primary bet will be right) —
to the THREE booked sleeves (momentum_front, nowcast_long, fiscal_hard) and asks, honestly and DEFLATED,
whether any sizing variant beats FLAT causal sizing on the gate's own ruler (deflated Sharpe / DSR).

THE HONESTY LAW (this project's prime directive — "nao invente resultados"): this is MEASURED
infrastructure, NOT an alpha claim. The project has NO demonstrated edge beyond carry; the three sleeves
are CANDIDATES under forward paper. The likely honest outcome is "marginal / none", and we report exactly
that. Crucially, a sizing variant only "wins" if it beats FLAT on DEFLATED DSR by a meaningful margin
WITHOUT just adding leverage — Sharpe/DSR are leverage-invariant, so any win must be a genuine
risk-adjusted improvement, not more notional. Everything is strictly point-in-time (expanding/trailing
only): every input at t uses data with index <= t and NEVER index > t.

The FLAT baseline reproduces ``arc.research.signal_sleeve_returns`` bit-for-bit (asserted at runtime); each
variant is the SAME causal position re-scaled by a PIT confidence/vol multiplier, then run through the
IDENTICAL costed return calc, so any difference is the sizing overlay alone.

POINT-PRED + FEATURE CHOICES (documented plainly so the measurement is auditable):
  * Conformal point prediction = the CAUSAL expanding mean of the realized forward return, lagged one step
    (``fwd.expanding(min_periods=...).mean().shift(1)``) so the prediction at t uses only forward returns
    realized strictly BEFORE t. ``realized`` = the forward return itself. This is a deliberately naive,
    honest predictor: the conformal half-width then reflects the past dispersion of |realized - pred|, i.e.
    how wide the sleeve's forecast error has typically been. Narrower-than-typical intervals => higher
    interval_confidence => larger position (confidence-scaled).
  * Meta-label features (all strictly PIT, index <= t): the signed causal position level ``pos`` (the bet's
    direction & conviction), its magnitude ``|pos|`` (conviction only), and the trailing predictive vol of
    the instrument ``predictive_vol(rets)`` (the risk environment). meta_labels(pos, fwd) is the
    Lopez de Prado target (1.0 if the primary bet's sign matched the forward return, else 0.0); the
    expanding-window classifier predicts P(bet is right) which then scales the position.

Run:
  python scripts/measure_intelligence.py
  python scripts/measure_intelligence.py --conformal-alpha 0.1   # interval coverage knob (default 0.10)

Writes <engine OUTPUT_DIR>/measure_intelligence.json (per-edge, per-variant stats + deltas + verdicts).
The single-use forward holdout is NOT touched here — this is in-sample sizing measurement, not promotion.
"""

from __future__ import annotations

import argparse
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

# Per-edge honest multiple-testing count (same as scripts/score_both_edges.py + the sleeve scripts):
# momentum 45, nowcast 55 (cumulative rounds 1+2), fiscal pb_momentum 69 (cumulative through round 3).
# Keyed by spec['kind'] so each registry name maps to the right deflation bar for DSR.
N_TRIALS = {"momentum": 45, "nowcast": 55, "fiscal_momentum": 69}

# A variant must beat FLAT on DEFLATED DSR by at least this margin to be called a (tentative) improvement.
# Deliberately conservative — small DSR wiggles are noise, and the honesty law forbids over-claiming.
DSR_WIN_MARGIN = 0.05


def _costed_sleeve_returns(position, returns, *, cost_bps: float):
    """Reproduce arc.research.signal_sleeve_returns' return calc EXACTLY, but from an already-built
    (possibly re-scaled) PIT position rather than from a raw signal.

    sleeve[t] = position[t-1] * return[t]  -  |position[t-1] - position[t-2]| * cost.
    The position is decided last month (shift(1)) and earns this month's return; turnover is the change in
    the HELD position. This is the single return calc shared by FLAT and every sizing variant, so any
    difference between variants is the sizing overlay alone (no return-calc drift)."""
    import pandas as pd
    r = pd.Series(returns).dropna()
    pos = pd.Series(position).reindex(r.index)
    held = pos.shift(1)                      # decided last month, earns this month's return
    gross = held * r
    turnover = held.diff().abs()
    cost = turnover * (cost_bps / 10000.0)
    return (gross - cost).dropna()


def _avg_turnover(position, returns) -> float:
    """Mean monthly turnover (|held[t] - held[t-1]|) of the HELD position — the cost/churn footprint of a
    sizing variant, reported so a 'win' that is really just churn is visible."""
    import numpy as np
    import pandas as pd
    r = pd.Series(returns).dropna()
    pos = pd.Series(position).reindex(r.index)
    held = pos.shift(1)
    to = held.diff().abs().dropna()
    return float(to.mean()) if len(to) else float("nan")


def _conformal_point_pred(fwd, *, min_periods: int = 24):
    """CAUSAL point prediction of the forward return: expanding mean lagged one step so the value at t uses
    only forward returns realized strictly before t (no peeking at fwd[t]). Honest, naive predictor whose
    error dispersion the conformal interval then quantifies."""
    return fwd.expanding(min_periods=min_periods).mean().shift(1)


def measure_edge(name, spec, ret_df, monthly, horizon, *, conformal_alpha: float):
    """Measure FLAT vs the three sizing variants for one booked edge. Returns a dict (JSON-able) with
    per-variant stats, deltas-vs-FLAT, and an honest per-edge verdict. Pure consumption of the engine's
    PIT ret_df/monthly + the Phase 5 intelligence APIs; touches no holdout."""
    import numpy as np
    import pandas as pd

    from arc.autonomy import build_signal
    from arc.eval import forward_returns
    from arc.intelligence.meta_labeling import meta_label_proba, meta_labels
    from arc.intelligence.sizing import confidence_scaled_position, inverse_vol_position
    from arc.intelligence.uncertainty import (conformal_intervals, interval_confidence,
                                              predictive_vol)
    from arc.research import (causal_position, momentum_signal, signal_sleeve_returns, sleeve_stats)

    inst = spec["instrument"]
    kind = spec["kind"]
    n_trials = N_TRIALS[kind]
    cost_bps = float(spec.get("cost_bps", 2.0))
    z_window = int(spec.get("z_window", 12))
    clip_z = float(spec.get("clip_z", 2.0))

    if inst not in ret_df.columns:
        return {"strategy": name, "instrument": inst, "kind": kind,
                "status": f"SKIPPED: '{inst}' not in ret_df", "variants": {}}

    rets = ret_df[inst].dropna()
    fwd = forward_returns(rets, horizon)

    # Oriented PIT signal (None => derive price momentum from returns, per the spec's contract).
    signal = build_signal(spec, monthly)
    if signal is None:
        signal = momentum_signal(rets, int(spec.get("lookback", 3)))
    signal = pd.Series(signal)
    signal_aligned = signal.reindex(rets.index)

    # Base causal position in [-1, 1] (the SAME expanding z-score the sleeve uses).
    pos = causal_position(signal_aligned, z_window=z_window, clip_z=clip_z)

    # ---- FLAT baseline: MUST equal arc.research.signal_sleeve_returns bit-for-bit ----
    flat = _costed_sleeve_returns(pos, rets, cost_bps=cost_bps)
    flat_ref = signal_sleeve_returns(signal_aligned, rets, z_window=z_window, clip_z=clip_z,
                                     cost_bps=cost_bps)
    aligned = pd.concat([flat, flat_ref], axis=1, join="inner")
    if len(aligned) and not np.allclose(aligned.iloc[:, 0].values, aligned.iloc[:, 1].values,
                                        rtol=1e-9, atol=1e-12, equal_nan=True):
        raise AssertionError(f"[{name}] FLAT does not reproduce signal_sleeve_returns — return-calc drift")

    # ---- Predictive vol (causal trailing rolling std of the instrument returns) ----
    pvol = predictive_vol(rets)

    # ---- INVERSE-VOL: scale the base position toward a 10% annual vol target (causal, clipped) ----
    pos_iv = inverse_vol_position(pos, pvol, target_vol_ann=0.10)

    # ---- CONFIDENCE (vol): split-conformal interval width -> interval confidence -> scaled position ----
    point = _conformal_point_pred(fwd)
    ci = conformal_intervals(point, fwd, alpha=conformal_alpha)
    width = ci["width"]
    conf_vol = interval_confidence(width)
    pos_conf = confidence_scaled_position(pos, conf_vol)

    # ---- META: P(primary bet is right) from a causal expanding classifier -> scaled position ----
    labels = meta_labels(pos, fwd)
    feats = pd.DataFrame({
        "signal_level": pos,            # signed conviction (direction + size of the bet)
        "abs_signal": pos.abs(),        # conviction magnitude only
        "pred_vol": pvol,               # the risk environment at decision time
    })
    proba = meta_label_proba(feats, labels)
    pos_meta = confidence_scaled_position(pos, proba)

    variants = {
        "FLAT": pos,
        "INVERSE_VOL": pos_iv,
        "CONFIDENCE_VOL": pos_conf,
        "META": pos_meta,
    }

    out_variants = {}
    flat_stats = None
    for vname, vpos in variants.items():
        sl = _costed_sleeve_returns(vpos, rets, cost_bps=cost_bps)
        st = sleeve_stats(sl, n_trials=n_trials, vol_target_ann=0.10)
        rec = {
            "n": st["n"],
            "ann_ret": st["ann_ret"],
            "ann_vol": st["ann_vol"],
            "sharpe_ann": st["sharpe_ann"],
            "psr_vs_0": st["psr_vs_0"],
            "dsr": st["dsr"],
            "max_drawdown": st["max_drawdown"],
            "hit_rate": st["hit_rate"],
            "turnover": _avg_turnover(vpos, rets),
            "leverage_for_vol_target": st.get("leverage_for_vol_target", float("nan")),
        }
        if vname == "FLAT":
            flat_stats = rec
        out_variants[vname] = rec

    # ---- Deltas vs FLAT + honest per-variant / per-edge verdict ----
    def _d(a, b):
        if a is None or b is None or any(np.isnan([a, b])):
            return float("nan")
        return float(a - b)

    best_variant, best_d_dsr = None, float("-inf")
    for vname, rec in out_variants.items():
        if vname == "FLAT":
            rec["delta_vs_flat"] = {k: 0.0 for k in ("sharpe_ann", "dsr", "max_drawdown", "hit_rate")}
            continue
        d = {
            "sharpe_ann": _d(rec["sharpe_ann"], flat_stats["sharpe_ann"]),
            "dsr": _d(rec["dsr"], flat_stats["dsr"]),
            "max_drawdown": _d(rec["max_drawdown"], flat_stats["max_drawdown"]),
            "hit_rate": _d(rec["hit_rate"], flat_stats["hit_rate"]),
        }
        rec["delta_vs_flat"] = d
        if not np.isnan(d["dsr"]) and d["dsr"] > best_d_dsr:
            best_d_dsr, best_variant = d["dsr"], vname

    # A win = beats FLAT on deflated DSR by >= margin. (DSR is leverage-invariant, so this cannot be gamed
    # by adding notional — the only way to win is a genuine risk-adjusted improvement.)
    win = best_variant is not None and best_d_dsr >= DSR_WIN_MARGIN
    if win:
        verdict = (f"TENTATIVE IMPROVEMENT: {best_variant} beats FLAT on deflated DSR by "
                   f"+{best_d_dsr:.3f} (>= {DSR_WIN_MARGIN}). In-sample only; confirm on forward paper.")
    elif best_variant is not None:
        verdict = (f"NO MEANINGFUL IMPROVEMENT: best variant {best_variant} delta-DSR "
                   f"{best_d_dsr:+.3f} < {DSR_WIN_MARGIN} margin — sizing does not beat FLAT here.")
    else:
        verdict = "INCONCLUSIVE: insufficient data to deflate (DSR NaN)."

    return {
        "strategy": name,
        "instrument": inst,
        "kind": kind,
        "n_trials": n_trials,
        "status": "OK",
        "variants": out_variants,
        "best_variant": best_variant,
        "best_delta_dsr": (None if best_variant is None else best_d_dsr),
        "win": bool(win),
        "verdict": verdict,
    }


def _print_edge_table(res) -> None:
    """Per-edge variant table: variant | Sharpe | DSR | maxDD | hit | turnover, plus a delta-vs-FLAT line."""
    name = res["strategy"]
    print("\n" + "=" * 96)
    print(f"EDGE: {name}  (instrument={res['instrument']}, kind={res['kind']}, "
          f"n_trials={res.get('n_trials', '?')})")
    print("=" * 96)
    if res["status"] != "OK":
        print(f"  {res['status']}")
        return
    cols = f"  {'variant':14s} {'Sharpe':>8s} {'DSR':>7s} {'maxDD':>8s} {'hit':>6s} {'turnover':>9s} {'lev@10%':>8s}"
    print(cols)
    print("  " + "-" * 92)
    for vname, rec in res["variants"].items():
        print(f"  {vname:14s} {rec['sharpe_ann']:>+8.3f} {rec['dsr']:>7.3f} "
              f"{rec['max_drawdown']*100:>+7.1f}% {rec['hit_rate']*100:>5.0f}% "
              f"{rec['turnover']:>9.3f} {rec['leverage_for_vol_target']:>7.1f}x")
    print("  " + "-" * 92)
    print(f"  {'DELTA vs FLAT':14s} {'dSharpe':>8s} {'dDSR':>7s} {'dMaxDD':>8s} {'dHit':>6s}")
    for vname, rec in res["variants"].items():
        if vname == "FLAT":
            continue
        d = rec["delta_vs_flat"]
        print(f"  {vname:14s} {d['sharpe_ann']:>+8.3f} {d['dsr']:>+7.3f} "
              f"{d['max_drawdown']*100:>+7.1f}% {d['hit_rate']*100:>+5.0f}%")
    print(f"\n  VERDICT: {res['verdict']}")


def main() -> None:
    import macro_risk_os_v2 as eng

    from arc.autonomy import SPECS

    ap = argparse.ArgumentParser(
        description="Phase 5 honest measurement: does intelligence sizing beat FLAT on the booked edges?")
    ap.add_argument("--conformal-alpha", type=float, default=0.10,
                    help="miscoverage for split-conformal intervals (default 0.10 => 90%% intervals)")
    args = ap.parse_args()

    print("[measure-intelligence] initializing engine (PIT returns)...", file=sys.stderr)
    e = eng.ProductionEngine(eng.DEFAULT_CONFIG)
    e.initialize()
    ret_df = e.data_layer.ret_df
    monthly = e.data_layer.monthly
    horizon = int(eng.DEFAULT_CONFIG.get("prediction_horizon_months", 1))
    out_dir = eng.OUTPUT_DIR

    print("\n" + "#" * 96)
    print("PHASE 5 — INTELLIGENCE SIZING MEASUREMENT (causal, DEFLATED, in-sample, NOT an alpha claim)")
    print(f"  horizon={horizon}m | conformal_alpha={args.conformal_alpha} | win bar = +{DSR_WIN_MARGIN} "
          f"deflated DSR over FLAT (leverage-invariant)")
    print("  variants: FLAT (baseline) | INVERSE_VOL | CONFIDENCE_VOL (conformal width) | META (meta-label P)")
    print("#" * 96)

    results = []
    for name, spec in SPECS.items():
        try:
            res = measure_edge(name, spec, ret_df, monthly, horizon,
                               conformal_alpha=args.conformal_alpha)
        except Exception as exc:  # noqa: BLE001 — report the failure honestly, keep measuring the rest
            res = {"strategy": name, "instrument": spec.get("instrument"), "kind": spec.get("kind"),
                   "status": f"ERROR: {type(exc).__name__}: {exc}", "variants": {}}
            print(f"[measure-intelligence] {name} ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        results.append(res)
        _print_edge_table(res)

    # ---- Overall honest verdict ----
    ok = [r for r in results if r["status"] == "OK"]
    wins = [r for r in ok if r.get("win")]
    print("\n" + "#" * 96)
    print("OVERALL VERDICT (HONEST)")
    print("#" * 96)
    if not ok:
        overall = "INCONCLUSIVE: no edge could be measured (data/import issues)."
    elif not wins:
        overall = ("NO / MARGINAL: no sizing variant beats FLAT on deflated DSR by the +"
                   f"{DSR_WIN_MARGIN} margin on any booked edge. Confidence/inverse-vol/meta-label sizing "
                   "does NOT add measured risk-adjusted value here (the expected, honest outcome). FLAT "
                   "causal sizing remains the baseline; intelligence sizing is not promoted.")
    else:
        names = ", ".join(f"{r['strategy']}({r['best_variant']} dDSR {r['best_delta_dsr']:+.3f})"
                          for r in wins)
        overall = ("TENTATIVE, IN-SAMPLE ONLY: sizing beat FLAT on deflated DSR for: " + names +
                   ". This is NOT an alpha claim — it is in-sample and leverage-invariant by construction; "
                   "it must survive the forward single-use holdout before any promotion. Treat as a "
                   "hypothesis to carry into forward paper, not a result.")
    print("  " + overall)
    print("  REMINDER: DSR is leverage-invariant, so none of these 'wins' come from adding notional; the "
          "single-use forward holdout was NOT touched (this is in-sample sizing measurement).")

    payload = {
        "phase": "5_intelligence_sizing",
        "honest_note": ("MEASURED infrastructure, not an alpha claim. In-sample sizing comparison vs FLAT "
                        "causal baseline; deflated DSR (leverage-invariant). Forward holdout untouched."),
        "horizon_months": horizon,
        "conformal_alpha": args.conformal_alpha,
        "dsr_win_margin": DSR_WIN_MARGIN,
        "n_trials_by_kind": N_TRIALS,
        "point_pred": "causal expanding-mean of forward return, lagged 1 (fwd.expanding().mean().shift(1))",
        "meta_features": ["signal_level (signed pos)", "abs_signal (|pos|)", "pred_vol (trailing)"],
        "variants": ["FLAT", "INVERSE_VOL", "CONFIDENCE_VOL", "META"],
        "edges": results,
        "overall_verdict": overall,
    }
    out_path = os.path.join(out_dir, "measure_intelligence.json")
    os.makedirs(out_dir, exist_ok=True)
    with open(out_path, "w", encoding="ascii") as f:
        json.dump(payload, f, indent=2, default=float)
    print(f"\n[measure-intelligence] wrote {out_path}")


if __name__ == "__main__":
    main()
