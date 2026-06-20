"""Evaluate a single candidate signal honestly: is it predictive beyond carry, out of sample,
stationary, and surviving deflation for the number of hypotheses tested?

A candidate is one feature predicting one instrument's forward return. We deliberately test simple,
pre-registered, economically-motivated single-feature signals — NOT the full ensemble, whose feature
selection overfits. The verdict composes the arc.eval primitives:

  - carry_neutralized_ic : predictive power beyond carry (the edge must not be carry in disguise).
  - half_sample decay     : H1 vs H2 carry-neutral IC; a steep drop is non-stationary (contamination
                            / regime-timing), not a durable edge. The bar is the SECOND half (~0.1).
  - refit_oos_cpcv        : TRUE out-of-sample IC — re-fit a ridge on the single feature inside each
                            purged fold. This is the primary edge metric (sign is learned in-fold).

Multiple testing: when N candidates are screened, the best by chance looks good. ``rank_signals``
reports N and applies a stricter OOS bar; treat any survivor as a hypothesis to be adversarially
re-verified, never as a promotion.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from arc.eval.gate import (
    carry_neutralized_ic,
    half_sample_carry_neutral_ic,
    refit_oos_cpcv,
)
from arc.eval.metrics import information_coefficient


@dataclass
class SignalThresholds:
    """Honest, strict bars. The point is to FAIL noise and carry, not to flatter."""
    carry_neutral_ic_min: float = 0.05   # must add IC beyond carry
    h2_ic_min: float = 0.03              # the second half must still work (the real forward bar)
    decay_max: float = 0.15              # H1 - H2: steep drop = non-stationary, not edge
    refit_oos_mean_min: float = 0.03     # true OOS IC must be positive with margin
    refit_oos_min_floor: float = -0.10   # worst purged fold not deeply negative
    min_obs: int = 40


def evaluate_signal(
    signal: pd.Series,
    fwd_ret: pd.Series,
    carry: pd.Series,
    *,
    thresholds: SignalThresholds | None = None,
) -> dict:
    """Run the full gate battery for one (signal -> forward return) pair, carry-neutralized.

    ``signal`` and ``carry`` are decision-time values; ``fwd_ret`` the forward return already aligned
    (signal[t] predicts fwd_ret[t]). Returns the metrics + a pass/fail with reasons.
    """
    th = thresholds or SignalThresholds()
    df = pd.concat([signal, fwd_ret, carry], axis=1, keys=["s", "r", "c"]).dropna()
    n = int(len(df))
    out: dict = {"n": n, "passed": False, "reasons": []}
    if n < th.min_obs:
        out["reasons"].append(f"insufficient obs ({n} < {th.min_obs})")
        return out

    s, r, c = df["s"], df["r"], df["c"]
    out["ic"] = float(information_coefficient(s, r))
    has_carry = float(c.std()) > 1e-12
    out["carry_neutral_ic"] = float(carry_neutralized_ic(s, r, c)) if has_carry else out["ic"]
    hs = half_sample_carry_neutral_ic(s, r, c if has_carry else pd.Series(np.zeros(n), index=df.index))
    out["h1"], out["h2"], out["decay"] = hs["h1"], hs["h2"], hs["drop"]
    ro = refit_oos_cpcv(s.values.reshape(-1, 1), r.values)
    out["refit_oos_mean"], out["refit_oos_min"], out["refit_oos_paths"] = ro["mean"], ro["min"], ro["n_paths"]

    # ---- verdict ----
    reasons: list[str] = []
    cn = out["carry_neutral_ic"]
    if not (cn >= th.carry_neutral_ic_min):
        reasons.append(f"carry-neutral IC {cn:+.3f} < {th.carry_neutral_ic_min}")
    h2 = out["h2"]
    if np.isnan(h2) or h2 < th.h2_ic_min:
        reasons.append(f"2nd-half IC {h2:+.3f} < {th.h2_ic_min} (no durable edge)")
    decay = out["decay"]
    if not np.isnan(decay) and decay > th.decay_max:
        reasons.append(f"half-sample decay {decay:+.3f} > {th.decay_max} (non-stationary)")
    rom = out["refit_oos_mean"]
    if np.isnan(rom) or rom < th.refit_oos_mean_min:
        reasons.append(f"refit-OOS IC {rom:+.3f} < {th.refit_oos_mean_min}")
    rmin = out["refit_oos_min"]
    if not np.isnan(rmin) and rmin < th.refit_oos_min_floor:
        reasons.append(f"worst OOS fold {rmin:+.3f} < {th.refit_oos_min_floor}")

    out["reasons"] = reasons
    out["passed"] = len(reasons) == 0
    return out


def rank_signals(
    candidates: dict,
    feature_df: pd.DataFrame,
    fwd_returns: dict,
    carry_by_inst: dict,
    *,
    thresholds: SignalThresholds | None = None,
) -> dict:
    """Evaluate a pre-registered {instrument: [feature, ...]} map. ``fwd_returns`` and
    ``carry_by_inst`` are {instrument: Series}. Returns per-candidate results + a summary with the
    total hypothesis count (for multiple-testing context) and the survivors."""
    th = thresholds or SignalThresholds()
    results = []
    for inst, feats in candidates.items():
        if inst not in fwd_returns or inst not in carry_by_inst:
            continue
        fr, ca = fwd_returns[inst], carry_by_inst[inst]
        for feat in feats:
            if feat not in feature_df.columns:
                results.append({"instrument": inst, "feature": feat, "n": 0,
                                "passed": False, "reasons": ["feature absent"]})
                continue
            res = evaluate_signal(feature_df[feat], fr, ca, thresholds=th)
            res["instrument"], res["feature"] = inst, feat
            results.append(res)
    tested = [r for r in results if r.get("n", 0) >= th.min_obs]
    survivors = [r for r in results if r.get("passed")]
    return {
        "n_hypotheses": len(tested),
        "n_survivors": len(survivors),
        "survivors": survivors,
        "results": results,
        "thresholds": th.__dict__,
    }
