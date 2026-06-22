"""CI-native tests for arc.portfolio.black_litterman (pure linear algebra, no engine, no network).

Asserts the Black-Litterman contract against KNOWN closed-form identities:
  (1) reverse optimization and MV optimization are inverses: bl_optimal_weights(implied_pi, cov) recovers the
      market weights (up to the budget rescale);
  (2) with NO views the posterior mean equals the prior (mu_bl == pi) and cov_bl == (1+tau)Σ;
  (3) a single strong view shifts the posterior mean toward Q on the viewed combination;
  (4) the posterior covariance is symmetric and PSD;
  (5) bl_optimal_weights sums to budget; long_only normalizes to budget with every weight >= 0;
  (6) input validation rejects bad shapes/params.

A small 3-asset covariance is used throughout. These tests assert math identities only — no alpha claim.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from arc.portfolio.black_litterman import (
    bl_optimal_weights,
    black_litterman_posterior,
    default_omega,
    implied_equilibrium_returns,
)


# --------------------------------------------------------------------------------------
# small 3-asset fixtures
# --------------------------------------------------------------------------------------
def _cov() -> np.ndarray:
    """A symmetric PSD 3-asset covariance (built as L L' so PSD is guaranteed)."""
    L = np.array(
        [
            [0.20, 0.00, 0.00],
            [0.06, 0.15, 0.00],
            [0.02, 0.04, 0.10],
        ]
    )
    return L @ L.T


def _w_mkt() -> np.ndarray:
    return np.array([0.5, 0.3, 0.2])


def _is_psd(M: np.ndarray, tol: float = 1e-10) -> bool:
    eig = np.linalg.eigvalsh(0.5 * (M + M.T))
    return bool(eig.min() >= -tol)


# --------------------------------------------------------------------------------------
# (1) reverse optimization <-> MV optimization are inverses
# --------------------------------------------------------------------------------------
def test_implied_returns_then_optimize_recovers_market_weights():
    cov = _cov()
    w_mkt = _w_mkt()
    delta = 2.5
    pi = implied_equilibrium_returns(cov, w_mkt, risk_aversion=delta)
    # Feeding pi back (same cov, same delta) with budget = sum(w_mkt) recovers the market weights.
    w_back = bl_optimal_weights(pi, cov, risk_aversion=delta, budget=float(w_mkt.sum()))
    assert np.allclose(w_back, w_mkt, atol=1e-10)


def test_implied_returns_formula_matches_definition():
    cov = _cov()
    w_mkt = _w_mkt()
    delta = 3.1
    pi = implied_equilibrium_returns(cov, w_mkt, risk_aversion=delta)
    assert np.allclose(pi, delta * (cov @ w_mkt), atol=1e-12)


# --------------------------------------------------------------------------------------
# (2) NO views => posterior == prior
# --------------------------------------------------------------------------------------
@pytest.mark.parametrize("P,Q", [(None, None), (np.zeros((0, 3)), np.zeros((0,)))])
def test_no_views_posterior_equals_prior(P, Q):
    cov = _cov()
    pi = implied_equilibrium_returns(cov, _w_mkt(), risk_aversion=2.5)
    tau = 0.05
    mu_bl, cov_bl = black_litterman_posterior(pi, cov, P, Q, tau=tau)
    assert np.allclose(mu_bl, pi, atol=1e-12), "no-view posterior mean must equal the prior pi"
    assert np.allclose(cov_bl, (1.0 + tau) * cov, atol=1e-12), "no-view cov_bl must equal (1+tau)Σ"


def test_no_views_then_optimize_recovers_market_weights_direction():
    """With no views, optimizing on mu_bl (cov_bl) still points at the market portfolio direction."""
    cov = _cov()
    w_mkt = _w_mkt()
    delta = 2.5
    pi = implied_equilibrium_returns(cov, w_mkt, risk_aversion=delta)
    mu_bl, _ = black_litterman_posterior(pi, cov, None, None, tau=0.05)
    # mu_bl == pi here, so MV on the ORIGINAL cov recovers the market weights.
    w_back = bl_optimal_weights(mu_bl, cov, risk_aversion=delta, budget=float(w_mkt.sum()))
    assert np.allclose(w_back, w_mkt, atol=1e-10)


# --------------------------------------------------------------------------------------
# (3) a single strong view shifts the posterior toward Q on the viewed combo
# --------------------------------------------------------------------------------------
def test_single_view_shifts_posterior_toward_view():
    cov = _cov()
    pi = implied_equilibrium_returns(cov, _w_mkt(), risk_aversion=2.5)

    # View: asset 0 OUTPERFORMS asset 1 by a large margin (P = [1, -1, 0], Q = big).
    P = np.array([[1.0, -1.0, 0.0]])
    prior_combo = float((P @ pi)[0])         # current prior on (asset0 - asset1)
    Q = np.array([prior_combo + 0.10])       # push the view well ABOVE the prior

    # Very confident view (tiny omega) -> posterior combo should move strongly toward Q.
    omega = np.array([[1e-6]])
    mu_bl, _ = black_litterman_posterior(pi, cov, P, Q, omega=omega, tau=0.05)
    post_combo = float((P @ mu_bl)[0])

    assert post_combo > prior_combo + 1e-6, "confident view did not move the posterior toward Q"
    # With a near-zero omega the posterior combo should land very close to Q.
    assert abs(post_combo - Q[0]) < 1e-3


def test_view_confidence_monotone():
    """A MORE confident view (smaller omega) moves the posterior combo CLOSER to Q than a vague one."""
    cov = _cov()
    pi = implied_equilibrium_returns(cov, _w_mkt(), risk_aversion=2.5)
    P = np.array([[1.0, -1.0, 0.0]])
    Q = np.array([float((P @ pi)[0]) + 0.10])

    confident, _ = black_litterman_posterior(pi, cov, P, Q, omega=np.array([[1e-5]]), tau=0.05)
    vague, _ = black_litterman_posterior(pi, cov, P, Q, omega=np.array([[1.0]]), tau=0.05)
    gap_confident = abs(float((P @ confident)[0]) - Q[0])
    gap_vague = abs(float((P @ vague)[0]) - Q[0])
    assert gap_confident < gap_vague, "tighter omega should land closer to Q"


def test_default_omega_is_diag_of_P_tauSigma_Pt():
    cov = _cov()
    tau = 0.05
    P = np.array([[1.0, -1.0, 0.0], [0.0, 0.0, 1.0]])
    Om = default_omega(P, cov, tau=tau)
    expected_diag = np.diag(P @ (tau * cov) @ P.T)
    assert np.allclose(np.diag(Om), expected_diag, atol=1e-12)
    # Off-diagonals are zero (views treated independently).
    off = Om - np.diag(np.diag(Om))
    assert np.allclose(off, 0.0, atol=1e-12)


def test_default_omega_used_when_none():
    """Passing omega=None must give the same posterior as passing the explicit default_omega."""
    cov = _cov()
    pi = implied_equilibrium_returns(cov, _w_mkt(), risk_aversion=2.5)
    P = np.array([[1.0, -1.0, 0.0]])
    Q = np.array([0.05])
    mu_default, cov_default = black_litterman_posterior(pi, cov, P, Q, omega=None, tau=0.05)
    Om = default_omega(P, cov, tau=0.05)
    mu_explicit, cov_explicit = black_litterman_posterior(pi, cov, P, Q, omega=Om, tau=0.05)
    assert np.allclose(mu_default, mu_explicit, atol=1e-12)
    assert np.allclose(cov_default, cov_explicit, atol=1e-12)


# --------------------------------------------------------------------------------------
# (4) posterior covariance symmetric + PSD
# --------------------------------------------------------------------------------------
def test_posterior_cov_symmetric_psd():
    cov = _cov()
    pi = implied_equilibrium_returns(cov, _w_mkt(), risk_aversion=2.5)
    P = np.array([[1.0, -1.0, 0.0], [0.0, 1.0, -1.0]])
    Q = np.array([0.03, -0.01])
    _, cov_bl = black_litterman_posterior(pi, cov, P, Q, tau=0.05)
    assert np.allclose(cov_bl, cov_bl.T, atol=1e-12), "posterior cov must be symmetric"
    assert _is_psd(cov_bl), "posterior cov must be PSD"
    # BL adds the posterior mean-covariance M >= 0 to Σ, so cov_bl >= Σ in the PSD order.
    assert _is_psd(cov_bl - cov), "cov_bl - Σ (= M) must be PSD"


# --------------------------------------------------------------------------------------
# (5) optimal weights: budget + long-only contract
# --------------------------------------------------------------------------------------
def test_optimal_weights_sum_to_budget():
    cov = _cov()
    mu = np.array([0.05, 0.02, 0.03])
    for budget in (1.0, 0.5, 2.0):
        w = bl_optimal_weights(mu, cov, risk_aversion=2.5, budget=budget)
        assert np.isclose(w.sum(), budget, atol=1e-12)


def test_optimal_weights_raw_when_budget_none():
    cov = _cov()
    mu = np.array([0.05, 0.02, 0.03])
    w = bl_optimal_weights(mu, cov, risk_aversion=2.5, budget=None)
    assert np.allclose(w, np.linalg.solve(cov, mu) / 2.5, atol=1e-12)


def test_long_only_clips_and_normalizes_to_budget():
    cov = _cov()
    # A mu that produces at least one negative raw weight (short), to exercise the clip.
    mu = np.array([0.10, -0.08, 0.02])
    raw = np.linalg.solve(cov, mu) / 2.5
    assert (raw < 0).any(), "fixture should produce a short leg before clipping"
    w = bl_optimal_weights(mu, cov, risk_aversion=2.5, long_only=True, budget=1.0)
    assert (w >= 0).all(), "long-only weights must be >= 0"
    assert np.isclose(w.sum(), 1.0, atol=1e-12), "long-only book must sum to budget"
    # The clipped (negative) leg is exactly zero.
    assert np.isclose(w[raw < 0][0], 0.0, atol=1e-12)


def test_long_only_all_clipped_raises():
    cov = _cov()
    # All-negative mu -> all raw weights negative -> nothing survives the long-only clip.
    mu = np.array([-0.05, -0.04, -0.03])
    raw = np.linalg.solve(cov, mu) / 2.5
    assert (raw < 0).all()
    with pytest.raises(ValueError):
        bl_optimal_weights(mu, cov, risk_aversion=2.5, long_only=True, budget=1.0)


# --------------------------------------------------------------------------------------
# pandas inputs accepted
# --------------------------------------------------------------------------------------
def test_accepts_pandas_inputs():
    cols = ["a", "b", "c"]
    cov = pd.DataFrame(_cov(), index=cols, columns=cols)
    w_mkt = pd.Series(_w_mkt(), index=cols)
    pi = implied_equilibrium_returns(cov, w_mkt, risk_aversion=2.5)
    assert isinstance(pi, np.ndarray) and pi.shape == (3,)
    P = pd.DataFrame([[1.0, -1.0, 0.0]], columns=cols)
    Q = pd.Series([0.05])
    mu_bl, cov_bl = black_litterman_posterior(pi, cov, P, Q, tau=0.05)
    assert mu_bl.shape == (3,) and cov_bl.shape == (3, 3)


# --------------------------------------------------------------------------------------
# (6) input validation
# --------------------------------------------------------------------------------------
def test_rejects_bad_params():
    cov = _cov()
    w_mkt = _w_mkt()
    with pytest.raises(ValueError):
        implied_equilibrium_returns(cov, w_mkt, risk_aversion=0.0)      # delta must be > 0
    with pytest.raises(ValueError):
        implied_equilibrium_returns(cov, np.array([0.5, 0.5]))          # length mismatch
    with pytest.raises(ValueError):
        black_litterman_posterior(np.zeros(3), cov, np.zeros((1, 3)), np.zeros(1), tau=0.0)  # tau > 0
    with pytest.raises(ValueError):
        black_litterman_posterior(np.zeros(3), cov, np.zeros((2, 3)), np.zeros(1))  # Q length != #views
    with pytest.raises(ValueError):
        black_litterman_posterior(np.zeros(3), cov, np.zeros((1, 2)), np.zeros(1))  # P cols != cov dim
    with pytest.raises(ValueError):
        bl_optimal_weights(np.zeros(3), cov, risk_aversion=-1.0)        # delta must be > 0
    with pytest.raises(ValueError):
        # asymmetric "cov" rejected
        bl_optimal_weights(np.zeros(3), np.array([[1.0, 2.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]))


def test_rejects_non_square_cov():
    with pytest.raises(ValueError):
        implied_equilibrium_returns(np.zeros((3, 2)), np.zeros(3))
