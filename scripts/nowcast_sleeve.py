"""Phase 4.4 — operationalize the activity nowcast as a standalone causal sleeve (the 2nd edge).

Mirrors scripts/momentum_sleeve.py for the nowcast signal. Builds the strictly-PIT nowcast factor and
runs the generic causal sleeve (arc.research.signal_sleeve_returns) for the rate receivers, reporting
gated, deflated, net-of-cost performance. DSR is deflated by the CUMULATIVE hypothesis count across
rounds 1+2 (the honest multiple-testing penalty for having searched twice). The single-use holdout is
reserved for FORWARD paper (scripts/paper_loop.py --strategy nowcast), never consumed here.

Run: python scripts/nowcast_sleeve.py
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

N_TRIALS = 55  # cumulative hypotheses screened across rounds 1 (45) + 2 (nowcast/real-curve family)
ACTIVITY_KEYS = ["ibc_br", "ewz", "iron_ore", "tot", "bcom"]


def main() -> None:
    import macro_risk_os_v2 as eng
    from arc.features.nowcast import activity_nowcast, nowcast_surprise
    from arc.research import signal_sleeve_returns, sleeve_stats

    print("[nowcast-sleeve] initializing engine (PIT returns)...", file=sys.stderr)
    e = eng.ProductionEngine(eng.DEFAULT_CONFIG)
    e.initialize()
    ret_df = e.data_layer.ret_df
    monthly = e.data_layer.monthly
    factor = activity_nowcast(monthly, ACTIVITY_KEYS, ref_col="ibc_br")

    sleeves = {
        "belly/neg_nowcast":          ("belly", -factor),
        "long/neg_nowcast_mom3":      ("long", -factor.diff(3)),
        "front/neg_nowcast_surprise": ("front", -nowcast_surprise(factor)),
    }

    print("\n" + "=" * 90)
    print("PHASE 4.4 — NOWCAST SLEEVE (causal, net of 2bp costs, DSR deflated by 55 cumulative trials)")
    print("=" * 90)
    print(f"  {'sleeve':26s} {'n':>4s} {'annRet':>7s} {'annVol':>7s} {'Sharpe':>7s} "
          f"{'PSR':>6s} {'DSR':>6s} {'maxDD':>7s} {'hit':>5s} {'lev@10%':>7s}")
    print("  " + "-" * 92)
    for name, (inst, sig) in sleeves.items():
        if inst not in ret_df.columns:
            continue
        sl = signal_sleeve_returns(sig, ret_df[inst], cost_bps=2.0)
        st = sleeve_stats(sl, n_trials=N_TRIALS, vol_target_ann=0.10)
        print(f"  {name:26s} {st['n']:>4d} {st['ann_ret']*100:>+6.2f}% {st['ann_vol']*100:>6.2f}% "
              f"{st['sharpe_ann']:>+6.2f} {st['psr_vs_0']:>6.3f} {st['dsr']:>6.3f} "
              f"{st['max_drawdown']*100:>+6.1f}% {st['hit_rate']*100:>4.0f}% "
              f"{st.get('leverage_for_vol_target', float('nan')):>6.1f}x")

    print("\n  Verdict bar: a sleeve is promotable to PAPER only if DSR (deflated by 55) > 0.5 and the net")
    print("  Sharpe survives. long/neg_nowcast_mom3 is the booked candidate (NOWCAST_SPEC); others context.")
    print("\n  GOVERNANCE: the single-use holdout is FORWARD PAPER (data after the current end), accrued by")
    print("  scripts/paper_loop.py --strategy nowcast. It is NOT consumed here; this is in-sample context.")


if __name__ == "__main__":
    main()
