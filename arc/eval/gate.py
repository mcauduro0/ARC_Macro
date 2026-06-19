"""Promotion gate — is the overlay real alpha, or carry wearing a signal costume?

The audit's central warning: the forward-target IC of ~0.64 (belly/long) is almost certainly
carry-dominance plus residual leakage, not skill. This module is the ruler that deflates it. It
composes the arc.eval primitives into a single, honest verdict:

  - carry_neutralized_ic : IC of the prediction vs realized AFTER regressing carry out of BOTH.
    If the signal IC collapses once carry is removed, the "edge" was carry.
  - carry_only_ic        : IC of the naive carry signal itself — the benchmark the model must beat.
  - carry_only_portfolio : a cross-sectional carry-weighted return stream — the strategy-level
    benchmark. If the overlay's Sharpe does not beat carry-only after costs, it is carry.
  - cpcv_ic              : IC across combinatorial purged folds — is the IC stable, or carried by a
    few periods? (dispersion + worst-fold, not one in-sample number).
  - sharpe_stats         : Deflated Sharpe Ratio and PSR on the overlay returns, deflated by the
    REAL number of trials (the ~30 re-scored tuning iterations) via the GovernanceLedger.

It reports the numbers and a PASS/FAIL with explicit reasons. It does not flatter them. PBO is only
computed when a trial-return matrix is supplied (it requires the per-config sweep); otherwise it is
reported as unavailable rather than faked.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Optional, Sequence

import numpy as np
import pandas as pd

from arc.eval.cv import combinatorial_purged_splits
from arc.eval.metrics import (
    deflated_sharpe_ratio,
    information_coefficient,
    newey_west_tstat,
    probabilistic_sharpe_ratio,
    probability_of_backtest_overfitting,
)


# --------------------------------------------------------------------------------------------
# building blocks
# --------------------------------------------------------------------------------------------
def residualize(y, x) -> pd.Series:
    """Residual of ``y`` after OLS on ``x`` (with intercept). NaNs dropped pairwise; the result is
    reindexed back to ``y``'s positions. Used to strip the carry component out of a series."""
    ys = pd.Series(np.asarray(y, dtype="float64")).reset_index(drop=True)
    xs = pd.Series(np.asarray(x, dtype="float64")).reset_index(drop=True)
    df = pd.concat([ys, xs], axis=1).dropna()
    if len(df) < 3 or df.iloc[:, 1].std() < 1e-12:
        return ys - ys.mean()
    X = np.column_stack([np.ones(len(df)), df.iloc[:, 1].to_numpy()])
    beta, *_ = np.linalg.lstsq(X, df.iloc[:, 0].to_numpy(), rcond=None)
    resid = pd.Series(np.nan, index=ys.index)
    resid.loc[df.index] = df.iloc[:, 0].to_numpy() - X @ beta
    return resid


def carry_neutralized_ic(pred, realized, carry, method: str = "spearman") -> float:
    """IC(pred ⟂ carry, realized ⟂ carry): the signal's predictive power *beyond* carry."""
    return information_coefficient(residualize(pred, carry), residualize(realized, carry), method=method)


def carry_only_ic(carry, realized, method: str = "spearman") -> float:
    """IC of the naive carry signal vs realized — the benchmark to beat."""
    return information_coefficient(carry, realized, method=method)


def cpcv_ic(pred, realized, n_groups: int = 6, n_test_groups: int = 2,
            embargo: float = 0.02, method: str = "spearman") -> dict:
    """Distribution of IC over combinatorial purged folds for one (pred, realized) pair already in
    forward shape (pred[t] predicts realized[t]). Reports mean / std / min (worst fold) / n_paths.

    This is an IC-stability check across leakage-free sub-periods, not a refit-OOS test (the engine
    fit the model upstream); a high mean with a deeply negative worst fold flags period-concentration.
    """
    p = np.asarray(pred, dtype="float64")
    r = np.asarray(realized, dtype="float64")
    n = len(p)
    empty = {"mean": float("nan"), "std": float("nan"), "min": float("nan"), "n_paths": 0}
    if n < n_groups * 3:
        return empty
    ics = []
    for _, test_idx in combinatorial_purged_splits(n, n_groups=n_groups,
                                                   n_test_groups=n_test_groups, embargo=embargo):
        ic = information_coefficient(p[test_idx], r[test_idx], method=method)
        if not np.isnan(ic):
            ics.append(float(ic))
    if not ics:
        return empty
    return {"mean": float(np.mean(ics)), "std": float(np.std(ics)),
            "min": float(np.min(ics)), "n_paths": len(ics)}


def carry_only_portfolio(carry_panel: pd.DataFrame, realized_panel: pd.DataFrame) -> pd.Series:
    """Strategy-level carry benchmark: each period, weight instruments by cross-sectionally
    demeaned, gross-normalized carry, then earn the realized returns. No look-ahead — carry[t] is
    the decision-time signal, realized[t] the forward return already aligned to it."""
    c = carry_panel.reindex(columns=realized_panel.columns)
    common = c.index.intersection(realized_panel.index)
    c = c.loc[common]
    r = realized_panel.loc[common]
    # cross-sectional demean -> dollar-neutral tilt; normalize by gross to bound leverage
    w = c.sub(c.mean(axis=1), axis=0)
    gross = w.abs().sum(axis=1).replace(0.0, np.nan)
    w = w.div(gross, axis=0).fillna(0.0)
    return (w * r).sum(axis=1)


def sharpe_stats(returns, n_trials: int, sr_std: float = 1.0, periods_per_year: int = 12) -> dict:
    """Per-period Sharpe with PSR (vs 0) and DSR (deflated by ``n_trials``). ``returns`` are
    per-period (monthly) overlay returns; ``sr_std`` is the across-trials Sharpe dispersion."""
    from scipy.stats import kurtosis, skew

    a = np.asarray(returns, dtype="float64")
    a = a[~np.isnan(a)]
    n = len(a)
    nan = {"sr_period": float("nan"), "sr_annual": float("nan"), "n": n,
           "n_trials": n_trials, "psr_vs_0": float("nan"), "dsr": float("nan"),
           "skew": float("nan"), "kurt": float("nan")}
    if n < 6:
        return nan
    sd = a.std(ddof=1)
    if sd <= 0:
        return nan
    sr = a.mean() / sd
    sk = float(skew(a))
    ku = float(kurtosis(a, fisher=False))  # non-excess (normal = 3)
    return {
        "sr_period": float(sr),
        "sr_annual": float(sr * np.sqrt(periods_per_year)),
        "n": n,
        "n_trials": int(n_trials),
        "psr_vs_0": float(probabilistic_sharpe_ratio(sr, n, sk, ku, 0.0)),
        "dsr": float(deflated_sharpe_ratio(sr, n, n_trials, sr_std, skew=sk, kurt=ku)),
        "skew": sk,
        "kurt": ku,
    }


# --------------------------------------------------------------------------------------------
# verdict
# --------------------------------------------------------------------------------------------
@dataclass
class GateThresholds:
    dsr_min: float = 0.95          # overlay Sharpe must survive deflation vs n_trials
    ic_t_min: float = 2.0          # Newey-West t-stat of carry-neutralized IC across instruments
    carry_neutral_ic_min: float = 0.02  # mean carry-neutralized IC must clear this margin
    sharpe_beat_carry: bool = True  # overlay Sharpe must exceed carry-only Sharpe
    cpcv_worst_min: float = -0.10   # worst purged-fold IC floor (period-concentration guard)


@dataclass
class GateVerdict:
    passed: bool
    reasons: list = field(default_factory=list)
    overlay: dict = field(default_factory=dict)
    carry_only: dict = field(default_factory=dict)
    per_instrument: dict = field(default_factory=dict)
    aggregate: dict = field(default_factory=dict)
    pbo: Optional[float] = None

    def to_dict(self) -> dict:
        return {
            "passed": self.passed,
            "reasons": self.reasons,
            "overlay": self.overlay,
            "carry_only": self.carry_only,
            "aggregate": self.aggregate,
            "per_instrument": self.per_instrument,
            "pbo": self.pbo,
        }


def promotion_report(
    *,
    pred_panel: pd.DataFrame,
    realized_panel: pd.DataFrame,
    carry_panel: pd.DataFrame,
    overlay_returns,
    n_trials: int,
    sr_std: float = 1.0,
    trial_perf_matrix: Optional[np.ndarray] = None,
    thresholds: Optional[GateThresholds] = None,
) -> GateVerdict:
    """Assemble the full gate verdict.

    Panels are DataFrames indexed by date, columns = instruments, already forward-aligned
    (pred[t]/carry[t] predict realized[t]). ``overlay_returns`` is the per-period overlay return
    stream. ``n_trials`` is the real trial count (e.g. from the GovernanceLedger). ``trial_perf_matrix``
    (T x N per-period returns for N candidate configs), if given, drives PBO; otherwise PBO is N/A.
    """
    th = thresholds or GateThresholds()
    reasons: list = []

    overlay = sharpe_stats(overlay_returns, n_trials=n_trials, sr_std=sr_std)

    carry_ret = carry_only_portfolio(carry_panel, realized_panel)
    carry_only = sharpe_stats(carry_ret, n_trials=1, sr_std=sr_std)

    per_inst: dict = {}
    insts = [c for c in pred_panel.columns if c in realized_panel.columns and c in carry_panel.columns]
    for inst in insts:
        df = pd.concat(
            [pred_panel[inst], realized_panel[inst], carry_panel[inst]], axis=1, keys=["p", "r", "c"]
        ).dropna()
        if len(df) < 12:
            per_inst[inst] = {"n": len(df), "ic": float("nan"), "carry_neutral_ic": float("nan"),
                              "carry_only_ic": float("nan"), "cpcv": {}}
            continue
        ic = information_coefficient(df["p"], df["r"])
        cn_ic = carry_neutralized_ic(df["p"], df["r"], df["c"])
        co_ic = carry_only_ic(df["c"], df["r"])
        cp = cpcv_ic(df["p"].to_numpy(), df["r"].to_numpy())
        per_inst[inst] = {"n": int(len(df)), "ic": ic, "carry_neutral_ic": cn_ic,
                          "carry_only_ic": co_ic, "cpcv": cp}

    cn_ics = [v["carry_neutral_ic"] for v in per_inst.values() if not np.isnan(v.get("carry_neutral_ic", np.nan))]
    cpcv_worst = [v["cpcv"].get("min", np.nan) for v in per_inst.values() if v.get("cpcv")]
    cpcv_worst = [x for x in cpcv_worst if not np.isnan(x)]
    agg = {
        "mean_carry_neutral_ic": float(np.mean(cn_ics)) if cn_ics else float("nan"),
        "carry_neutral_ic_t": float(newey_west_tstat(cn_ics)) if len(cn_ics) >= 3 else float("nan"),
        "n_instruments": len(cn_ics),
        "worst_cpcv_ic": float(np.min(cpcv_worst)) if cpcv_worst else float("nan"),
    }

    pbo = None
    if trial_perf_matrix is not None:
        try:
            pbo = float(probability_of_backtest_overfitting(trial_perf_matrix))
        except Exception:
            pbo = None

    # ---- decision ----
    dsr_ok = not np.isnan(overlay["dsr"]) and overlay["dsr"] >= th.dsr_min
    if not dsr_ok:
        reasons.append(f"DSR {overlay['dsr']:.3f} < {th.dsr_min} (overlay Sharpe not safe vs {n_trials} trials)")

    cn_mean = agg["mean_carry_neutral_ic"]
    cn_ok = not np.isnan(cn_mean) and cn_mean >= th.carry_neutral_ic_min
    if not cn_ok:
        reasons.append(f"mean carry-neutralized IC {cn_mean:.4f} < {th.carry_neutral_ic_min} (edge is carry)")

    t_ok = not np.isnan(agg["carry_neutral_ic_t"]) and agg["carry_neutral_ic_t"] >= th.ic_t_min
    if not t_ok:
        reasons.append(f"carry-neutral IC t-stat {agg['carry_neutral_ic_t']:.2f} < {th.ic_t_min}")

    beat_ok = True
    if th.sharpe_beat_carry:
        ov_sr, ca_sr = overlay.get("sr_annual", np.nan), carry_only.get("sr_annual", np.nan)
        beat_ok = not np.isnan(ov_sr) and not np.isnan(ca_sr) and ov_sr > ca_sr
        if not beat_ok:
            reasons.append(f"overlay Sharpe {ov_sr:.2f} does not beat carry-only {ca_sr:.2f}")

    cpcv_ok = np.isnan(agg["worst_cpcv_ic"]) or agg["worst_cpcv_ic"] >= th.cpcv_worst_min
    if not cpcv_ok:
        reasons.append(f"worst purged-fold IC {agg['worst_cpcv_ic']:.3f} < {th.cpcv_worst_min} (period-concentrated)")

    passed = dsr_ok and cn_ok and t_ok and beat_ok and cpcv_ok
    if passed:
        reasons.append("PASS: overlay survives deflation and adds IC beyond carry")

    return GateVerdict(passed=passed, reasons=reasons, overlay=overlay, carry_only=carry_only,
                       per_instrument=per_inst, aggregate=agg, pbo=pbo)
