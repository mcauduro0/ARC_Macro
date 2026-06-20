"""Phase 4.3 — operationalize the verified front-momentum edge as a standalone, costed sleeve.

Builds the causal momentum sleeve for the rate tenors and reports its gated, deflated, net-of-cost
performance. DSR is deflated by the FULL number of hypotheses screened in Phase 4 (45) — the honest
multiple-testing penalty for having searched. Uses the PIT feature_df / ret_df from initialize()
(no walk-forward needed; the sleeve is rules-based and causal). Run: python scripts/momentum_sleeve.py
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

N_TRIALS_SCREEN = 45  # Phase 4 screened 45 hypotheses; deflate the sleeve DSR by that.


def main() -> None:
    import macro_risk_os_v2 as eng  # noqa: E402
    from arc.research import momentum_sleeve_returns, sleeve_stats  # noqa: E402

    print("[sleeve] initializing engine (PIT returns)...", file=sys.stderr)
    e = eng.ProductionEngine(eng.DEFAULT_CONFIG)
    e.initialize()
    ret_df = e.data_layer.ret_df

    print("\n" + "=" * 78)
    print("PHASE 4.3 — MOMENTUM SLEEVE (causal, net of 2bp costs, DSR deflated by 45 trials)")
    print("=" * 78)
    print(f"  {'sleeve':16s} {'n':>4s} {'annRet':>7s} {'annVol':>7s} {'Sharpe':>7s} "
          f"{'PSR':>6s} {'DSR':>6s} {'maxDD':>7s} {'hit':>5s} {'lev@10%':>7s}")
    print("  " + "-" * 80)
    for inst in ["front", "belly", "long"]:
        if inst not in ret_df.columns:
            continue
        for lb in ([3] if inst != "front" else [3, 6, 12]):
            sl = momentum_sleeve_returns(ret_df[inst], lookback=lb, cost_bps=2.0)
            st = sleeve_stats(sl, n_trials=N_TRIALS_SCREEN, vol_target_ann=0.10)
            name = f"{inst}/mom{lb}"
            print(f"  {name:16s} {st['n']:>4d} {st['ann_ret']*100:>+6.2f}% {st['ann_vol']*100:>6.2f}% "
                  f"{st['sharpe_ann']:>+6.2f} {st['psr_vs_0']:>6.3f} {st['dsr']:>6.3f} "
                  f"{st['max_drawdown']*100:>+6.1f}% {st['hit_rate']*100:>4.0f}% "
                  f"{st.get('leverage_for_vol_target', float('nan')):>6.1f}x")

    print("\n  Verdict bar: a sleeve is promotable to PAPER only if DSR (deflated by 45) > 0.5 and the")
    print("  net Sharpe survives. front/mom3 is the verified candidate; belly/long shown for context.")
    print("\n  GOVERNANCE: the in-sample holdout was NOT reserved before research (the screen used the")
    print("  full sample, including the recent third), so consuming a single-use holdout token on seen")
    print("  data would be self-deception. The genuine single-use holdout is FORWARD PAPER (data after")
    print("  the current end ~2026-06). Token reserved for that; do not evaluate the sleeve on it until")
    print("  paper accumulates out-of-time months.")


if __name__ == "__main__":
    main()
