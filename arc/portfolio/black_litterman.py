"""Phase 6 — Black-Litterman: blend an equilibrium PRIOR with explicit macro VIEWS.

WHAT THIS IS (and is NOT):
    Pure, CI-tested portfolio-construction linear algebra. Black-Litterman (BL) takes a market-equilibrium
    prior on expected returns (recovered from the covariance and market weights by reverse optimization) and
    tilts it toward a set of investor VIEWS, each with its own uncertainty, producing a posterior mean and
    covariance that a mean-variance optimizer turns into weights. This module is INFRASTRUCTURE, not an alpha
    claim: it asserts nothing about whether any view is profitable. The views must come from already-gated,
    leakage-safe signals before any allocation is real (project honesty law: no demonstrated alpha beyond
    carry). With NO views, BL reduces to the equilibrium prior and the optimizer recovers the market weights.

NO TIME SERIES HERE:
    These functions are cross-sectional matrix algebra on a SINGLE as-of snapshot (one covariance, one set of
    weights/views). There is no lookahead surface — causality lives upstream where ``cov``, ``market_weights``
    and the view matrix ``(P, Q)`` are estimated point-in-time. Numerically stable: we use ``np.linalg.solve``
    on symmetrized systems rather than forming explicit inverses where possible.

API
    implied_equilibrium_returns(cov, market_weights, *, risk_aversion=2.5) -> np.ndarray
        Reverse optimization:  pi = risk_aversion * cov @ w_mkt.
    black_litterman_posterior(pi, cov, P, Q, omega=None, *, tau=0.05) -> (mu_bl, cov_bl)
        Standard BL posterior (see formula below). Omega defaults Idzorek-style to diag(P (tauΣ) P').
    bl_optimal_weights(mu, cov, *, risk_aversion=2.5, long_only=False, budget=1.0) -> np.ndarray
        Unconstrained MV weights w = (1/risk_aversion) Σ^-1 mu, optionally clipped >= 0 and renormalized.

SHAPES (N assets, K views)
    cov:            (N, N) symmetric PSD covariance of asset returns.
    market_weights: (N,)  capitalization (or budget) weights of the equilibrium portfolio.
    pi / mu:        (N,)  expected-return vector (the prior, or any mean to optimize on).
    P:              (K, N) view-pick matrix; row k expresses one linear combination of assets.
    Q:              (K,)  the views' expected returns (P @ true_mu ~ Q).
    omega:          (K, K) view-uncertainty covariance (None => Idzorek default).
    returns:        np.ndarray (1-D for vectors, 2-D for cov_bl). pandas inputs are accepted and unwrapped.

FORMULA (black_litterman_posterior)
    Let Σ = cov, and let the prior on the MEAN be N(pi, tauΣ). With views N(Q, Ω) on the combos P:
        mu_bl  = [ (tauΣ)^-1 + P' Ω^-1 P ]^-1 [ (tauΣ)^-1 pi + P' Ω^-1 Q ]
        M      = [ (tauΣ)^-1 + P' Ω^-1 P ]^-1          # posterior covariance OF THE MEAN estimate
        cov_bl = Σ + M                                  # covariance of returns used by the optimizer
    With NO views (K = 0) the view terms vanish, so mu_bl == pi and cov_bl == Σ + tauΣ == (1+tau)Σ.

DEFAULT OMEGA (when omega is None)
    Ω = diag( P (tauΣ) P' )   — the per-view variance implied by the prior on that exact combo (Idzorek-style,
    "proportional to the view variance"). This makes each view's confidence scale with how uncertain the prior
    already is about that combination; off-diagonals are dropped so views are treated as independent. Any view
    row producing a non-positive implied variance is floored to a tiny positive epsilon to keep Ω invertible.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

__all__ = [
    "implied_equilibrium_returns",
    "black_litterman_posterior",
    "bl_optimal_weights",
    "default_omega",
]

_EPS = 1e-12


def _as_2d(a, name: str) -> np.ndarray:
    """Coerce a DataFrame/ndarray to a 2-D float64 square-or-rectangular array."""
    arr = np.asarray(a.values if isinstance(a, (pd.DataFrame, pd.Series)) else a, dtype="float64")
    if arr.ndim != 2:
        raise ValueError(f"{name} must be 2-D, got shape {arr.shape}")
    return arr


def _as_1d(a, name: str) -> np.ndarray:
    """Coerce a Series/1-D ndarray (or an (N,1)/(1,N) array) to a 1-D float64 vector.

    A genuine 2-D array is collapsed only when one of its dims is 1 (a row/column vector); a 1-D input is
    passed through unchanged (so a single-element vector like ``Q`` of one view stays shape ``(1,)`` rather
    than being squeezed to a 0-D scalar)."""
    arr = np.asarray(a.values if isinstance(a, (pd.DataFrame, pd.Series)) else a, dtype="float64")
    if arr.ndim == 2 and 1 in arr.shape:
        arr = arr.reshape(-1)
    if arr.ndim != 1:
        raise ValueError(f"{name} must be 1-D, got shape {np.asarray(a).shape}")
    return arr


def _check_cov(cov: np.ndarray) -> np.ndarray:
    """Validate a covariance matrix: square and (numerically) symmetric. Returns a symmetrized copy."""
    if cov.shape[0] != cov.shape[1]:
        raise ValueError(f"cov must be square, got shape {cov.shape}")
    if not np.allclose(cov, cov.T, atol=1e-10):
        raise ValueError("cov must be symmetric")
    return 0.5 * (cov + cov.T)  # symmetrize to kill tiny asymmetries before solving


def implied_equilibrium_returns(cov, market_weights, *, risk_aversion: float = 2.5) -> np.ndarray:
    """Reverse-optimize the equilibrium (prior) expected returns from cov and market weights.

    Implements ``pi = risk_aversion * cov @ w_mkt`` — the excess returns that make ``w_mkt`` the optimal
    mean-variance portfolio at the given risk aversion. This is the inverse of ``bl_optimal_weights``: feeding
    the returned ``pi`` (with the SAME cov and risk_aversion) into ``bl_optimal_weights`` recovers
    ``market_weights`` exactly (up to floating point).

    Parameters
    ----------
    cov : (N, N) array-like
        Symmetric PSD covariance of asset returns.
    market_weights : (N,) array-like
        Equilibrium/benchmark weights (typically market-cap weights).
    risk_aversion : float
        Scalar risk-aversion coefficient (delta), > 0.

    Returns
    -------
    np.ndarray, shape (N,)
        The implied equilibrium excess returns ``pi``.
    """
    if risk_aversion <= 0:
        raise ValueError(f"risk_aversion must be > 0, got {risk_aversion}")
    sigma = _check_cov(_as_2d(cov, "cov"))
    w = _as_1d(market_weights, "market_weights")
    if w.shape[0] != sigma.shape[0]:
        raise ValueError(f"market_weights length {w.shape[0]} != cov dim {sigma.shape[0]}")
    return risk_aversion * (sigma @ w)


def default_omega(P: np.ndarray, cov: np.ndarray, *, tau: float = 0.05) -> np.ndarray:
    """Idzorek-style default view-uncertainty matrix: Ω = diag(P (tauΣ) P').

    Each view's variance equals the prior variance of that exact combination, ``tau * P_k Σ P_k'``, so the
    view's confidence is proportional to how uncertain the prior already is about it. Off-diagonals are zero
    (views treated as independent). Non-positive diagonal entries are floored to a tiny epsilon so Ω stays
    invertible.

    Parameters
    ----------
    P : (K, N) array-like
        View-pick matrix.
    cov : (N, N) array-like
        Asset covariance Σ.
    tau : float
        Scalar scaling the prior covariance of the mean, > 0.

    Returns
    -------
    np.ndarray, shape (K, K)
        Diagonal view-uncertainty covariance.
    """
    Pm = _as_2d(P, "P")
    sigma = _check_cov(_as_2d(cov, "cov"))
    if tau <= 0:
        raise ValueError(f"tau must be > 0, got {tau}")
    if Pm.shape[1] != sigma.shape[0]:
        raise ValueError(f"P has {Pm.shape[1]} columns but cov dim is {sigma.shape[0]}")
    # Per-view prior variance: diagonal of P (tauΣ) P'. Compute only the diagonal (einsum), not the full matrix.
    diag = tau * np.einsum("ki,ij,kj->k", Pm, sigma, Pm)
    diag = np.where(diag > _EPS, diag, _EPS)  # floor to keep Ω invertible
    return np.diag(diag)


def black_litterman_posterior(pi, cov, P, Q, omega=None, *, tau: float = 0.05):
    """Black-Litterman posterior mean and (return) covariance from a prior and a set of views.

    See the module docstring for the full formula. Briefly, with prior on the mean ``N(pi, tauΣ)`` and views
    ``N(Q, Ω)`` on the linear combinations ``P``::

        A      = (tauΣ)^-1 + P' Ω^-1 P            # posterior precision of the mean
        mu_bl  = A^-1 [ (tauΣ)^-1 pi + P' Ω^-1 Q ]
        cov_bl = Σ + A^-1                          # M = A^-1 is the posterior covariance of the mean

    When there are NO views (``P`` is None/empty, or has 0 rows) the view terms drop out and the result is the
    pure prior: ``mu_bl == pi`` and ``cov_bl == (1 + tau) Σ``. Solved with ``np.linalg.solve`` on symmetrized
    systems for numerical stability (no explicit matrix inverse of the data covariances).

    Parameters
    ----------
    pi : (N,) array-like
        Prior (equilibrium) expected returns.
    cov : (N, N) array-like
        Asset covariance Σ (symmetric PSD).
    P : (K, N) array-like or None
        View-pick matrix; one row per view. None or a (0, N) array means "no views".
    Q : (K,) array-like or None
        View expected returns. None/empty when there are no views.
    omega : (K, K) array-like or None
        View-uncertainty covariance. If None, uses ``default_omega(P, cov, tau=tau)``.
    tau : float
        Scalar scaling the prior covariance of the mean, > 0 (commonly small, e.g. 0.025-0.05).

    Returns
    -------
    (mu_bl, cov_bl) : (np.ndarray shape (N,), np.ndarray shape (N, N))
        Posterior mean and posterior return covariance. ``cov_bl`` is symmetric.
    """
    if tau <= 0:
        raise ValueError(f"tau must be > 0, got {tau}")
    sigma = _check_cov(_as_2d(cov, "cov"))
    pi_v = _as_1d(pi, "pi")
    n = sigma.shape[0]
    if pi_v.shape[0] != n:
        raise ValueError(f"pi length {pi_v.shape[0]} != cov dim {n}")

    tau_sigma = tau * sigma

    # --- no-views fast path: posterior == prior ---------------------------------------------------
    no_views = P is None
    if not no_views:
        Pm = _as_2d(P, "P")
        if Pm.shape[0] == 0:
            no_views = True
    if no_views:
        cov_bl = sigma + tau_sigma  # = (1 + tau) Σ
        return pi_v.copy(), 0.5 * (cov_bl + cov_bl.T)

    Pm = _as_2d(P, "P")
    if Pm.shape[1] != n:
        raise ValueError(f"P has {Pm.shape[1]} columns but cov dim is {n}")
    k = Pm.shape[0]
    Qv = _as_1d(Q, "Q")
    if Qv.shape[0] != k:
        raise ValueError(f"Q length {Qv.shape[0]} != number of views {k}")

    if omega is None:
        Om = default_omega(Pm, sigma, tau=tau)
    else:
        Om = _as_2d(omega, "omega")
        if Om.shape != (k, k):
            raise ValueError(f"omega must be ({k}, {k}), got {Om.shape}")
        Om = 0.5 * (Om + Om.T)

    # Precision of the prior on the mean: (tauΣ)^-1.  Solve tauΣ X = I  ->  X = (tauΣ)^-1.
    tau_sigma_inv = np.linalg.solve(tau_sigma, np.eye(n))
    # Ω^-1 P  and  Ω^-1 Q via solve (avoid explicit inverse of Ω).
    omega_inv_P = np.linalg.solve(Om, Pm)        # (K, N)
    omega_inv_Q = np.linalg.solve(Om, Qv)        # (K,)

    # Posterior precision of the mean:  A = (tauΣ)^-1 + P' Ω^-1 P  (symmetric).
    A = tau_sigma_inv + Pm.T @ omega_inv_P
    A = 0.5 * (A + A.T)

    # RHS: (tauΣ)^-1 pi + P' Ω^-1 Q.
    rhs_mean = tau_sigma_inv @ pi_v + Pm.T @ omega_inv_Q
    mu_bl = np.linalg.solve(A, rhs_mean)

    # Posterior covariance of the mean estimate M = A^-1, and return covariance cov_bl = Σ + M.
    M = np.linalg.solve(A, np.eye(n))
    cov_bl = sigma + 0.5 * (M + M.T)
    return mu_bl, 0.5 * (cov_bl + cov_bl.T)


def bl_optimal_weights(
    mu,
    cov,
    *,
    risk_aversion: float = 2.5,
    long_only: bool = False,
    budget: float = 1.0,
) -> np.ndarray:
    """Unconstrained mean-variance weights, optionally projected to long-only and a budget.

    Computes the closed-form MV solution ``w = (1 / risk_aversion) Σ^-1 mu`` (via solve, no explicit inverse).
    With ``long_only=False`` the weights are returned scaled so they SUM to ``budget`` (a pure rescale that
    preserves the optimal direction; pass ``budget=None`` to skip rescaling and return the raw MV weights).
    With ``long_only=True`` negative weights are clipped to 0 and the survivors are renormalized to sum to
    ``budget`` (every weight then >= 0 and the book sums to ``budget``).

    Consistency: ``bl_optimal_weights(implied_equilibrium_returns(cov, w_mkt, risk_aversion=d), cov,
    risk_aversion=d, budget=sum(w_mkt))`` recovers ``w_mkt`` (long/short) up to floating point.

    Parameters
    ----------
    mu : (N,) array-like
        Expected-return vector to optimize on (e.g. the BL posterior mean, or the prior pi).
    cov : (N, N) array-like
        Asset covariance Σ (symmetric PSD, invertible).
    risk_aversion : float
        Scalar risk aversion (delta), > 0.
    long_only : bool
        If True, clip negatives to 0 and renormalize to ``budget``.
    budget : float or None
        Target sum of weights. If None and ``long_only`` is False, return raw (unscaled) MV weights. Must be
        non-None and the un-clipped/clipped weights must have nonzero sum to renormalize.

    Returns
    -------
    np.ndarray, shape (N,)
        Portfolio weights. Sums to ``budget`` unless ``budget is None`` and ``long_only is False``.
    """
    if risk_aversion <= 0:
        raise ValueError(f"risk_aversion must be > 0, got {risk_aversion}")
    sigma = _check_cov(_as_2d(cov, "cov"))
    mu_v = _as_1d(mu, "mu")
    if mu_v.shape[0] != sigma.shape[0]:
        raise ValueError(f"mu length {mu_v.shape[0]} != cov dim {sigma.shape[0]}")

    # Raw MV weights: w = (1/delta) Σ^-1 mu  via  solve(Σ, mu).
    w = np.linalg.solve(sigma, mu_v) / risk_aversion

    if long_only:
        if budget is None:
            raise ValueError("budget must be set (not None) when long_only=True")
        w = np.clip(w, 0.0, None)
        total = float(w.sum())
        if total <= _EPS:
            raise ValueError("all weights clipped to ~0; cannot renormalize a long-only book to budget")
        return w * (budget / total)

    if budget is None:
        return w  # raw MV weights, not rescaled
    total = float(w.sum())
    if abs(total) <= _EPS:
        raise ValueError("MV weights sum to ~0; cannot rescale to budget (pass budget=None for raw weights)")
    return w * (budget / total)
