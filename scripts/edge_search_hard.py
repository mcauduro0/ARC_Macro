"""Phase 4.5 — honest edge search, round 3: the 'hard' instrument (Brazil sovereign-spread receiver).

The roadmap flags 'hard' refit-OOS IC ~0.33 as the single most plausible genuine residual edge left in
the engine. But that number is suspect: a prior defect carry-neutralized `hard` against the cupom-FX
carry (carry_hard = cupom cambial) instead of the TRUE spread carry, so a signal that was really just
SPREAD CARRY in disguise looked like alpha (e.g. Z_cds_br carry-neutral IC +0.16 collapsing to -0.045
once neutralized against embi/10000/12). This round does the honest version: every candidate is carry-
neutralized against the TRUE spread carry  carry['hard'] = monthly['embi_spread']/10000/12.

The `hard` return is a sovereign-spread RECEIVER: ret_hard = (-d_spread/10000 * dv01) + spread_carry, so
the position GAINS WHEN THE SPREAD TIGHTENS (d_spread < 0). Every candidate below is therefore ORIENTED
so that "higher signal => higher hard forward return = spread tightening".

We do NOT screen the full feature x instrument cross-product (that is data mining). We pre-register a
small, economically-motivated set of single-feature hypotheses for `hard` across DISTINCT families:

  (1) SOVEREIGN CREDIT — CDS/EMBI momentum (tightening trend continues) + a cross to US HY spread.
  (2) FISCAL          — debt acceleration & primary-balance momentum (worse fiscal => wider => negate).
  (3) EXTERNAL        — BoP/current account, terms of trade, iron ore (better external => tighter => +).
  (4) GLOBAL RISK     — VIX, DXY, US HY spread (risk-off => wider => negate).
  (5) MOMENTUM        — mom3/6/12 of hard returns (past tightening continues).
  (6) ACTIVITY NOWCAST— the strictly-PIT activity factor (arc.features.nowcast); for a sovereign spread
                        the prior is the OPPOSITE of the rate-receiver: stronger activity => better
                        growth/fiscal => tighter spread => + (stated explicitly, gated not assumed).

Each candidate runs through the SAME gate as rounds 1+2 (carry-neutralized IC, half-sample H1/H2 decay,
refit-OOS CPCV). Multiple testing is CUMULATIVE: rounds 1 (signal_research.py, 45) + 2 (edge_search_
nowcast.py, ~10) screened ~55 hypotheses; this round adds its own, so any survivor must be read against
the full cumulative count (~3+ false positives expected at 5%). Survivors are hypotheses to adversarially
re-verify on a single-use forward holdout, NEVER auto-promotions.

Run: python scripts/edge_search_hard.py
"""

from __future__ import annotations

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

# Cumulative multiple-testing context: round 1 (signal_research.py) = 45, round 2
# (edge_search_nowcast.py) = ~10. Anything that survives here must be deflated against the total.
PRIOR_HYPOTHESES = 55
ACTIVITY_KEYS = ["ibc_br", "ewz", "iron_ore", "tot", "bcom"]


def _czscore(s, min_periods=24):
    """Expanding (causal) z-score: mean/std use only data <= t, never the full sample."""
    import numpy as np
    s = s.astype("float64")
    mu = s.expanding(min_periods=min_periods).mean()
    sd = s.expanding(min_periods=min_periods).std().replace(0.0, np.nan)
    return (s - mu) / sd


def main() -> None:
    import numpy as np  # noqa: E402
    import pandas as pd  # noqa: E402

    import macro_risk_os_v2 as eng  # noqa: E402
    from arc.eval import forward_returns  # noqa: E402
    from arc.features.nowcast import activity_nowcast  # noqa: E402
    from arc.research import rank_signals  # noqa: E402

    print("[edge3] initializing engine (PIT features)...", file=sys.stderr)
    e = eng.ProductionEngine(eng.DEFAULT_CONFIG)
    e.initialize()
    feat_df = e.feature_engine.feature_df
    ret_df = e.data_layer.ret_df
    monthly = e.data_layer.monthly
    horizon = eng.DEFAULT_CONFIG.get("prediction_horizon_months", 1)
    idx = feat_df.index

    if "hard" not in ret_df.columns:
        print("[edge3] FATAL: 'hard' not in ret_df — cannot run.", file=sys.stderr)
        sys.exit(1)

    def m(key):
        """Monthly series reindexed onto the feature index (NaN where absent)."""
        s = monthly.get(key)
        return s.reindex(idx) if s is not None else pd.Series(index=idx, dtype="float64")

    # ---- build hard-specific candidate features, each ORIENTED to the tightening prior ----
    # Reminder: hard GAINS when the spread TIGHTENS (d_spread < 0). Orient every feature so a higher
    # value predicts tightening => higher forward hard return.
    new = {}

    # (1) SOVEREIGN CREDIT — tightening-trend continuation + level mean-reversion + a US-HY cross.
    cds = m("cds_5y")
    embi = m("embi_spread")
    hy = m("us_hy_spread")
    #   momentum (continuation): spread FELL recently (diff<0) => tightening trend => negate the diff so
    #   a positive signal = recent tightening, predicting continued tightening => +hard return.
    new["neg_cds_mom3"] = -cds.diff(3)
    new["neg_embi_mom3"] = -embi.diff(3)
    #   level mean-reversion: a WIDE spread (high z) is "cheap credit" that historically tightens back
    #   in; orient so wide spread => + (state the prior — this is the cleanest non-carry sovereign read).
    new["neg_cds_z"] = -_czscore(cds)
    #   cross-asset: BR spread WIDE relative to US HY (BR z - HY z high) => idiosyncratic cheapness that
    #   should converge (tighten) => +. (If it is global risk, US HY moves too and the gap stays flat.)
    new["br_vs_hy_cheap"] = _czscore(cds) - _czscore(hy)

    # (2) FISCAL — worse fiscal => wider spread => negate so a positive signal predicts tightening.
    debt = m("debt_gdp")
    pb = m("primary_balance")
    #   debt ACCELERATION (12m change of debt/GDP rising = deteriorating) => wider => negate.
    new["neg_debt_accel"] = -debt.diff(12)
    #   primary-balance MOMENTUM (improving balance, diff>0, is good fiscal) => tighter => +.
    new["pb_momentum"] = pb.diff(6)

    # (3) EXTERNAL — a stronger external position supports the credit => tighter spread => +.
    bop = m("bop_current")
    tot = m("tot")
    iron = m("iron_ore")
    new["bop_z"] = _czscore(bop)                       # higher current-account balance => + (tighter)
    new["tot_mom6"] = tot.pct_change(6)                # improving terms of trade => + (tighter)
    new["iron_mom6"] = iron.pct_change(6)              # iron-ore tailwind (fiscal+external) => +

    # (4) GLOBAL RISK — risk-off widens EM sovereign spreads => negate (high risk => predict widening).
    vix = m("vix")
    dxy = m("dxy")
    new["neg_vix_z"] = -_czscore(vix)                  # calm (low VIX) => + (tighter)
    new["neg_dxy_mom3"] = -dxy.pct_change(3)           # weaker USD (EM tailwind) => + (tighter)
    new["neg_hy_mom3"] = -hy.diff(3)                   # US HY tightening (risk-on) => + (tighter)

    # (5) MOMENTUM — time-series momentum of the hard return itself (past tightening continues).
    r_hard = ret_df["hard"].reindex(idx)
    new["hard_mom3"] = r_hard.rolling(3).sum()         # signal[t] uses returns realized up to t
    new["hard_mom6"] = r_hard.rolling(6).sum()
    new["hard_mom12"] = r_hard.rolling(12).sum()

    # (6) ACTIVITY NOWCAST — strictly point-in-time mixed-frequency activity factor. PRIOR (opposite of
    # the rate-receiver): stronger Brazil activity => better growth/fiscal trajectory => tighter
    # sovereign spread => +. We do NOT negate it (we gate the prior, we don't assume it).
    have = [k for k in ACTIVITY_KEYS if k in monthly and monthly[k] is not None and len(monthly[k].dropna())]
    print(f"[edge3] nowcast inputs available: {have}", file=sys.stderr)
    factor = activity_nowcast(monthly, ACTIVITY_KEYS, ref_col="ibc_br").reindex(idx)
    new["nowcast"] = factor                            # strong activity => + (tighter spread)
    new["nowcast_mom3"] = factor.diff(3)               # accelerating activity => + (tighter spread)

    feat_df = feat_df.join(pd.DataFrame(new), how="outer")

    # ---- pre-registered candidates for `hard` (economically motivated, NOT a cross-product) ----
    CANDIDATES = {
        "hard": [
            # (1) sovereign credit
            "neg_cds_mom3", "neg_embi_mom3", "neg_cds_z", "br_vs_hy_cheap",
            # (2) fiscal
            "neg_debt_accel", "pb_momentum",
            # (3) external
            "bop_z", "tot_mom6", "iron_mom6",
            # (4) global risk
            "neg_vix_z", "neg_dxy_mom3", "neg_hy_mom3",
            # (5) momentum
            "hard_mom3", "hard_mom6", "hard_mom12",
            # (6) nowcast
            "nowcast", "nowcast_mom3",
        ],
    }
    n_new = sum(len(v) for v in CANDIDATES.values())

    fwd = {"hard": forward_returns(ret_df["hard"], horizon)}

    # ---- CRITICAL: carry-neutralize against the TRUE spread carry, NOT carry_hard (cupom-FX) ----
    # The whole point of this round. carry_hard in the engine is now the spread carry by default
    # (ARC_CARRY_HARD_SPREAD=1), but we recompute it here from embi/10000/12 directly so this script is
    # correct regardless of the engine's carry_hard wiring, and to make the spread-carry choice explicit.
    embi_raw = monthly.get("embi_spread", None)
    if embi_raw is None or len(embi_raw.dropna()) <= 12:
        print("[edge3] FATAL: embi_spread unavailable — cannot build the true spread carry.", file=sys.stderr)
        sys.exit(1)
    carry = {"hard": (embi_raw / 10000.0 / 12.0).reindex(idx)}  # bps spread -> monthly decimal carry

    # Honesty diagnostic (reported, not gated): how different is the true spread carry from the legacy
    # cupom-FX carry? A near-zero correlation is exactly why neutralizing against the wrong one inflated
    # the apparent edge.
    cupom = monthly.get("swap_dixdol_360d", monthly.get("fx_cupom_1m", None))
    spread_vs_cupom = float("nan")
    if cupom is not None and len(cupom.dropna()) > 12:
        cmp = pd.concat([carry["hard"], (cupom / 100.0 / 12.0).reindex(idx)], axis=1).dropna()
        if len(cmp) > 12:
            spread_vs_cupom = float(np.corrcoef(cmp.iloc[:, 0], cmp.iloc[:, 1])[0, 1])

    out = rank_signals(CANDIDATES, feat_df, fwd, carry)
    cumulative = PRIOR_HYPOTHESES + out["n_hypotheses"]

    report_path = os.path.join(eng.OUTPUT_DIR, "edge_search_hard.json")
    out["true_spread_carry_vs_cupom_corr"] = spread_vs_cupom
    out["cumulative_hypotheses"] = cumulative
    with open(report_path, "w") as f:
        json.dump(out, f, indent=2, default=float)

    print("\n" + "=" * 100)
    print("PHASE 4.5 — EDGE SEARCH ROUND 3: 'HARD' SOVEREIGN-SPREAD RECEIVER (gated, TRUE spread carry)")
    print("=" * 100)
    print(f"  carry = embi/10000/12 (spread carry).  corr(true spread carry, legacy cupom carry) = "
          f"{spread_vs_cupom:+.2f}")
    print(f"  new hypotheses={n_new}   cumulative (rounds 1+2+3)={cumulative}")
    print(f"  {'inst':5s} {'feature':16s} {'n':>4s} {'IC':>7s} {'cnIC':>7s} {'H1':>7s} {'H2':>7s} "
          f"{'decay':>7s} {'OOSm':>7s} {'OOSmin':>7s}  verdict")
    print("  " + "-" * 104)
    for r in out["results"]:
        if r.get("n", 0) < 1 or "ic" not in r:
            print(f"  {r['instrument']:5s} {r['feature']:16s}  --  {'; '.join(r.get('reasons', []))}")
            continue
        v = "PASS" if r["passed"] else "fail: " + "; ".join(r["reasons"])
        print(f"  {r['instrument']:5s} {r['feature']:16s} {r['n']:>4d} {r['ic']:+.3f} "
              f"{r['carry_neutral_ic']:+.3f} {r['h1']:+.3f} {r['h2']:+.3f} {r['decay']:+.3f} "
              f"{r['refit_oos_mean']:+.3f} {r['refit_oos_min']:+.3f}  {v}")

    if out["survivors"]:
        print("\n  SURVIVORS (candidates to adversarially re-verify, NOT promotions):")
        for r in out["survivors"]:
            print(f"    {r['instrument']}/{r['feature']}: cnIC={r['carry_neutral_ic']:+.3f} "
                  f"H2={r['h2']:+.3f} refit-OOS={r['refit_oos_mean']:+.3f}")
        print(f"\n  NOTE: ~{cumulative} cumulative hypotheses => expect ~{cumulative*0.05:.0f} false "
              f"positives at 5%. The headline 'hard refit-OOS ~0.33' was carry-in-disguise: a survivor "
              f"here is neutral to the TRUE spread carry, but must still clear deflation on a single-use "
              f"forward holdout (paper) before any promotion.")
    else:
        print("\n  NO SURVIVORS — once neutralized against the TRUE spread carry, no `hard` signal clears "
              "the gate. This is the expected, honest result if the ~0.33 IC was spread carry.")
    print(f"\n  report: {report_path}")


if __name__ == "__main__":
    main()
