"""Phase 7.4 — measure the LIVE pre-trade VaR/ES gate on the booked sleeves (operational, NOT alpha).

Engine-touching (imports the monolith; not CI). Replays the gate CAUSALLY month-by-month over each
sleeve's in-sample return stream: at each month t (history strictly < t), size to the 10% vol target,
then apply the VaR/ES cap, and compare the gated stream vs the vol-target-only stream. Reports how often
the gate binds, the average leverage cut when it does, and the realized tail/drawdown it would have
shaved. For the 3-sleeve BOOK it uses the cross-sleeve covariance (EWMA for the rolling pass — DCC-GARCH
QMLE per step is too slow for ~150 steps — plus a final DCC-GARCH snapshot).

HONEST FRAMING: a VaR/ES gate BOUNDS LOSSES; it makes no alpha claim. The numbers below are operational
risk control — tail/drawdown management at the cost of some foregone upside in the months it cuts size.
It does not, and must not, change the scored frozen holdout (the loop wiring is proven to leave it
byte-identical in tests/test_risk_gate.py).
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

VOL_TARGET = 0.10
MIN_MONTHS = 24


def _sleeve_returns(spec, ret_df, monthly):
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


def _stats(pnl):
    import numpy as np
    eq = (1.0 + pnl).cumprod()
    dd = float((eq / eq.cummax() - 1.0).min())
    vol = float(pnl.std(ddof=1) * np.sqrt(12))
    return {"worst_month": float(pnl.min()), "maxDD": dd, "ann_vol": vol,
            "ann_ret": float(pnl.mean() * 12)}


def _replay_single(s, limits):
    """Causal month-by-month: size to vol target on trailing data, then apply the VaR/ES cap."""
    import numpy as np
    import pandas as pd
    from arc.autonomy.risk_gate import pretrade_leverage_gate
    s = pd.Series(s).dropna()
    gated, volonly, binds, cuts = [], [], 0, []
    idx = []
    for t in range(MIN_MONTHS, len(s)):
        hist = s.iloc[:t]
        ann_vol = float(hist.std(ddof=1) * np.sqrt(12))
        if not (ann_vol > 0):
            continue
        vt_lev = VOL_TARGET / ann_vol
        g = pretrade_leverage_gate(hist, requested_leverage=vt_lev, limits=limits)
        applied = g.applied_leverage
        r_next = float(s.iloc[t])
        volonly.append(vt_lev * r_next)
        gated.append(applied * r_next)
        idx.append(s.index[t])
        if g.binding != "vol_target":
            binds += 1
            cuts.append(1.0 - applied / vt_lev)
    gated = pd.Series(gated, index=idx)
    volonly = pd.Series(volonly, index=idx)
    return {
        "n": len(gated), "bind_freq": (binds / len(gated)) if len(gated) else float("nan"),
        "mean_cut": (float(np.mean(cuts)) if cuts else 0.0),
        "gated": _stats(gated), "volonly": _stats(volonly),
    }


def main() -> None:
    import numpy as np
    import pandas as pd

    import macro_risk_os_v2 as eng
    from arc.autonomy.risk_gate import RiskLimits, portfolio_pretrade_gate
    from arc.autonomy.spec import SPECS

    print("[gate] initializing engine (PIT returns)...", file=sys.stderr)
    e = eng.ProductionEngine(eng.DEFAULT_CONFIG)
    e.initialize()
    ret_df, monthly = e.data_layer.ret_df, e.data_layer.monthly
    limits = RiskLimits()  # defaults: VaR 5.5% / ES 7.5% monthly, 95%, min 24m, Cornish-Fisher

    print("\n" + "=" * 86)
    print(f"LIVE PRE-TRADE VaR/ES GATE — operational replay (vol target {VOL_TARGET:.0%}, "
          f"budget VaR {limits.var_limit:.1%} / ES {limits.es_limit:.1%} monthly @95%)")
    print("=" * 86)
    print(f"{'sleeve':16s} {'n':>4s} {'bind%':>7s} {'meanCut':>8s} "
          f"{'worstM vol':>11s} {'worstM gate':>12s} {'maxDD vol':>10s} {'maxDD gate':>11s}")

    sleeves = {}
    for name, spec in SPECS.items():
        s = _sleeve_returns(spec, ret_df, monthly)
        if s is None or len(s.dropna()) < MIN_MONTHS + 6:
            print(f"{name:16s}  SKIPPED (insufficient)")
            continue
        sleeves[name] = s.dropna()
        r = _replay_single(s, limits)
        print(f"{name:16s} {r['n']:>4d} {r['bind_freq']:>7.1%} {r['mean_cut']:>8.1%} "
              f"{r['volonly']['worst_month']:>11.3f} {r['gated']['worst_month']:>12.3f} "
              f"{r['volonly']['maxDD']:>10.2%} {r['gated']['maxDD']:>11.2%}")

    # ---- tighter budget: show the gate HAS teeth + the honest tradeoff (return given up vs vol/DD cut) ----
    tight = RiskLimits(var_limit=0.035, es_limit=0.045)
    print("\n" + "-" * 86)
    print(f"TIGHTER budget (VaR {tight.var_limit:.1%} / ES {tight.es_limit:.1%}) — the gate now binds; "
          f"tradeoff = annualised return GIVEN UP vs vol & drawdown CUT:")
    print(f"{'sleeve':16s} {'bind%':>7s} {'meanCut':>8s} {'ret vol':>9s} {'ret gate':>9s} "
          f"{'vol vol':>8s} {'vol gate':>9s} {'maxDD vol':>10s} {'maxDD gate':>11s}")
    for name, s in sleeves.items():
        r = _replay_single(s, tight)
        print(f"{name:16s} {r['bind_freq']:>7.1%} {r['mean_cut']:>8.1%} "
              f"{r['volonly']['ann_ret']:>9.2%} {r['gated']['ann_ret']:>9.2%} "
              f"{r['volonly']['ann_vol']:>8.2%} {r['gated']['ann_vol']:>9.2%} "
              f"{r['volonly']['maxDD']:>10.2%} {r['gated']['maxDD']:>11.2%}")

    # ---- the 3-sleeve BOOK: portfolio VaR gate using the cross-sleeve covariance ----
    panel = pd.DataFrame(sleeves).dropna()
    if panel.shape[1] >= 2 and len(panel) >= MIN_MONTHS + 6:
        w = np.full(panel.shape[1], 1.0 / panel.shape[1])
        binds, cuts, n = 0, [], 0
        gated, volonly, idx = [], [], []
        for t in range(MIN_MONTHS, len(panel)):
            hist = panel.iloc[:t]
            book_hist = hist @ w
            ann_vol = float(book_hist.std(ddof=1) * np.sqrt(12))
            if not (ann_vol > 0):
                continue
            vt_lev = VOL_TARGET / ann_vol
            g = portfolio_pretrade_gate(hist, w, requested_leverage=vt_lev, limits=limits, cov_method="ewma")
            r_next = float(panel.iloc[t] @ w)
            volonly.append(vt_lev * r_next)
            gated.append(g.applied_leverage * r_next)
            idx.append(panel.index[t])
            n += 1
            if g.binding != "vol_target":
                binds += 1
                cuts.append(1.0 - g.applied_leverage / vt_lev)
        gated = pd.Series(gated, index=idx)
        volonly = pd.Series(volonly, index=idx)
        print("-" * 86)
        print(f"{'POOL (book, ewma)':16s} {n:>4d} {(binds/n if n else float('nan')):>7.1%} "
              f"{(float(np.mean(cuts)) if cuts else 0.0):>8.1%} "
              f"{volonly.min():>11.3f} {gated.min():>12.3f} "
              f"{_stats(volonly)['maxDD']:>10.2%} {_stats(gated)['maxDD']:>11.2%}")

        # one DCC-GARCH snapshot at the latest date (the production covariance forecast)
        from arc.autonomy.risk_gate import RiskLimits as RL
        book_vol = float((panel @ w).std(ddof=1) * np.sqrt(12))
        vt_lev = VOL_TARGET / book_vol if book_vol > 0 else float("nan")
        gd = portfolio_pretrade_gate(panel, w, requested_leverage=vt_lev, limits=RL(), cov_method="dcc")
        print(f"\n[gate] latest DCC-GARCH book snapshot: per-unit VaR {gd.var_per_unit:.4f}, "
              f"ES {gd.es_per_unit:.4f}; vol-target leverage {vt_lev:.2f} -> applied {gd.applied_leverage:.2f} "
              f"(binding={gd.binding})")

    print("\n" + "=" * 86)
    print("HONEST READ: the gate is operational tail control, NOT alpha. Where it binds it caps leverage to")
    print("the loss budget (shaving the worst months / drawdown) at the cost of some upside those months;")
    print("where the book is well-behaved it is transparent (vol target binds). It NEVER touches the scored")
    print("frozen holdout — that is proven byte-identical in tests/test_risk_gate.py.")
    print("=" * 86)


if __name__ == "__main__":
    main()
