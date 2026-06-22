"""Phase 7.4 (track a) — HONEST statistical-power audit: where does power actually come from, and what
lever shortens the time to a confident forward verdict?

Engine-touching (imports the monolith; not CI). It MEASURES, it does not assert edge. Three questions:

  1. CROSS-SECTION BREADTH. How many *independent* bets does the instrument universe (and the 3 booked
     sleeves) really offer? Eigenvalue participation ratio N_eff = (Σλ)² / Σλ² of the correlation matrix
     (N_eff = N for orthogonal columns, 1 for perfectly correlated). This bounds any pooling speed-up.

  2. THE FORWARD-VERDICT TIMELINE (the user's real question: "more power before 2028"). The promotion
     verdict scores FORWARD months only. More *in-sample* history does NOT change its inputs, so it does
     NOT accelerate the verdict. The ONLY honest accelerator is cross-sectional POOLING: an equal-weight
     panel of K_eff effectively-independent, similar-edge sleeves carries a given t-stat in ~1/K_eff of
     the calendar months. We derive a PRE-COMMITTABLE pooled eval_at_n = max(12, ceil(24 / K_eff)) — a
     fixed formula over the (stable) correlation, not a knob tuned on returns.

  3. THE IN-SAMPLE BOTTLENECK. ret_df is dropna'd on the core instruments (fx, front, belly, long), so a
     gap in ANY of them truncates the WHOLE matrix. We quantify it (the DI_5Y 2010->2012 gap forces a
     ~2012 start) and the marginal months a fix would recover — flagged as backtest-quality, NOT
     forward-verdict, power.

Honest bottom line is printed at the end. Pooling is the only forward-power lever, and it is OPTIMISTIC:
it pays off only if MULTIPLE sleeves carry real, similarly-signed edge; if one is noise, pooling dilutes.
The forward holdout remains the sole judge.
"""

from __future__ import annotations

import math
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

SINGLE_EVAL_AT_N = 24  # the pre-committed single-sleeve forward sample size
POOL_CALENDAR_FLOOR = 12  # never evaluate the pool on fewer calendar months (regime-thinness guard)


def _eff_n(corr) -> float:
    """Eigenvalue participation ratio of a correlation matrix: (Σλ)²/Σλ². N for orthogonal, 1 for rank-1."""
    import numpy as np
    eig = np.linalg.eigvalsh(np.asarray(corr, dtype="float64"))
    eig = eig[eig > 1e-12]
    return float((eig.sum() ** 2) / np.square(eig).sum())


def _sleeve_returns(spec, ret_df, monthly):
    """In-sample frozen sleeve return stream for a booked spec (momentum -> price momentum; else the
    external oriented signal). Same construction the paper loop reproduces month-by-month."""
    import pandas as pd

    from arc.autonomy import build_signal
    from arc.research.sleeve import momentum_sleeve_returns, signal_sleeve_returns
    inst = spec["instrument"]
    if inst not in ret_df.columns:
        return None
    rets = ret_df[inst].dropna()
    sig = build_signal(spec, monthly)
    if sig is None:
        return momentum_sleeve_returns(rets, lookback=int(spec["lookback"]), z_window=int(spec["z_window"]),
                                       clip_z=float(spec["clip_z"]), cost_bps=float(spec["cost_bps"]))
    sig = pd.Series(sig).dropna()
    return signal_sleeve_returns(sig, rets, z_window=int(spec["z_window"]), clip_z=float(spec["clip_z"]),
                                 cost_bps=float(spec["cost_bps"]))


def _di5y_gap_months():
    """How many in-sample months a DI_5Y 2010->2012 gap fix would recover (read the cached curve CSVs)."""
    import pandas as pd
    d = os.path.join(MODEL_DIR, "data")

    def _first(name):
        p = os.path.join(d, name + ".csv")
        if not os.path.exists(p):
            return None
        s = pd.read_csv(p)
        s.columns = [c.lower() for c in s.columns]
        col = next((c for c in s.columns if "date" in c or "data" in c), s.columns[0])
        dts = pd.to_datetime(s[col], errors="coerce").dropna().sort_values()
        # first date AFTER the largest gap (the effective continuous start)
        gaps = dts.diff()
        big = gaps[gaps > pd.Timedelta(days=60)]
        cont_start = dts.iloc[dts.index.get_loc(big.index[-1])] if len(big) else dts.iloc[0]
        return dts.iloc[0].date(), cont_start.date()
    out = {}
    for n in ("DI_1Y", "DI_5Y", "DI_10Y"):
        out[n] = _first(n)
    return out


def main() -> None:
    import numpy as np
    import pandas as pd

    import macro_risk_os_v2 as eng
    from arc.autonomy.spec import SPECS, strategy_hash

    print("[power] initializing engine (PIT returns)...", file=sys.stderr)
    e = eng.ProductionEngine(eng.DEFAULT_CONFIG)
    e.initialize()
    ret_df, monthly = e.data_layer.ret_df, e.data_layer.monthly

    print("\n" + "=" * 78)
    print("ARC statistical-power audit")
    print("=" * 78)

    # --- 1. ret_df coverage + instrument effective-N ----------------------
    print(f"\nret_df: {ret_df.shape[0]} months x {ret_df.shape[1]} instruments "
          f"[{ret_df.index[0].date()} -> {ret_df.index[-1].date()}]")
    print("  per-instrument non-NaN coverage:")
    for c in ret_df.columns:
        s = ret_df[c].dropna()
        print(f"    {c:7s}: n={len(s):4d}  [{s.index[0].date()} -> {s.index[-1].date()}]")
    inst_corr = ret_df.dropna().corr()
    n_inst = ret_df.shape[1]
    neff_inst = _eff_n(inst_corr)
    print(f"  instrument cross-section: N={n_inst}, N_eff={neff_inst:.2f} "
          f"(effective independent bets; {neff_inst / n_inst:.0%} of nominal)")

    # --- 2. the 3 booked sleeves: panel correlation + K_eff ---------------
    print("\nbooked sleeves (in-sample frozen streams):")
    sleeves = {}
    for name, spec in SPECS.items():
        sr = _sleeve_returns(spec, ret_df, monthly)
        if sr is None or len(sr) < 12:
            print(f"    {name:14s}: SKIPPED (insufficient)")
            continue
        sleeves[name] = sr.dropna()
        ann = sr.mean() * 12
        vol = sr.std(ddof=1) * np.sqrt(12)
        sh = float(ann / vol) if vol > 0 else float("nan")
        print(f"    {name:14s} ({spec['instrument']:5s}) {strategy_hash(spec)[:8]}: "
              f"n={len(sleeves[name]):3d}  in-sample Sharpe={sh:5.2f}  [{sleeves[name].index[0].date()} "
              f"-> {sleeves[name].index[-1].date()}]")

    panel = pd.DataFrame(sleeves).dropna()
    print(f"\n  aligned sleeve panel: {panel.shape[0]} common months x {panel.shape[1]} sleeves")
    if panel.shape[1] >= 2:
        pcorr = panel.corr()
        print("  pairwise correlation:")
        print(pcorr.round(3).to_string().replace("\n", "\n    ").rjust(0))
        k_eff = _eff_n(pcorr)
        avg_abs_corr = float(np.abs(pcorr.values[np.triu_indices(panel.shape[1], 1)]).mean())
        print(f"  sleeve panel: K={panel.shape[1]}, K_eff={k_eff:.2f}, avg|corr|={avg_abs_corr:.3f}")

        # equal-weight pooled stream (NO in-sample fitting -> no extra weight-deflation)
        pooled = panel.mean(axis=1)
        psh = float(pooled.mean() * 12 / (pooled.std(ddof=1) * np.sqrt(12)))
        singles = panel.apply(lambda c: c.mean() * 12 / (c.std(ddof=1) * np.sqrt(12)))
        print(f"  equal-weight pool in-sample Sharpe={psh:.2f} (vs mean single {singles.mean():.2f}; "
              f"IN-SAMPLE, descriptive only — NOT evidence)")

        # PRE-COMMITTABLE pooled eval_at_n from the (stable) correlation breadth, fixed formula
        eval_pool = max(POOL_CALENDAR_FLOOR, math.ceil(SINGLE_EVAL_AT_N / k_eff))
        print("\n" + "-" * 78)
        print("FORWARD-POWER LEVER (the only one that accelerates the verdict):")
        print(f"  single-sleeve verdict needs {SINGLE_EVAL_AT_N} forward calendar months.")
        print(f"  with K_eff={k_eff:.2f} effective-independent sleeves, an equal-weight pooled holdout")
        print(f"  carries equivalent t-content in ~{SINGLE_EVAL_AT_N / k_eff:.1f} months; pre-committed")
        print(f"  pooled eval_at_n = max({POOL_CALENDAR_FLOOR}, ceil({SINGLE_EVAL_AT_N}/{k_eff:.2f})) = "
              f"{eval_pool} forward months.")
        print(f"  => the pool could reach a verdict ~{SINGLE_EVAL_AT_N - eval_pool} months sooner "
              f"(~{(SINGLE_EVAL_AT_N - eval_pool) / 12:.1f}y) THAN a single sleeve — IF multiple sleeves")
        print("     carry real, similarly-signed edge. If one is noise, pooling DILUTES (forward test judges).")
        print("-" * 78)

    # --- 3. the in-sample bottleneck (backtest-quality, NOT forward power) -
    print("\nIN-SAMPLE BOTTLENECK (backtest length; does NOT accelerate the forward verdict):")
    gaps = _di5y_gap_months()
    for n, v in gaps.items():
        if v:
            print(f"    {n}: raw_first={v[0]}  continuous_from={v[1]}")
    di5 = gaps.get("DI_5Y")
    if di5 and di5[0] != di5[1]:
        recoverable = (pd.Timestamp(di5[1]) - pd.Timestamp(di5[0])).days // 30
        print(f"    -> DI_5Y has a ~{recoverable}-month gap; 'belly' is a CORE instrument, so ret_df is")
        print(f"       dropna'd to belly's continuous start (~{di5[1]}). front/long/hard real returns over")
        print("       that window are REAL but DROPPED. Filling DI_5Y (curve interpolation, FLAGGED) would")
        print(f"       recover ~{recoverable} months of in-sample history for the booked sleeves' GATE")
        print("       calibration — but the FORWARD verdict's inputs are unchanged, so it does NOT shorten")
        print("       the time to promotion. It is a backtest-robustness improvement, not a power lever.")

    print("\n" + "=" * 78)
    print("HONEST BOTTOM LINE:")
    print("  - The forward verdict is bound by forward calendar months; in-sample history & macro-series")
    print("    history (features only) do NOT accelerate it.")
    print("  - The ONLY honest accelerator is cross-sectional POOLING of the booked sleeves, and it is a")
    print("    BET that several sleeves have real edge. Pre-register it; let the forward holdout decide.")
    print("  - Nothing here is evidence of edge. No fabrication. The holdout remains the sole promoter.")
    print("=" * 78)


if __name__ == "__main__":
    main()
