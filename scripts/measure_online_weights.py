"""Phase 5 — the HONEST measurement: do online/adaptive COMBINATION weights beat equal-weight?

Engine-touching entrypoint (imports the heavy monolith, so NOT run in CI; the pure
``arc.intelligence.online_weights`` module + its tests carry the CI guarantees). It builds the THREE booked
candidate sleeves' FLAT causal return streams (momentum_front, nowcast_long, fiscal_hard), aligns them into a
monthly panel, and combines them into ONE book under three weighting schemes:

  * EQUAL                 — flat 1/3 each (the baseline).
  * EWMA_PERF             — ``ewma_performance_weights`` (causal EW Sharpe-proxy weights).
  * INVERSE_VARIANCE      — ``rolling_inverse_variance_weights`` (causal risk-parity-ish weights).

The combined-book return at month t is ``sum_c weights[t, c] * sleeve_return[t, c]`` with weights that are
STRICTLY causal (decided from sleeve returns before t). It reports ``sleeve_stats`` (Sharpe / DSR / maxDD)
for each combined book, DEFLATED, and an HONEST verdict.

THE HONESTY LAW (this project's prime directive — "nao invente resultados"): this is MEASURED
infrastructure, NOT an alpha claim. The project has NO demonstrated edge beyond carry; the three sleeves are
CANDIDATES under forward paper (0 out-of-time months exist today). The likely honest outcome is "marginal /
none", and we report exactly that. An online scheme only "wins" if it beats EQUAL on DEFLATED DSR by a
meaningful margin (>= +0.05) WITHOUT just adding leverage — Sharpe/DSR are leverage-invariant, so any win
must be a genuine risk-adjusted improvement, not more notional. Everything is strictly point-in-time.

SCOPE: this measures online *combination weighting* of the fixed 3-sleeve set. Online FEATURE selection is
OUT OF SCOPE and DEFERRED (noted in the JSON payload).

Run:
  python scripts/measure_online_weights.py
  python scripts/measure_online_weights.py --halflife 12 --window 12 --floor 0.0

Writes <engine OUTPUT_DIR>/measure_online_weights.json. The single-use forward holdout is NOT touched here.
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

# A scheme must beat EQUAL on DEFLATED DSR by at least this margin to be called a (tentative) improvement.
DSR_WIN_MARGIN = 0.05

# Honest multiple-testing count for the COMBINED book. We are choosing among a small number of combination
# schemes for the SAME three sleeves; n_trials = number of sleeves combined (3) is the conservative,
# stated bar. (We also report it explicitly so the deflation basis is auditable.)
N_TRIALS_COMBINED = 3


def _build_sleeve_panel(ret_df, monthly):
    """Build the three booked sleeves' FLAT causal return streams and align them into one monthly panel.

    Each column reproduces ``arc.research.signal_sleeve_returns`` for the booked spec (momentum derives
    price momentum from the return stream; the others use ``build_signal``). Returns (panel, per-sleeve
    diagnostics). The panel is the OUTER-aligned union of months; NaN marks a sleeve not tradable that
    month (so the combiner equal-weights only the present sleeves there)."""
    import pandas as pd

    from arc.autonomy import SPECS, build_signal
    from arc.research import momentum_signal, signal_sleeve_returns

    streams = {}
    diag = {}
    for name, spec in SPECS.items():
        inst = spec["instrument"]
        if inst not in ret_df.columns:
            diag[name] = {"status": f"SKIPPED: '{inst}' not in ret_df", "instrument": inst}
            continue
        rets = ret_df[inst].dropna()
        signal = build_signal(spec, monthly)
        if signal is None:  # momentum kind -> derive price momentum from returns
            signal = momentum_signal(rets, int(spec.get("lookback", 3)))
        signal = pd.Series(signal).reindex(rets.index)
        sl = signal_sleeve_returns(
            signal, rets,
            z_window=int(spec.get("z_window", 12)),
            clip_z=float(spec.get("clip_z", 2.0)),
            cost_bps=float(spec.get("cost_bps", 2.0)),
        )
        streams[name] = sl
        diag[name] = {"status": "OK", "instrument": inst, "n": int(len(sl))}

    if not streams:
        return None, diag
    panel = pd.DataFrame(streams).sort_index()
    return panel, diag


def _combined_returns(panel, weights):
    """Causal combined-book return: sum_c weights[t,c] * panel[t,c], over the columns present at t.

    ``weights`` is strictly causal (row t uses only sleeve returns before t). We treat a NaN sleeve return
    as 0 contribution at rows where the weight is also NaN (absent sleeve) so the present sleeves' weights
    (which sum to 1) define the book. Rows with no defined weights are dropped."""
    import numpy as np
    import pandas as pd

    w = weights.reindex_like(panel)
    contrib = (w * panel)
    # Where a weight is defined (sleeve present & weighted) the product is the contribution; treat a
    # defined-weight / NaN-return pair as 0 (cannot happen by construction — weight is NaN if return is).
    out = contrib.sum(axis=1, min_count=1)
    # Keep only rows where at least one weight was defined.
    has_weight = w.notna().any(axis=1)
    out = out.where(has_weight)
    return pd.Series(out, index=panel.index).dropna()


def measure(ret_df, monthly, *, halflife, window, min_periods, floor):
    """Build the panel, form EQUAL / EWMA_PERF / INVERSE_VARIANCE combined books, and compare them DEFLATED.

    Returns a JSON-able dict with per-scheme stats, deltas-vs-EQUAL, the best scheme, and an honest
    verdict. Pure consumption of the engine's PIT ret_df/monthly + the online_weights APIs; no holdout."""
    import numpy as np
    import pandas as pd

    from arc.intelligence.online_weights import (
        ewma_performance_weights,
        rolling_inverse_variance_weights,
    )
    from arc.research import sleeve_stats

    panel, diag = _build_sleeve_panel(ret_df, monthly)
    if panel is None or panel.shape[1] == 0:
        return {"status": "INCONCLUSIVE: no booked sleeve could be built", "sleeves": diag}

    n_sleeves = panel.shape[1]

    # EQUAL weights: 1/k across the columns present at each row (the honest baseline; itself causal/static).
    present = panel.notna()
    eq_w = present.div(present.sum(axis=1).replace(0, np.nan), axis=0)

    ewma_w = ewma_performance_weights(panel, halflife=halflife, min_periods=min_periods, floor=floor)
    iv_w = rolling_inverse_variance_weights(panel, window=window, min_periods=min_periods)

    schemes = {
        "EQUAL": eq_w,
        "EWMA_PERF": ewma_w,
        "INVERSE_VARIANCE": iv_w,
    }

    out_schemes = {}
    equal_stats = None
    for sname, w in schemes.items():
        book = _combined_returns(panel, w)
        st = sleeve_stats(book, n_trials=N_TRIALS_COMBINED, vol_target_ann=0.10)
        # Mean per-row turnover of the WEIGHT vector (how much the scheme churns the blend itself).
        wt_turn = float(w.diff().abs().sum(axis=1).dropna().mean()) if len(w) else float("nan")
        rec = {
            "n": st["n"],
            "ann_ret": st["ann_ret"],
            "ann_vol": st["ann_vol"],
            "sharpe_ann": st["sharpe_ann"],
            "psr_vs_0": st["psr_vs_0"],
            "dsr": st["dsr"],
            "max_drawdown": st["max_drawdown"],
            "hit_rate": st["hit_rate"],
            "weight_turnover": wt_turn,
            "leverage_for_vol_target": st.get("leverage_for_vol_target", float("nan")),
        }
        if sname == "EQUAL":
            equal_stats = rec
        out_schemes[sname] = rec

    def _d(a, b):
        if a is None or b is None or any(np.isnan([a, b])):
            return float("nan")
        return float(a - b)

    best_scheme, best_d_dsr = None, float("-inf")
    for sname, rec in out_schemes.items():
        if sname == "EQUAL":
            rec["delta_vs_equal"] = {k: 0.0 for k in ("sharpe_ann", "dsr", "max_drawdown", "hit_rate")}
            continue
        d = {
            "sharpe_ann": _d(rec["sharpe_ann"], equal_stats["sharpe_ann"]),
            "dsr": _d(rec["dsr"], equal_stats["dsr"]),
            "max_drawdown": _d(rec["max_drawdown"], equal_stats["max_drawdown"]),
            "hit_rate": _d(rec["hit_rate"], equal_stats["hit_rate"]),
        }
        rec["delta_vs_equal"] = d
        if not np.isnan(d["dsr"]) and d["dsr"] > best_d_dsr:
            best_d_dsr, best_scheme = d["dsr"], sname

    # A win = beats EQUAL on deflated DSR by >= margin. DSR is leverage-invariant, so the only way to win is
    # a genuine risk-adjusted improvement (NOT more notional).
    win = best_scheme is not None and best_d_dsr >= DSR_WIN_MARGIN
    if win:
        verdict = (
            f"TENTATIVE IMPROVEMENT (in-sample): {best_scheme} beats EQUAL on deflated DSR by "
            f"+{best_d_dsr:.3f} (>= {DSR_WIN_MARGIN}), leverage-invariant. NOT an alpha claim; confirm on "
            "forward paper before any promotion."
        )
    elif best_scheme is not None:
        verdict = (
            f"NO MEANINGFUL IMPROVEMENT: best online scheme {best_scheme} delta-DSR {best_d_dsr:+.3f} "
            f"< {DSR_WIN_MARGIN} margin over EQUAL. Online combination weights do NOT add measured "
            "risk-adjusted value here (the expected, honest outcome). EQUAL weight remains the baseline."
        )
    else:
        verdict = "INCONCLUSIVE: insufficient data to deflate (DSR NaN)."

    return {
        "status": "OK",
        "n_sleeves": n_sleeves,
        "sleeve_names": list(panel.columns),
        "panel_months": int(panel.shape[0]),
        "n_trials_combined": N_TRIALS_COMBINED,
        "params": {"halflife": halflife, "window": window, "min_periods": min_periods, "floor": floor},
        "sleeves": diag,
        "schemes": out_schemes,
        "best_scheme": best_scheme,
        "best_delta_dsr": (None if best_scheme is None else best_d_dsr),
        "win": bool(win),
        "verdict": verdict,
    }


def _print_table(res) -> None:
    print("\n" + "#" * 96)
    print("PHASE 5 — ONLINE/ADAPTIVE COMBINATION WEIGHTS (causal, DEFLATED, in-sample, NOT an alpha claim)")
    print("#" * 96)
    if res["status"] != "OK":
        print(f"  {res['status']}")
        return
    p = res["params"]
    print(f"  sleeves={res['sleeve_names']}  months={res['panel_months']}  "
          f"n_trials={res['n_trials_combined']}  halflife={p['halflife']}  window={p['window']}  "
          f"floor={p['floor']}  win bar = +{DSR_WIN_MARGIN} deflated DSR over EQUAL (leverage-invariant)")
    print("  " + "-" * 92)
    hdr = (f"  {'scheme':18s} {'Sharpe':>8s} {'DSR':>7s} {'maxDD':>8s} {'hit':>6s} "
           f"{'wTurn':>7s} {'lev@10%':>8s}")
    print(hdr)
    print("  " + "-" * 92)
    for sname, rec in res["schemes"].items():
        print(f"  {sname:18s} {rec['sharpe_ann']:>+8.3f} {rec['dsr']:>7.3f} "
              f"{rec['max_drawdown']*100:>+7.1f}% {rec['hit_rate']*100:>5.0f}% "
              f"{rec['weight_turnover']:>7.3f} {rec['leverage_for_vol_target']:>7.1f}x")
    print("  " + "-" * 92)
    print(f"  {'DELTA vs EQUAL':18s} {'dSharpe':>8s} {'dDSR':>7s} {'dMaxDD':>8s} {'dHit':>6s}")
    for sname, rec in res["schemes"].items():
        if sname == "EQUAL":
            continue
        d = rec["delta_vs_equal"]
        print(f"  {sname:18s} {d['sharpe_ann']:>+8.3f} {d['dsr']:>+7.3f} "
              f"{d['max_drawdown']*100:>+7.1f}% {d['hit_rate']*100:>+5.0f}%")
    print(f"\n  VERDICT: {res['verdict']}")


def main() -> None:
    import macro_risk_os_v2 as eng

    ap = argparse.ArgumentParser(
        description="Phase 5 honest measurement: do online combination weights beat EQUAL on the book?")
    ap.add_argument("--halflife", type=int, default=12, help="EWMA halflife (months) for performance weights")
    ap.add_argument("--window", type=int, default=12, help="trailing window (months) for inverse-variance")
    ap.add_argument("--min-periods", type=int, default=12, help="min history before a scheme weight is defined")
    ap.add_argument("--floor", type=float, default=0.0, help="lower clip on EWMA pre-normalization weights")
    args = ap.parse_args()

    print("[measure-online-weights] initializing engine (PIT returns)...", file=sys.stderr)
    e = eng.ProductionEngine(eng.DEFAULT_CONFIG)
    e.initialize()
    ret_df = e.data_layer.ret_df
    monthly = e.data_layer.monthly
    out_dir = eng.OUTPUT_DIR

    res = measure(
        ret_df, monthly,
        halflife=args.halflife, window=args.window,
        min_periods=args.min_periods, floor=args.floor,
    )
    _print_table(res)

    print("\n  REMINDER: DSR is leverage-invariant, so a 'win' cannot come from adding notional; the "
          "single-use forward holdout was NOT touched (this is in-sample combination measurement). Online "
          "FEATURE selection is OUT OF SCOPE / DEFERRED.")

    payload = {
        "phase": "5_online_combination_weights",
        "honest_note": (
            "MEASURED infrastructure, not an alpha claim. In-sample combination comparison vs EQUAL-weight "
            "baseline; deflated DSR (leverage-invariant). Forward holdout untouched. Online FEATURE "
            "selection is out of scope / deferred."
        ),
        "dsr_win_margin": DSR_WIN_MARGIN,
        "schemes": ["EQUAL", "EWMA_PERF", "INVERSE_VARIANCE"],
        "deferred": "online feature selection (adaptively choosing model inputs) is NOT implemented here",
        "result": res,
        "overall_verdict": res.get("verdict", res.get("status")),
    }
    out_path = os.path.join(out_dir, "measure_online_weights.json")
    os.makedirs(out_dir, exist_ok=True)
    with open(out_path, "w", encoding="ascii") as f:
        json.dump(payload, f, indent=2, default=float)
    print(f"\n[measure-online-weights] wrote {out_path}")


if __name__ == "__main__":
    main()
