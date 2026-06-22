"""VaR / ES + pre-trade gate tests (arc.risk.var_es).

Sign convention under test: VaR/ES are POSITIVE loss magnitudes; smaller alpha
=> larger VaR; ES >= VaR; portfolio_var of a 1-asset book == scalar parametric.
"""

from __future__ import annotations

import numpy as np
import pytest

from arc.risk.var_es import (
    cornish_fisher_var,
    historical_es,
    historical_var,
    parametric_es,
    parametric_var,
    portfolio_var,
    pretrade_var_gate,
)


# --------------------------- known closed-form cases --------------------------
def test_parametric_var_standard_normal_known_value():
    # 5% one-sided Gaussian z = 1.6448536...
    assert parametric_var(0.0, 1.0, alpha=0.05) == pytest.approx(1.6448536, abs=1e-5)
    # 1% level
    assert parametric_var(0.0, 1.0, alpha=0.01) == pytest.approx(2.3263479, abs=1e-5)


def test_parametric_es_standard_normal_known_value():
    # phi(z_0.05)/0.05 = 0.103136.../0.05 = 2.06271...
    assert parametric_es(0.0, 1.0, alpha=0.05) == pytest.approx(2.0627128, abs=1e-5)
    assert parametric_es(0.0, 1.0, alpha=0.05) > parametric_var(0.0, 1.0, alpha=0.05)


def test_parametric_var_mean_and_scale_shifts():
    # positive mu reduces loss; sigma scales the z-term
    assert parametric_var(0.1, 1.0, alpha=0.05) == pytest.approx(1.6448536 - 0.1, abs=1e-5)
    assert parametric_var(0.0, 2.0, alpha=0.05) == pytest.approx(2 * 1.6448536, abs=1e-5)
    # large positive mean can drive parametric VaR negative (quantile is positive)
    assert parametric_var(5.0, 1.0, alpha=0.05) < 0


# ------------------------------- monotonicity --------------------------------
def test_parametric_var_es_monotonic_in_alpha():
    v05 = parametric_var(0.0, 1.0, alpha=0.05)
    v01 = parametric_var(0.0, 1.0, alpha=0.01)
    assert v01 > v05  # deeper tail => larger VaR
    e05 = parametric_es(0.0, 1.0, alpha=0.05)
    e01 = parametric_es(0.0, 1.0, alpha=0.01)
    assert e01 > e05
    assert e05 >= v05 and e01 >= v01


def test_historical_var_es_monotonic_and_ordering():
    rng = np.random.default_rng(0)
    r = rng.standard_normal(20_000)
    v05 = historical_var(r, alpha=0.05)
    v01 = historical_var(r, alpha=0.01)
    assert v01 > v05  # monotone in alpha
    e05 = historical_es(r, alpha=0.05)
    e01 = historical_es(r, alpha=0.01)
    assert e01 > e05
    assert e05 >= v05 and e01 >= v01
    # large iid normal sample -> close to the Gaussian closed form
    assert v05 == pytest.approx(parametric_var(0.0, 1.0, alpha=0.05), abs=0.1)
    assert e05 == pytest.approx(parametric_es(0.0, 1.0, alpha=0.05), abs=0.1)


def test_historical_es_strictly_ge_var_general_sample():
    rng = np.random.default_rng(7)
    r = rng.standard_normal(5_000) - 0.01
    assert historical_es(r, alpha=0.05) >= historical_var(r, alpha=0.05)


# ------------------------------ cornish-fisher -------------------------------
def test_cornish_fisher_matches_gaussian_for_symmetric_mesokurtic():
    rng = np.random.default_rng(3)
    r = rng.standard_normal(50_000)
    cf = cornish_fisher_var(r, alpha=0.05)
    # near-Gaussian sample -> CF VaR close to plain Gaussian VaR
    assert cf == pytest.approx(parametric_var(0.0, 1.0, alpha=0.05), abs=0.1)


def test_cornish_fisher_inflates_var_for_left_skew_fat_tails():
    rng = np.random.default_rng(5)
    base = rng.standard_normal(20_000)
    # inject a fat negative tail (left skew + excess kurtosis)
    base[:400] -= 6.0
    mu = float(base.mean())
    sigma = float(base.std(ddof=1))
    cf = cornish_fisher_var(base, alpha=0.01)
    gauss = parametric_var(mu, sigma, alpha=0.01)
    assert cf > gauss  # tail risk recognised beyond the Gaussian


# ------------------------------ portfolio VaR --------------------------------
def test_portfolio_var_one_asset_equals_parametric():
    sigma2 = 0.04  # variance => sigma = 0.2
    pv = portfolio_var(np.array([1.0]), np.array([[sigma2]]), alpha=0.05)
    assert pv == pytest.approx(parametric_var(0.0, np.sqrt(sigma2), alpha=0.05), abs=1e-12)


def test_portfolio_var_with_mu_and_diversification():
    cov = np.array([[0.04, 0.0], [0.0, 0.09]])  # vols 0.2, 0.3, uncorrelated
    w = np.array([0.5, 0.5])
    sigma_p = np.sqrt(w @ cov @ w)
    assert portfolio_var(w, cov, alpha=0.05) == pytest.approx(
        parametric_var(0.0, sigma_p, alpha=0.05), abs=1e-12
    )
    # positive expected returns reduce VaR vs the zero-mean case
    mu = np.array([0.05, 0.05])
    assert portfolio_var(w, cov, alpha=0.05, mu=mu) < portfolio_var(w, cov, alpha=0.05)
    # diversification: equal-weight uncorrelated < fully concentrated worst leg
    concentrated = portfolio_var(np.array([0.0, 1.0]), cov, alpha=0.05)
    assert portfolio_var(w, cov, alpha=0.05) < concentrated


def test_portfolio_var_symmetrizes_and_validates_shape():
    cov = np.array([[0.04, 0.02], [0.0, 0.09]])  # asymmetric -> symmetrised
    w = np.array([0.5, 0.5])
    cov_sym = 0.5 * (cov + cov.T)
    sigma_p = np.sqrt(w @ cov_sym @ w)
    assert portfolio_var(w, cov, alpha=0.05) == pytest.approx(
        parametric_var(0.0, sigma_p, alpha=0.05), abs=1e-12
    )
    with pytest.raises(ValueError):
        portfolio_var(np.array([1.0, 0.0, 0.0]), cov, alpha=0.05)  # length mismatch


# ------------------------------ degenerate cases -----------------------------
def test_zero_vol_degenerate_handled():
    # scalar parametric
    assert parametric_var(0.2, 0.0, alpha=0.05) == pytest.approx(-0.2)
    assert parametric_es(0.2, 0.0, alpha=0.05) == pytest.approx(-0.2)
    # portfolio with zero covariance
    cov0 = np.zeros((2, 2))
    assert portfolio_var(np.array([0.5, 0.5]), cov0, alpha=0.05) == pytest.approx(0.0)
    assert portfolio_var(
        np.array([0.5, 0.5]), cov0, alpha=0.05, mu=np.array([0.1, 0.1])
    ) == pytest.approx(-0.1)
    # constant return sample -> sigma 0
    const = np.full(50, 0.003)
    assert cornish_fisher_var(const, alpha=0.05) == pytest.approx(-0.003)
    assert historical_var(const, alpha=0.05) == pytest.approx(-0.003)
    assert historical_es(const, alpha=0.05) == pytest.approx(-0.003)


# --------------------------------- the gate ----------------------------------
def test_pretrade_gate_breach_both_sides():
    cov = np.array([[0.04, 0.0], [0.0, 0.04]])  # vols 0.2
    w = np.array([1.0, 1.0])
    var = portfolio_var(w, cov, alpha=0.05)
    assert var > 0
    # limit just below VaR -> breach / reject
    tight = pretrade_var_gate(w, cov, var_limit=var * 0.5, alpha=0.05)
    assert tight["breach"] is True
    assert tight["utilization"] > 1.0
    assert tight["reason"].startswith("REJECT")
    assert tight["var"] == pytest.approx(var)
    # limit comfortably above VaR -> pass
    loose = pretrade_var_gate(w, cov, var_limit=var * 2.0, alpha=0.05)
    assert loose["breach"] is False
    assert loose["utilization"] < 1.0
    assert loose["reason"].startswith("OK")
    assert loose["limit"] == pytest.approx(var * 2.0)


def test_pretrade_gate_boundary_not_a_breach():
    cov = np.array([[0.04]])
    w = np.array([1.0])
    var = portfolio_var(w, cov, alpha=0.05)
    # limit exactly equal to VaR: var > limit is False -> not a breach
    res = pretrade_var_gate(w, cov, var_limit=var, alpha=0.05)
    assert res["breach"] is False
    assert res["utilization"] == pytest.approx(1.0)


def test_pretrade_gate_rejects_bad_limit():
    cov = np.array([[0.04]])
    w = np.array([1.0])
    for bad in (0.0, -1.0, np.nan, np.inf):
        with pytest.raises(ValueError):
            pretrade_var_gate(w, cov, var_limit=bad, alpha=0.05)


# ------------------------------- input guards --------------------------------
def test_alpha_and_input_validation():
    with pytest.raises(ValueError):
        parametric_var(0.0, 1.0, alpha=0.0)
    with pytest.raises(ValueError):
        parametric_var(0.0, 1.0, alpha=1.0)
    with pytest.raises(ValueError):
        parametric_var(0.0, -1.0, alpha=0.05)  # negative sigma
    with pytest.raises(ValueError):
        historical_var(np.array([np.nan, np.inf]), alpha=0.05)  # empty after clean
