"""Live PRE-TRADE risk gate for the paper loop (Phase 7.4 / Phase 6 wiring).

What it is: a causal, operational sizing overlay that caps leverage so the SIZED book's one-month-ahead
tail risk (VaR / ES) stays within a pre-committed ABSOLUTE loss budget — on TOP of the existing vol
target. The applied leverage is ``min(vol-target leverage, VaR-limit leverage, ES-limit leverage)``, so:
  - in normal regimes the vol target binds (the gate is transparent), and
  - when the sleeve's tail fattens beyond Gaussian (Cornish-Fisher VaR jumps on negative skew / excess
    kurtosis) the gate CUTS size — catching tail risk the vol target alone misses.

What it is NOT: an alpha signal. It only bounds losses. And — the non-negotiable invariant — it touches
ONLY the operational sizing (the Proposal's leverage / sized_exposure). It NEVER changes the `frozen`
(scored holdout) or the raw `live` ledger positions: the verdict's input is untouched. Risk is estimated
from the strategy's own causal realized return history (the raw `frozen` sleeve stream — operations may
READ the holdout's realized returns to size; only the reverse, operations changing the score, is forbidden).

Both gates inherit the var_es / covariance sign + causality contracts (positive-loss convention; the
covariance forecast Σ_{T+1|T} uses only rows ≤ T). With too little history the gate is INACTIVE (returns
the requested leverage unchanged) and says so — tails need data before they can bind.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd

from arc.risk.covariance import dcc_garch_cov, ewma_cov
from arc.risk.var_es import (
    cornish_fisher_var,
    historical_es,
    historical_var,
    parametric_es,
    parametric_var,
    portfolio_var,
)


@dataclass(frozen=True)
class RiskLimits:
    """A pre-committed ABSOLUTE monthly loss budget for the SIZED book (positive-loss fractions).

    Defaults are a TAIL overlay calibrated to sit just above a 10%-annual-vol book's Gaussian tail
    (monthly σ≈2.9% ⇒ 95% VaR≈4.8%, ES≈6.0%), so the gate is transparent in normal regimes and bites only
    when fat tails push the Cornish-Fisher VaR above the budget. Absolute (not vol-scaled) by design: a
    VaR limit is a loss budget, so a higher vol target makes the gate bind sooner — correct risk control."""

    var_limit: float = 0.055      # max monthly VaR (positive loss) of the sized book at 1-alpha
    es_limit: float = 0.075       # max monthly ES (positive loss)
    alpha: float = 0.05           # tail probability (95% level)
    min_months: int = 24          # causal history required before the gate may bind (tails need data)
    var_method: str = "cornish_fisher"  # "cornish_fisher" | "historical" | "parametric"


@dataclass(frozen=True)
class RiskGateState:
    """The gate's decision. ``applied_leverage`` is what the loop should size with; everything else is the
    explanation (which limit bound, the per-unit and at-applied tail estimates)."""

    active: bool
    requested_leverage: float
    applied_leverage: float
    var_per_unit: float           # VaR of the book at leverage 1 (positive loss)
    es_per_unit: float
    var_at_applied: float         # VaR of the sized book at applied_leverage
    es_at_applied: float
    binding: str                  # "vol_target" | "var_limit" | "es_limit" | "inactive"
    reasons: list = field(default_factory=list)


def _var_per_unit(returns: np.ndarray, *, alpha: float, method: str) -> float:
    if method == "historical":
        return historical_var(returns, alpha=alpha)
    if method == "parametric":
        r = returns[np.isfinite(returns)]
        sd = float(np.std(r, ddof=1)) if r.size > 1 else 0.0
        return parametric_var(float(np.mean(r)) if r.size else 0.0, sd, alpha=alpha)
    return cornish_fisher_var(returns, alpha=alpha)  # default: fat-tail aware


def _cap(requested: float, lev_var: float, lev_es: float):
    """Take the binding (smallest) of the three leverage caps. Leverage is a positive magnitude."""
    req = abs(float(requested))
    candidates = {"vol_target": req, "var_limit": lev_var, "es_limit": lev_es}
    binding = min(candidates, key=lambda k: candidates[k])
    return binding, float(candidates[binding])


def _inactive(req: float, reason: str) -> RiskGateState:
    return RiskGateState(active=False, requested_leverage=req,
                         applied_leverage=(req if np.isfinite(req) else float("nan")),
                         var_per_unit=float("nan"), es_per_unit=float("nan"),
                         var_at_applied=float("nan"), es_at_applied=float("nan"),
                         binding="inactive", reasons=[reason])


def pretrade_leverage_gate(
    returns,
    *,
    requested_leverage: float,
    limits: RiskLimits = RiskLimits(),
) -> RiskGateState:
    """Cap a single sleeve's vol-target leverage so the sized book's monthly VaR/ES stay within budget.

    ``returns`` is the sleeve's causal realized return history (leverage-1 stream). Returns a
    ``RiskGateState`` whose ``applied_leverage = min(requested, var_limit/VaR_per_unit, es_limit/ES_per_unit)``.
    Inactive (returns ``requested`` unchanged) when there is too little history or no requested leverage.
    A strongly positive mean can make a tail estimate ≤ 0 (mathematically valid) — that simply imposes no
    cap from that side."""
    r = pd.Series(returns, dtype="float64").dropna()
    req = float(requested_leverage)
    if not np.isfinite(req):
        return _inactive(req, "no requested leverage (vol target undefined)")
    if len(r) < int(limits.min_months):
        return _inactive(req, f"insufficient history ({len(r)} < {limits.min_months} months) — gate inactive")

    a = float(limits.alpha)
    rv = r.to_numpy()
    var_u = _var_per_unit(rv, alpha=a, method=limits.var_method)
    es_u = historical_es(rv, alpha=a)
    lev_var = (float(limits.var_limit) / var_u) if var_u > 0 else float("inf")
    lev_es = (float(limits.es_limit) / es_u) if es_u > 0 else float("inf")

    binding, applied_mag = _cap(req, lev_var, lev_es)
    reasons = []
    if binding != "vol_target":
        reasons.append(
            f"{binding} binds: leverage {abs(req):.2f} -> {applied_mag:.2f} (per-unit VaR {var_u:.4f}, "
            f"ES {es_u:.4f}; budget VaR {limits.var_limit} / ES {limits.es_limit})")
    return RiskGateState(active=True, requested_leverage=req, applied_leverage=applied_mag,
                         var_per_unit=float(var_u), es_per_unit=float(es_u),
                         var_at_applied=float(applied_mag * var_u), es_at_applied=float(applied_mag * es_u),
                         binding=binding, reasons=reasons)


def portfolio_pretrade_gate(
    returns_panel,
    weights,
    *,
    requested_leverage: float,
    limits: RiskLimits = RiskLimits(),
    cov_method: str = "dcc",
) -> RiskGateState:
    """Cap a multi-sleeve BOOK's leverage using the causal covariance FORECAST (DCC-GARCH or EWMA).

    ``returns_panel`` is the members' causal return panel; ``weights`` the book weights at leverage 1
    (e.g. equal). VaR/ES are the parametric (Gaussian) portfolio tail from Σ_{T+1|T} = ``dcc_garch_cov`` /
    ``ewma_cov`` — i.e. the cross-sleeve correlation IS used. Same min(vol-target, VaR, ES) cap as the
    single gate. Inactive with too little history."""
    df = pd.DataFrame(returns_panel).dropna()
    w = np.asarray(weights, dtype="float64").ravel()
    req = float(requested_leverage)
    if not np.isfinite(req):
        return _inactive(req, "no requested leverage")
    if len(df) < int(limits.min_months) or df.shape[1] < 1:
        return _inactive(req, f"insufficient history ({len(df)} < {limits.min_months} months) — gate inactive")

    cov = (ewma_cov(df).to_numpy() if cov_method == "ewma" else dcc_garch_cov(df).to_numpy())
    a = float(limits.alpha)
    var_u = portfolio_var(w, cov, alpha=a)
    sigma_p = float(np.sqrt(max(float(w @ cov @ w), 0.0)))
    es_u = parametric_es(0.0, sigma_p, alpha=a)
    lev_var = (float(limits.var_limit) / var_u) if var_u > 0 else float("inf")
    lev_es = (float(limits.es_limit) / es_u) if es_u > 0 else float("inf")

    binding, applied_mag = _cap(req, lev_var, lev_es)
    reasons = []
    if binding != "vol_target":
        reasons.append(
            f"{binding} binds (book): leverage {abs(req):.2f} -> {applied_mag:.2f} (per-unit portfolio VaR "
            f"{var_u:.4f}, ES {es_u:.4f}; cov={cov_method}; budget VaR {limits.var_limit} / ES {limits.es_limit})")
    return RiskGateState(active=True, requested_leverage=req, applied_leverage=applied_mag,
                         var_per_unit=float(var_u), es_per_unit=float(es_u),
                         var_at_applied=float(applied_mag * var_u), es_at_applied=float(applied_mag * es_u),
                         binding=binding, reasons=reasons)


__all__ = ["RiskLimits", "RiskGateState", "pretrade_leverage_gate", "portfolio_pretrade_gate"]
