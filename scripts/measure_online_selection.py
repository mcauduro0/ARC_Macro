"""Phase 5 (deferred item) — the HONEST measurement: does ONLINE feature selection beat BATCH?

The engine does BATCH feature selection (fit on the full sample, freeze the chosen set). This script asks,
causally and deflated, whether re-selecting features ONLINE (rolling, point-in-time) does any better in a
simple predict-then-IC sense on a real forward target.

Engine-touching entrypoint (imports the heavy monolith, so NOT run in CI; the pure
``arc.intelligence.online_selection`` module + its tests carry the CI guarantees). It pulls the engine's PIT
feature panel ``feat_df`` and a FORWARD target (``forward_returns(ret_df['long'])`` by default), builds a
causal combined signal from a SELECTED feature set under each regime, and compares:

  * BATCH    — full-sample ElasticNet importance, top-k features chosen ONCE; that fixed set is used at every
               t (this mirrors the engine's batch selection; note it is technically in-sample-chosen, the
               optimistic baseline online has to beat).
  * ONLINE   — ``rolling_elasticnet_importance`` -> ``online_selected_mask`` top-k; the selected SET varies
               through time, each row chosen from data strictly before t (no leakage).
  * ONLINE_STABILITY — ``rolling_stability_selection`` -> threshold mask; bootstrap-stable set per t.

For each regime the combined signal at t is the EQUAL-WEIGHT average of the (causal, expanding-z) selected
features (oriented by the sign of their batch/rolling coefficient so "higher signal => higher forward
return"). We report a CARRY-NEUTRAL IC (Spearman of the signal vs the carry-residualized forward target),
the half-sample H1/H2 ICs (decay check), and a DEFLATED note. HONEST verdict: does online beat batch? The
expected, honest outcome is MARGINAL / NULL — online selection adds turnover and estimation noise, and any
IC gain must clear the deflation bar to mean anything.

THE HONESTY LAW (this project's prime directive — "nao invente resultados"): MEASURED infrastructure, NOT an
alpha claim. No demonstrated edge beyond carry. The single-use forward holdout is NOT touched here.

Run:
  python scripts/measure_online_selection.py
  python scripts/measure_online_selection.py --instrument long --top-k 5 --window 60 --min-train 36

Writes <engine OUTPUT_DIR>/measure_online_selection.json.
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

# An online scheme must beat BATCH on carry-neutral IC by at least this margin (after a deflation haircut)
# to be called even a TENTATIVE improvement. Online selection is the harder claim, so the bar is meaningful.
IC_WIN_MARGIN = 0.03


def _expanding_z(s, *, min_periods=24):
    """Strictly causal expanding z-score (index <= t only)."""
    import numpy as np
    s = s.astype("float64")
    mu = s.expanding(min_periods=min_periods).mean()
    sd = s.expanding(min_periods=min_periods).std(ddof=1).replace(0.0, np.nan)
    return (s - mu) / sd


def _carry_residualize(fwd, carry):
    """Residualize the forward target on carry (causal expanding OLS slope) -> carry-neutral target.

    At each t we regress fwd on carry using ONLY data with index <= t (expanding), then subtract the fitted
    carry component. If no carry series is available the target is returned demeaned (expanding). This is the
    same spirit as the project's carry-neutral gate: remove the part of the forward return explained by
    carry so the IC measures information BEYOND carry."""
    import numpy as np
    import pandas as pd

    fwd = pd.Series(fwd, dtype="float64")
    if carry is None:
        mu = fwd.expanding(min_periods=24).mean()
        return fwd - mu

    c = pd.Series(carry, dtype="float64").reindex(fwd.index)
    df = pd.concat([fwd.rename("y"), c.rename("x")], axis=1)
    resid = pd.Series(index=fwd.index, dtype="float64")
    # Expanding (causal) simple regression slope/intercept; residual at t uses params from data <= t.
    for i in range(len(df)):
        sub = df.iloc[: i + 1].dropna()
        if len(sub) < 24 or not np.isfinite(df.iloc[i]["y"]):
            continue
        x = sub["x"].to_numpy()
        y = sub["y"].to_numpy()
        vx = x.var()
        if not np.isfinite(vx) or vx <= 0:
            resid.iloc[i] = df.iloc[i]["y"] - y.mean()
            continue
        beta = np.cov(x, y, ddof=0)[0, 1] / vx
        alpha = y.mean() - beta * x.mean()
        xi = df.iloc[i]["x"]
        if not np.isfinite(xi):
            resid.iloc[i] = df.iloc[i]["y"] - y.mean()
        else:
            resid.iloc[i] = df.iloc[i]["y"] - (alpha + beta * xi)
    return resid


def _spearman_ic(signal, target):
    """Spearman rank IC between an aligned (signal, target); NaN if too few overlapping points."""
    import numpy as np
    import pandas as pd
    from scipy.stats import spearmanr

    df = pd.concat([pd.Series(signal), pd.Series(target)], axis=1).dropna()
    if len(df) < 12:
        return float("nan"), int(len(df))
    rho, _p = spearmanr(df.iloc[:, 0], df.iloc[:, 1])
    return (float(rho) if np.isfinite(rho) else float("nan")), int(len(df))


def _combined_signal_from_mask(feat_z, mask, signs):
    """Equal-weight causal combined signal from a per-t boolean selected mask and per-feature signs.

    feat_z : DataFrame of causal expanding-z features (index x feature).
    mask   : per-t bool DataFrame (same shape) — which features are selected at t.
    signs  : per-t signed DataFrame (or a single Series broadcast) giving the orientation (+/-1) to apply so
             each selected feature points the same way as the forward return. The signal at t is the mean of
             (sign * z) over the selected features at t; rows with no selection are NaN."""
    import numpy as np
    import pandas as pd

    z = feat_z.reindex_like(mask)
    oriented = z * signs
    sel = oriented.where(mask)
    sig = sel.mean(axis=1, skipna=True)
    cnt = mask.sum(axis=1)
    sig = sig.where(cnt > 0)
    return pd.Series(sig, index=mask.index)


def _half_sample_ic(signal, target):
    """H1/H2 carry-neutral IC on the two contiguous halves of the OVERLAP (decay check)."""
    import pandas as pd
    df = pd.concat([pd.Series(signal).rename("s"), pd.Series(target).rename("t")], axis=1).dropna()
    if len(df) < 24:
        return float("nan"), float("nan")
    mid = len(df) // 2
    h1, _ = _spearman_ic(df["s"].iloc[:mid], df["t"].iloc[:mid])
    h2, _ = _spearman_ic(df["s"].iloc[mid:], df["t"].iloc[mid:])
    return h1, h2


def measure(feat_df, ret_df, *, instrument, top_k, window, min_train, l1_ratio, n_bootstrap, stab_threshold,
            horizon):
    """Build BATCH / ONLINE / ONLINE_STABILITY combined signals and compare carry-neutral IC, deflated.

    Pure consumption of the engine's PIT feat_df/ret_df + the online_selection APIs; no holdout touched."""
    import numpy as np
    import pandas as pd

    from arc.eval import forward_returns
    from arc.intelligence.online_selection import (
        online_selected_mask,
        rolling_elasticnet_importance,
        rolling_stability_selection,
    )

    if instrument not in ret_df.columns:
        return {"status": f"INCONCLUSIVE: instrument '{instrument}' not in ret_df ({list(ret_df.columns)})"}

    idx = feat_df.index
    fwd = forward_returns(ret_df[instrument], horizon).reindex(idx)

    # Candidate feature universe: numeric, reasonably-populated columns; EXCLUDE the instrument's own carry
    # (we carry-neutralize against it, so it must not be a selectable feature) and any all-NaN columns.
    carry_col = f"carry_{instrument}"
    carry = feat_df[carry_col] if carry_col in feat_df.columns else None

    num = feat_df.select_dtypes(include=[np.number]).copy()
    drop_cols = [c for c in num.columns if c.startswith("carry_")]
    num = num.drop(columns=drop_cols, errors="ignore")
    # keep columns with enough coverage to be usable as features
    cover = num.notna().mean()
    keep = cover[cover >= 0.5].index.tolist()
    num = num[keep]
    # Cap the universe for tractability (top by coverage) so the rolling fits stay cheap & stable.
    if num.shape[1] > 30:
        num = num[cover[keep].sort_values(ascending=False).index[:30]]
    feat_universe = list(num.columns)
    if len(feat_universe) < 3:
        return {"status": f"INCONCLUSIVE: too few usable features ({len(feat_universe)})"}

    # Causal expanding-z of every candidate feature (the building block of every combined signal).
    feat_z = pd.DataFrame({c: _expanding_z(num[c]) for c in feat_universe}, index=idx)

    # Carry-neutral target (information beyond carry).
    cn_target = _carry_residualize(fwd, carry)

    # ---- BATCH selection: full-sample ElasticNet importance, top-k, ONE fixed set (the engine's mode) ----
    # (Optimistic baseline: it sees the whole sample to pick its set.)
    from arc.intelligence.online_selection import _coef_elasticnet, _standardize_train  # type: ignore

    batch_df = pd.concat([feat_z, cn_target.rename("__y__")], axis=1).dropna()
    batch_info = {}
    if len(batch_df) < max(min_train, 24):
        return {"status": "INCONCLUSIVE: not enough complete rows for batch fit"}
    Xb = batch_df[feat_universe].to_numpy()
    yb = batch_df["__y__"].to_numpy()
    Xs, ys, _mu, _sd, kp = _standardize_train(Xb, yb)
    batch_imp = np.where(kp, _coef_elasticnet(Xs, ys, l1_ratio=l1_ratio, use_cv=True), 0.0)
    batch_imp_s = pd.Series(batch_imp, index=feat_universe)
    # Batch signs: orient each feature by the sign of its full-sample coefficient.
    # (re-fit once to recover signed coef; _coef_elasticnet returns |coef|, so refit for the sign)
    batch_signed = _batch_signed_coef(Xs, ys, l1_ratio=l1_ratio)
    batch_signs = pd.Series(np.sign(np.where(np.abs(batch_signed) > 0, batch_signed, 1.0)), index=feat_universe)
    batch_top = batch_imp_s.sort_values(ascending=False).head(top_k).index.tolist()
    batch_info = {"selected": batch_top, "importance": {k: float(batch_imp_s[k]) for k in batch_top}}

    # Batch combined signal: fixed set, fixed signs, at every t.
    batch_mask = pd.DataFrame(False, index=idx, columns=feat_universe)
    batch_mask.loc[:, batch_top] = feat_z[batch_top].notna()  # only "select" where the feature exists at t
    batch_signs_df = pd.DataFrame(
        np.tile(batch_signs.values, (len(idx), 1)), index=idx, columns=feat_universe
    )
    batch_sig = _combined_signal_from_mask(feat_z, batch_mask, batch_signs_df)

    # ---- ONLINE selection: rolling ElasticNet importance -> top-k mask (causal, time-varying set) ----
    online_imp = rolling_elasticnet_importance(
        feat_z, cn_target, window=window, min_train=min_train, l1_ratio=l1_ratio, refit_every=1
    )
    online_mask = online_selected_mask(online_imp, top_k=top_k)
    # Online signs: orient by the BATCH sign (a stable causal-enough orientation; the rolling |coef| chooses
    # the SET, batch sign gives a consistent direction — avoids sign-flip churn dominating the IC).
    online_sig = _combined_signal_from_mask(feat_z, online_mask, batch_signs_df)

    # ---- ONLINE STABILITY: rolling bootstrap selection frequency -> threshold mask ----
    stab_freq = rolling_stability_selection(
        feat_z, cn_target, window=window, min_train=min_train,
        n_bootstrap=n_bootstrap, threshold=stab_threshold, seed=0,
    )
    stab_mask = online_selected_mask(stab_freq, threshold=stab_threshold)
    stab_sig = _combined_signal_from_mask(feat_z, stab_mask, batch_signs_df)

    schemes = {}
    for sname, sig in [("BATCH", batch_sig), ("ONLINE", online_sig), ("ONLINE_STABILITY", stab_sig)]:
        # Compare each scheme's signal at t to the carry-neutral target at t (both already causal-aligned).
        ic, n_ic = _spearman_ic(sig, cn_target)
        h1, h2 = _half_sample_ic(sig, cn_target)
        # Average selected-set size + set turnover (how much the chosen set churns row to row).
        mask = {"BATCH": batch_mask, "ONLINE": online_mask, "ONLINE_STABILITY": stab_mask}[sname]
        avg_k = float(mask.sum(axis=1).replace(0, np.nan).dropna().mean()) if mask.values.any() else float("nan")
        set_turn = float(mask.astype(int).diff().abs().sum(axis=1).dropna().mean()) if len(mask) else float("nan")
        schemes[sname] = {
            "carry_neutral_ic": ic,
            "n_ic": n_ic,
            "h1": h1,
            "h2": h2,
            "decay": (float(h2 - h1) if np.isfinite(h1) and np.isfinite(h2) else float("nan")),
            "avg_selected_k": avg_k,
            "set_turnover": set_turn,
        }

    # Deflation haircut: choosing among N_TRIALS feature combinations inflates IC. We apply a conservative
    # haircut to the ABS IC proportional to sqrt(2 ln(trials) / n) (a White's-reality-check-flavored bound)
    # and report the deflated IC alongside the raw. This is a NOTE, not a p-value.
    n_trials = max(2, len(feat_universe))  # we screened among this many features for the top-k set
    def _deflate(ic, n):
        if not np.isfinite(ic) or n is None or n < 12:
            return float("nan")
        import math
        haircut = math.sqrt(2.0 * math.log(n_trials) / n)
        mag = max(abs(ic) - haircut, 0.0)
        return float(math.copysign(mag, ic))

    for sname, rec in schemes.items():
        rec["deflated_ic"] = _deflate(rec["carry_neutral_ic"], rec["n_ic"])

    batch_ic = schemes["BATCH"]["deflated_ic"]
    best_online, best_d = None, float("-inf")
    for sname in ("ONLINE", "ONLINE_STABILITY"):
        di = schemes[sname]["deflated_ic"]
        if np.isfinite(di) and np.isfinite(batch_ic):
            d = di - batch_ic
            schemes[sname]["delta_vs_batch_deflated_ic"] = float(d)
            if d > best_d:
                best_d, best_online = d, sname
        else:
            schemes[sname]["delta_vs_batch_deflated_ic"] = float("nan")
    schemes["BATCH"]["delta_vs_batch_deflated_ic"] = 0.0

    win = best_online is not None and best_d >= IC_WIN_MARGIN
    if win:
        verdict = (
            f"TENTATIVE: {best_online} beats BATCH on DEFLATED carry-neutral IC by +{best_d:.3f} "
            f"(>= {IC_WIN_MARGIN}). NOT an alpha claim; online selection MIGHT add value here — confirm on "
            "forward paper before any reliance. Note BATCH is an optimistic (full-sample-chosen) baseline."
        )
    elif best_online is not None:
        verdict = (
            f"NO MEANINGFUL IMPROVEMENT: best online scheme {best_online} delta deflated-IC {best_d:+.3f} "
            f"< {IC_WIN_MARGIN} over BATCH. Online feature selection does NOT add measured value here (the "
            "expected, honest outcome): it churns the selected set and adds estimation noise without a "
            "deflated IC gain. BATCH selection remains the baseline."
        )
    else:
        verdict = "INCONCLUSIVE: insufficient overlap to compare deflated ICs."

    return {
        "status": "OK",
        "instrument": instrument,
        "horizon": horizon,
        "n_features_universe": len(feat_universe),
        "feature_universe": feat_universe,
        "n_trials_deflation": n_trials,
        "ic_win_margin": IC_WIN_MARGIN,
        "params": {
            "top_k": top_k, "window": window, "min_train": min_train, "l1_ratio": l1_ratio,
            "n_bootstrap": n_bootstrap, "stab_threshold": stab_threshold,
        },
        "batch_selection": batch_info,
        "schemes": schemes,
        "best_online_scheme": best_online,
        "best_delta_deflated_ic": (None if best_online is None else best_d),
        "win": bool(win),
        "verdict": verdict,
    }


def _batch_signed_coef(Xs, ys, *, l1_ratio):
    """Recover the SIGNED standardized ElasticNet coefficient for orientation (sklearn or numpy fallback)."""
    import numpy as np
    try:
        from sklearn.linear_model import ElasticNet
        m = ElasticNet(alpha=0.01, l1_ratio=l1_ratio if l1_ratio > 0 else 0.01,
                       max_iter=5000, fit_intercept=False)
        m.fit(Xs, ys)
        return np.asarray(m.coef_, dtype="float64").ravel()
    except Exception:
        from arc.intelligence.online_selection import _coord_descent_enet  # type: ignore
        return _coord_descent_enet(Xs, ys, alpha=0.01, l1_ratio=l1_ratio)


def _print_table(res) -> None:
    print("\n" + "#" * 100)
    print("PHASE 5 (deferred) — ONLINE vs BATCH FEATURE SELECTION (causal, carry-neutral IC, DEFLATED, "
          "NOT an alpha claim)")
    print("#" * 100)
    if res["status"] != "OK":
        print(f"  {res['status']}")
        return
    p = res["params"]
    print(f"  instrument={res['instrument']}  horizon={res['horizon']}  "
          f"features={res['n_features_universe']}  top_k={p['top_k']}  window={p['window']}  "
          f"min_train={p['min_train']}  win bar = +{IC_WIN_MARGIN} deflated cnIC over BATCH")
    print(f"  batch selected: {res['batch_selection'].get('selected')}")
    print("  " + "-" * 96)
    hdr = (f"  {'scheme':18s} {'cnIC':>7s} {'deflIC':>7s} {'H1':>7s} {'H2':>7s} {'decay':>7s} "
           f"{'avgK':>6s} {'setTurn':>8s} {'dVsBatch':>9s}")
    print(hdr)
    print("  " + "-" * 96)
    for sname, rec in res["schemes"].items():
        print(f"  {sname:18s} {rec['carry_neutral_ic']:>+7.3f} {rec['deflated_ic']:>+7.3f} "
              f"{rec['h1']:>+7.3f} {rec['h2']:>+7.3f} {rec['decay']:>+7.3f} "
              f"{rec['avg_selected_k']:>6.1f} {rec['set_turnover']:>8.2f} "
              f"{rec['delta_vs_batch_deflated_ic']:>+9.3f}")
    print("  " + "-" * 96)
    print(f"\n  VERDICT: {res['verdict']}")


def main() -> None:
    import macro_risk_os_v2 as eng

    ap = argparse.ArgumentParser(
        description="Phase 5 honest measurement: does ONLINE feature selection beat BATCH?")
    ap.add_argument("--instrument", type=str, default="long", help="ret_df column for the forward target")
    ap.add_argument("--top-k", type=int, default=5, help="number of features in the selected set")
    ap.add_argument("--window", type=int, default=60, help="rolling train-window (months)")
    ap.add_argument("--min-train", type=int, default=36, help="min strictly-past rows before selection")
    ap.add_argument("--l1-ratio", type=float, default=0.5, help="ElasticNet L1/L2 mix")
    ap.add_argument("--n-bootstrap", type=int, default=40, help="bootstraps for stability selection")
    ap.add_argument("--stab-threshold", type=float, default=0.6, help="stability selection frequency cut")
    args = ap.parse_args()

    print("[measure-online-selection] initializing engine (PIT features)...", file=sys.stderr)
    e = eng.ProductionEngine(eng.DEFAULT_CONFIG)
    e.initialize()
    feat_df = e.feature_engine.feature_df
    ret_df = e.data_layer.ret_df
    horizon = eng.DEFAULT_CONFIG.get("prediction_horizon_months", 1)
    out_dir = eng.OUTPUT_DIR

    res = measure(
        feat_df, ret_df,
        instrument=args.instrument, top_k=args.top_k, window=args.window, min_train=args.min_train,
        l1_ratio=args.l1_ratio, n_bootstrap=args.n_bootstrap, stab_threshold=args.stab_threshold,
        horizon=horizon,
    )
    _print_table(res)

    print("\n  REMINDER: carry-neutral IC is deflated for the feature-search count; a 'win' must clear the "
          "margin AFTER deflation. BATCH here is the OPTIMISTIC (full-sample-chosen) baseline, so online "
          "starts at a disadvantage by construction. The single-use forward holdout was NOT touched.")

    payload = {
        "phase": "5_online_feature_selection",
        "honest_note": (
            "MEASURED infrastructure, not an alpha claim. In-sample comparison of ONLINE (rolling, causal) "
            "vs BATCH (full-sample) feature selection via carry-neutral IC, deflated for the search count. "
            "BATCH is an optimistic full-sample-chosen baseline. Forward holdout untouched. The expected, "
            "honest outcome is marginal / null."
        ),
        "ic_win_margin": IC_WIN_MARGIN,
        "schemes": ["BATCH", "ONLINE", "ONLINE_STABILITY"],
        "result": res,
        "overall_verdict": res.get("verdict", res.get("status")),
    }
    out_path = os.path.join(out_dir, "measure_online_selection.json")
    os.makedirs(out_dir, exist_ok=True)
    with open(out_path, "w", encoding="ascii") as f:
        json.dump(payload, f, indent=2, default=float)
    print(f"\n[measure-online-selection] wrote {out_path}")


if __name__ == "__main__":
    main()
