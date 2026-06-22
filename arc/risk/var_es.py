"""Value-at-Risk / Expected-Shortfall and a pre-trade VaR gate (pure numpy/scipy).

SIGN CONVENTION (read this first)
---------------------------------
All VaR/ES quantities returned here are POSITIVE numbers expressing a LOSS
MAGNITUDE over the holding period at confidence level ``1 - alpha``.

Let ``r`` be the (arithmetic) return of the book.  Define the loss as ``L = -r``.
For a tail probability ``alpha`` (e.g. 0.05 for the 95% level):

    VaR_alpha = -quantile_alpha(r) = quantile_{1-alpha}(L)

i.e. VaR is the loss that is exceeded with probability ``alpha``.  A return
distribution centred at zero with unit vol has a 5% VaR of ~1.645 (one-sided
Gaussian z), reported here as ``+1.645``.

    ES_alpha = -E[ r | r <= quantile_alpha(r) ] = E[ L | L >= VaR ]

ES (a.k.a. CVaR) is the mean loss conditional on being in the alpha tail and is
therefore ALWAYS >= VaR.

A profitable mean shifts the distribution right and REDUCES both VaR and ES;
with a large enough positive ``mu`` the parametric VaR can go negative — that is
mathematically correct (the alpha-quantile of returns is itself positive) and we
do NOT clip it, so the numbers stay self-consistent.  The pre-trade gate below
compares VaR against a positive ``var_limit`` and rejects only when the loss
estimate exceeds the limit.

Monotonicity (guaranteed by construction): smaller ``alpha`` => deeper tail =>
LARGER VaR and ES.

Everything is static (no time index) and stateless: callers feed in either a
realised-return sample or moments / a covariance, so there is no causality
concern in this module — the caller is responsible for using only data with
index <= t when estimating those inputs.
"""

from __future__ import annotations

from typing import Optional

import numpy as np
from scipy.stats import norm

__all__ = [
    "historical_var",
    "historical_es",
    "parametric_var",
    "parametric_es",
    "cornish_fisher_var",
    "portfolio_var",
    "pretrade_var_gate",
]


def _clean_alpha(alpha: float) -> float:
    a = float(alpha)
    if not (0.0 < a < 1.0):
        raise ValueError(f"alpha must be in (0, 1), got {alpha!r}")
    return a


def _clean_sample(returns) -> np.ndarray:
    r = np.asarray(returns, dtype=float).ravel()
    r = r[np.isfinite(r)]
    if r.size == 0:
        raise ValueError("returns sample is empty after dropping non-finite values")
    return r


# --------------------------------------------------------------------------- #
# Non-parametric (empirical) estimators
# --------------------------------------------------------------------------- #
def historical_var(returns, *, alpha: float = 0.05) -> float:
    """Empirical (historical-simulation) VaR as a positive loss.

    VaR = -quantile_alpha(returns).  Uses the lower-interpolated empirical
    quantile of the return sample.
    """
    a = _clean_alpha(alpha)
    r = _clean_sample(returns)
    q = float(np.quantile(r, a, method="lower"))
    return -q


def historical_es(returns, *, alpha: float = 0.05) -> float:
    """Empirical Expected Shortfall (CVaR) as a positive loss.

    ES = -mean(returns that are <= the alpha-quantile).  If no observation falls
    strictly at/under the (lower-interpolated) quantile threshold — which can
    happen only for tiny samples — we fall back to the single worst loss, so the
    relation ES >= VaR is preserved.
    """
    a = _clean_alpha(alpha)
    r = _clean_sample(returns)
    q = float(np.quantile(r, a, method="lower"))
    tail = r[r <= q]
    if tail.size == 0:
        tail = np.array([r.min()])
    return -float(tail.mean())


# --------------------------------------------------------------------------- #
# Parametric (Gaussian) estimators
# --------------------------------------------------------------------------- #
def parametric_var(mu: float, sigma: float, *, alpha: float = 0.05) -> float:
    """Gaussian VaR as a positive loss: VaR = -(mu + sigma * z_alpha).

    ``z_alpha = Phi^{-1}(alpha)`` is negative for alpha < 0.5, so for mu=0 this
    returns ``-sigma * z_alpha = sigma * |z_alpha|`` (e.g. 1.645*sigma at 5%).
    A degenerate ``sigma == 0`` yields ``-mu``.
    """
    a = _clean_alpha(alpha)
    s = float(sigma)
    if s < 0:
        raise ValueError(f"sigma must be non-negative, got {sigma!r}")
    z = norm.ppf(a)
    return -(float(mu) + s * z)


def parametric_es(mu: float, sigma: float, *, alpha: float = 0.05) -> float:
    """Gaussian Expected Shortfall as a positive loss.

    ES = -mu + sigma * phi(z_alpha) / alpha, where phi is the standard-normal
    pdf and z_alpha = Phi^{-1}(alpha).  For mu=0, sigma=1, alpha=0.05 this is
    ~2.063.  Always >= the Gaussian VaR.  Degenerate ``sigma == 0`` yields -mu.
    """
    a = _clean_alpha(alpha)
    s = float(sigma)
    if s < 0:
        raise ValueError(f"sigma must be non-negative, got {sigma!r}")
    z = norm.ppf(a)
    return -float(mu) + s * float(norm.pdf(z)) / a


def cornish_fisher_var(returns, *, alpha: float = 0.05) -> float:
    """Cornish-Fisher (modified) VaR: Gaussian quantile adjusted for skew/kurt.

    The standard-normal quantile ``z`` is expanded to

        z_cf = z + (z^2 - 1) S / 6
                 + (z^3 - 3z) K / 24
                 - (2 z^3 - 5 z) S^2 / 36

    where S is the sample skewness and K the EXCESS kurtosis of ``returns``.
    VaR = -(mu + sigma * z_cf), a positive loss.  Negative left-skew / fat tails
    push z_cf more negative and so INCREASE the reported VaR relative to the
    plain Gaussian.  Needs at least 2 observations for a sample std; for a
    constant sample (sigma == 0) it returns ``-mu``.
    """
    a = _clean_alpha(alpha)
    r = _clean_sample(returns)
    mu = float(r.mean())
    sigma = float(r.std(ddof=1)) if r.size > 1 else 0.0
    if sigma == 0.0:
        return -mu
    rs = (r - mu) / sigma
    S = float(np.mean(rs ** 3))               # skewness
    K = float(np.mean(rs ** 4) - 3.0)         # excess kurtosis
    z = norm.ppf(a)
    z_cf = (
        z
        + (z ** 2 - 1.0) * S / 6.0
        + (z ** 3 - 3.0 * z) * K / 24.0
        - (2.0 * z ** 3 - 5.0 * z) * (S ** 2) / 36.0
    )
    return -(mu + sigma * z_cf)


# --------------------------------------------------------------------------- #
# Portfolio-level parametric VaR and the pre-trade gate
# --------------------------------------------------------------------------- #
def portfolio_var(
    weights,
    cov,
    *,
    alpha: float = 0.05,
    mu: Optional[np.ndarray] = None,
) -> float:
    """Parametric (Gaussian) portfolio VaR from ``w' Σ w``, a positive loss.

    Portfolio vol = sqrt(w' Σ w); portfolio mean = w'mu (0 if mu is None).  The
    result is exactly ``parametric_var(w'mu, sqrt(w'Σw), alpha=alpha)`` so a
    single-asset book reduces to the scalar parametric VaR.  The covariance is
    symmetrised before use; a tiny negative ``w'Σw`` from round-off is floored
    at 0 (degenerate zero-vol => VaR = -w'mu).
    """
    a = _clean_alpha(alpha)
    w = np.asarray(weights, dtype=float).ravel()
    cov = np.asarray(cov, dtype=float)
    if cov.ndim != 2 or cov.shape[0] != cov.shape[1]:
        raise ValueError(f"cov must be a square 2-D matrix, got shape {cov.shape}")
    if w.shape[0] != cov.shape[0]:
        raise ValueError(
            f"weights length {w.shape[0]} != cov dimension {cov.shape[0]}"
        )
    cov_sym = 0.5 * (cov + cov.T)
    var_p = float(w @ cov_sym @ w)
    sigma_p = np.sqrt(var_p) if var_p > 0.0 else 0.0
    mu_p = 0.0 if mu is None else float(w @ np.asarray(mu, dtype=float).ravel())
    return parametric_var(mu_p, sigma_p, alpha=a)


def pretrade_var_gate(
    weights,
    cov,
    *,
    var_limit: float,
    alpha: float = 0.05,
    mu: Optional[np.ndarray] = None,
) -> dict:
    """Pre-trade risk check: reject the proposed book if its VaR exceeds a limit.

    Returns a dict::

        {"var": float,            # portfolio VaR (positive loss)
         "limit": var_limit,
         "breach": bool,          # True iff var > limit  => REJECT the trade
         "utilization": var/limit,# fraction of the limit consumed (>1 => breach)
         "reason": str}

    ``var_limit`` must be a positive loss budget in the same units as the VaR.
    """
    if not np.isfinite(var_limit) or float(var_limit) <= 0.0:
        raise ValueError(f"var_limit must be a positive number, got {var_limit!r}")
    limit = float(var_limit)
    var = portfolio_var(weights, cov, alpha=alpha, mu=mu)
    breach = bool(var > limit)
    utilization = var / limit
    if breach:
        reason = (
            f"REJECT: VaR {var:.6g} exceeds limit {limit:.6g} "
            f"(utilization {utilization:.1%})"
        )
    else:
        reason = (
            f"OK: VaR {var:.6g} within limit {limit:.6g} "
            f"(utilization {utilization:.1%})"
        )
    return {
        "var": var,
        "limit": limit,
        "breach": breach,
        "utilization": utilization,
        "reason": reason,
    }
