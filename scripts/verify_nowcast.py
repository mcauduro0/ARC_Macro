"""Phase 4.4 — adversarial verification of the nowcast survivors (RED-FLAG discipline).

cnIC ~0.2 with H2>H1 across three rate instruments, from a freshly-built feature, is exactly the kind
of "too good" result this project treats as leakage until proven otherwise. This script tries to BREAK
the find:

  A. Diagnose why the real-curve features had ~0 obs (coverage vs alignment).
  B. Is it equity/market beta, not activity? Leave-one-out rebuild + an activity-ONLY nowcast (drop the
     market-priced inputs EWZ/BCOM). If it collapses without EWZ, it's risk-on/off, not a nowcast.
  C. Is it just the broad risk factor? Partial-correlation IC neutralizing vs carry AND market state
     (EWZ return, VIX), not just carry.
  D. Is it predictive or merely coincident / mis-aligned? IC at lags -1..+2 (a genuine signal predicts
     the FORWARD return; a leak shows an implausible contemporaneous/anti-causal spike).
  E. Sub-period thirds (is it period-concentrated like the old regime-timing edge?).
  F. Placebo: a random signal through the same pipeline must FAIL (the gate still has teeth).

Run: python scripts/verify_nowcast.py
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
    """Partial-correlation IC: residualize signal and fwd on [1, *controls], correlate residuals."""
    import numpy as np
    import pandas as pd
    df = pd.concat([signal.rename("s"), fwd.rename("r")] + [c.rename(f"c{i}") for i, c in enumerate(controls)],
                   axis=1).dropna()
    if len(df) < 40:
        return float("nan"), len(df)
    X = np.column_stack([np.ones(len(df))] + [df[f"c{i}"].values for i in range(len(controls))])
    def resid(y):
        beta, *_ = np.linalg.lstsq(X, y, rcond=None)
        return y - X @ beta
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
    from arc.features.nowcast import activity_nowcast, nowcast_surprise
    from arc.research import evaluate_signal

    print("[verify] initializing engine...", file=sys.stderr)
    e = eng.ProductionEngine(eng.DEFAULT_CONFIG)
    e.initialize()
    feat_df = e.feature_engine.feature_df
    ret_df = e.data_layer.ret_df
    monthly = e.data_layer.monthly
    horizon = eng.DEFAULT_CONFIG.get("prediction_horizon_months", 1)
    idx = feat_df.index

    def m(key):
        s = monthly.get(key)
        return s.reindex(idx) if s is not None else pd.Series(index=idx, dtype="float64")

    fwd = {inst: forward_returns(ret_df[inst], horizon) for inst in ["front", "belly", "long"]}
    carry = {inst: feat_df[f"carry_{inst}"] for inst in fwd if f"carry_{inst}" in feat_df.columns}

    print("\n" + "=" * 88)
    print("A. REAL-CURVE COVERAGE DIAGNOSIS")
    print("=" * 88)
    for k in ["ntnb_5y", "ntnb_10y", "breakeven_5y", "breakeven_10y"]:
        s = monthly.get(k)
        if s is None:
            print(f"  {k:16s}: MISSING from monthly")
            continue
        sd = s.dropna()
        inter = len(s.reindex(idx).dropna())
        rng = f"{sd.index[0].date()}..{sd.index[-1].date()}" if len(sd) else "empty"
        print(f"  {k:16s}: raw n={len(sd):4d} range {rng:24s} overlap-with-featidx={inter}")

    # ---- build nowcast variants ----
    factor_full = activity_nowcast(monthly, ACTIVITY_KEYS, ref_col="ibc_br").reindex(idx)
    activity_only = [k for k in ["ibc_br", "iron_ore", "tot"]]
    factor_act = activity_nowcast(monthly, activity_only, ref_col="ibc_br").reindex(idx)

    SIGS = {
        "front/neg_nowcast_surprise": ("front", -nowcast_surprise(factor_full)),
        "belly/neg_nowcast":          ("belly", -factor_full),
        "long/neg_nowcast_mom3":      ("long",  -factor_full.diff(3)),
    }

    print("\n" + "=" * 88)
    print("B. LEAVE-ONE-OUT + ACTIVITY-ONLY (is it EWZ/market beta, not activity?)")
    print("=" * 88)
    print(f"  {'variant':22s} {'inst':5s} {'cnIC':>7s} {'H2':>7s} {'OOSm':>7s}  pass")
    for drop in [None, "ewz", "bcom", "iron_ore", "ibc_br"]:
        keys = [k for k in ACTIVITY_KEYS if k != drop]
        fac = activity_nowcast(monthly, keys, ref_col="ibc_br").reindex(idx)
        for name, (inst, _orig) in SIGS.items():
            if "surprise" in name:
                sig = -nowcast_surprise(fac)
            elif "mom3" in name:
                sig = -fac.diff(3)
            else:
                sig = -fac
            r = evaluate_signal(sig, fwd[inst], carry[inst])
            tag = f"drop={drop or 'none':8s}"
            print(f"  {tag:22s} {inst:5s} {r.get('carry_neutral_ic', float('nan')):+.3f} "
                  f"{r.get('h2', float('nan')):+.3f} {r.get('refit_oos_mean', float('nan')):+.3f}  "
                  f"{'PASS' if r.get('passed') else 'fail'}")
        print("  " + "-" * 60)

    print("  ACTIVITY-ONLY nowcast (ibc_br+iron_ore+tot, NO market prices):")
    for name, (inst, _o) in SIGS.items():
        if "surprise" in name:
            sig = -nowcast_surprise(factor_act)
        elif "mom3" in name:
            sig = -factor_act.diff(3)
        else:
            sig = -factor_act
        r = evaluate_signal(sig, fwd[inst], carry[inst])
        print(f"    {name:28s} cnIC={r.get('carry_neutral_ic', float('nan')):+.3f} "
              f"H2={r.get('h2', float('nan')):+.3f} OOSm={r.get('refit_oos_mean', float('nan')):+.3f}  "
              f"{'PASS' if r.get('passed') else 'fail'}")

    print("\n" + "=" * 88)
    print("C. PARTIAL IC neutralizing vs carry + MARKET (EWZ ret, VIX) — beyond risk-on/off?")
    print("=" * 88)
    ewz_ret = m("ewz").pct_change()
    vix = m("vix")
    for name, (inst, sig) in SIGS.items():
        ic_carry, _ = _partial_ic(sig, fwd[inst], [carry[inst]])
        ic_mkt, n = _partial_ic(sig, fwd[inst], [carry[inst], ewz_ret, vix])
        print(f"  {name:28s} cnIC(carry)={ic_carry:+.3f}  IC(carry+mkt)={ic_mkt:+.3f}  n={n}")

    print("\n" + "=" * 88)
    print("D. LAG SCAN (predictive vs coincident/leaky): IC(signal[t], ret over (t+L-1,t+L])")
    print("=" * 88)
    for name, (inst, sig) in SIGS.items():
        row = []
        for L in [-1, 0, 1, 2]:
            r = forward_returns(ret_df[inst], horizon).shift(-(L - 1)) if L != 1 else fwd[inst]
            # L=1 is the genuine forward target; L=0 contemporaneous; L=-1 backward; L=2 two-ahead
            d = pd.concat([sig, r], axis=1).dropna()
            ic = information_coefficient(d.iloc[:, 0], d.iloc[:, 1]) if len(d) > 30 else float("nan")
            row.append(f"L={L:+d}:{ic:+.3f}")
        print(f"  {name:28s} " + "  ".join(row))

    print("\n" + "=" * 88)
    print("E. SUB-PERIOD THIRDS (period-concentrated?)")
    print("=" * 88)
    for name, (inst, sig) in SIGS.items():
        d = pd.concat([sig, fwd[inst], carry[inst]], axis=1).dropna()
        n = len(d)
        thirds = []
        for a, b in [(0, n // 3), (n // 3, 2 * n // 3), (2 * n // 3, n)]:
            seg = d.iloc[a:b]
            ic = information_coefficient(seg.iloc[:, 0], seg.iloc[:, 1]) if len(seg) > 10 else float("nan")
            thirds.append(f"{ic:+.3f}")
        print(f"  {name:28s} thirds = [{', '.join(thirds)}]")

    print("\n" + "=" * 88)
    print("F. PLACEBO (random signal must FAIL — gate still has teeth)")
    print("=" * 88)
    rng = np.random.default_rng(0)
    placebo = pd.Series(rng.normal(size=len(idx)), index=idx)
    r = evaluate_signal(placebo, fwd["belly"], carry["belly"])
    print(f"  random/belly: cnIC={r.get('carry_neutral_ic', float('nan')):+.3f} "
          f"OOSm={r.get('refit_oos_mean', float('nan')):+.3f}  {'PASS(!?)' if r.get('passed') else 'fail (good)'}")


if __name__ == "__main__":
    main()
