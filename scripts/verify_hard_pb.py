"""Phase 4.5 — adversarial verification of the lone 'hard' survivor: pb_momentum (fiscal primary balance).

It is 1 of 69 cumulative hypotheses (≈3 false positives expected at 5%) and its worst OOS fold is +0.004
(razor-thin). RED-FLAG discipline: try to break it before calling it an edge.

  A. Lookback robustness: primary_balance.diff(3/6/9/12) — a real fiscal edge should not hinge on one window.
  B. Partial IC neutralizing vs spread carry + global risk (VIX, US HY) — beyond risk-on/off?
  C. Lag scan: predictive (forward) vs coincident/leaky.
  D. Sub-period thirds: period-concentrated?
  E. Orthogonality to the two existing edges (front/mom3 price momentum; the activity nowcast).
  F. Placebo: a random signal must FAIL.

Run: python scripts/verify_hard_pb.py
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

ACTIVITY_KEYS = ["ibc_br", "ewz", "iron_ore", "tot", "bcom"]


def _partial_ic(signal, fwd, controls):
    import numpy as np
    import pandas as pd
    cols = {"s": signal, "r": fwd}
    for i, c in enumerate(controls):
        cols[f"c{i}"] = c
    df = pd.concat(cols, axis=1).dropna()
    if len(df) < 40:
        return float("nan"), len(df)
    X = np.column_stack([np.ones(len(df))] + [df[f"c{i}"].values for i in range(len(controls))])
    def resid(y):
        b, *_ = np.linalg.lstsq(X, y, rcond=None)
        return y - X @ b
    rs, rr = resid(df["s"].values), resid(df["r"].values)
    if rs.std() < 1e-12 or rr.std() < 1e-12:
        return float("nan"), len(df)
    return float(np.corrcoef(rs, rr)[0, 1]), len(df)


def main() -> None:
    import numpy as np
    import pandas as pd

    import macro_risk_os_v2 as eng
    from arc.eval import forward_returns
    from arc.eval.metrics import information_coefficient
    from arc.features.nowcast import activity_nowcast
    from arc.research import evaluate_signal

    print("[verify-hard] initializing engine...", file=sys.stderr)
    e = eng.ProductionEngine(eng.DEFAULT_CONFIG)
    e.initialize()
    ret_df = e.data_layer.ret_df
    monthly = e.data_layer.monthly
    idx = e.feature_engine.feature_df.index
    horizon = eng.DEFAULT_CONFIG.get("prediction_horizon_months", 1)

    pb = monthly.get("primary_balance").reindex(idx)
    fwd = forward_returns(ret_df["hard"], horizon)
    carry = (monthly.get("embi_spread").reindex(idx)) / 10000.0 / 12.0
    vix = monthly.get("vix").reindex(idx)
    hy = monthly.get("us_hy_spread").reindex(idx)

    print("\n" + "=" * 84)
    print("A. LOOKBACK ROBUSTNESS — pb_momentum = primary_balance.diff(L)")
    print("=" * 84)
    for L in [3, 6, 9, 12]:
        r = evaluate_signal(pb.diff(L), fwd, carry)
        print(f"  diff({L:>2d}): cnIC={r.get('carry_neutral_ic', float('nan')):+.3f} "
              f"H1={r.get('h1', float('nan')):+.3f} H2={r.get('h2', float('nan')):+.3f} "
              f"OOSm={r.get('refit_oos_mean', float('nan')):+.3f} OOSmin={r.get('refit_oos_min', float('nan')):+.3f} "
              f"{'PASS' if r.get('passed') else 'fail'}")

    sig = pb.diff(6)  # the survivor
    print("\n" + "=" * 84)
    print("B. PARTIAL IC vs carry + global risk (VIX, US HY) — beyond risk-on/off?")
    print("=" * 84)
    ic_c, _ = _partial_ic(sig, fwd, [carry])
    ic_m, n = _partial_ic(sig, fwd, [carry, vix, hy])
    print(f"  pb_mom6: IC(carry)={ic_c:+.3f}  IC(carry+VIX+HY)={ic_m:+.3f}  n={n}")

    print("\n" + "=" * 84)
    print("C. LAG SCAN (predictive vs coincident/leaky)")
    print("=" * 84)
    row = []
    for L in [-1, 0, 1, 2]:
        r = fwd.shift(-(L - 1)) if L != 1 else fwd
        d = pd.concat([sig, r], axis=1).dropna()
        ic = information_coefficient(d.iloc[:, 0], d.iloc[:, 1]) if len(d) > 30 else float("nan")
        row.append(f"L={L:+d}:{ic:+.3f}")
    print("  pb_mom6  " + "  ".join(row))

    print("\n" + "=" * 84)
    print("D. SUB-PERIOD THIRDS")
    print("=" * 84)
    d = pd.concat([sig, fwd, carry], axis=1).dropna()
    n = len(d)
    thirds = [information_coefficient(d.iloc[a:b, 0], d.iloc[a:b, 1])
              for a, b in [(0, n // 3), (n // 3, 2 * n // 3), (2 * n // 3, n)]]
    print(f"  pb_mom6 thirds = [{', '.join(f'{t:+.3f}' for t in thirds)}]")

    print("\n" + "=" * 84)
    print("E. ORTHOGONALITY to existing edges (front/mom3, activity nowcast)")
    print("=" * 84)
    front_mom3 = ret_df["front"].rolling(3).sum().reindex(idx)
    factor = activity_nowcast(monthly, ACTIVITY_KEYS, ref_col="ibc_br").reindex(idx)
    c_fm = pd.concat([sig, front_mom3], axis=1).dropna()
    c_nc = pd.concat([sig, factor], axis=1).dropna()
    corr_fm = float(np.corrcoef(c_fm.iloc[:, 0], c_fm.iloc[:, 1])[0, 1]) if len(c_fm) > 12 else float("nan")
    corr_nc = float(np.corrcoef(c_nc.iloc[:, 0], c_nc.iloc[:, 1])[0, 1]) if len(c_nc) > 12 else float("nan")
    ic_x_fm, _ = _partial_ic(sig, fwd, [carry, front_mom3])
    ic_x_nc, _ = _partial_ic(sig, fwd, [carry, factor])
    print(f"  corr(pb_mom6, front_mom3)={corr_fm:+.2f}  corr(pb_mom6, nowcast)={corr_nc:+.2f}")
    print(f"  IC pb_mom6 | carry+front_mom3 = {ic_x_fm:+.3f}   IC pb_mom6 | carry+nowcast = {ic_x_nc:+.3f}")

    print("\n" + "=" * 84)
    print("F. PLACEBO (random must FAIL)")
    print("=" * 84)
    rng = np.random.default_rng(0)
    r = evaluate_signal(pd.Series(rng.normal(size=len(idx)), index=idx), fwd, carry)
    print(f"  random/hard: cnIC={r.get('carry_neutral_ic', float('nan')):+.3f} "
          f"OOSm={r.get('refit_oos_mean', float('nan')):+.3f}  {'PASS(!?)' if r.get('passed') else 'fail (good)'}")


if __name__ == "__main__":
    main()
