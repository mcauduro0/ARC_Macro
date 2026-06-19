"""Causal composite r* — as-of invariance of the regime-weighted equilibrium (audit eq-1/eq-3).

The legacy ``compute`` takes one regime-probability vector (the as-of date's regime) and applies it
to ALL history, so appending future data (which changes the as-of regime) silently rewrites the r*
feature in the past — a look-ahead. ``compute_causal`` uses the regime probs AT each date, so early
values must be invariant to what comes later. This test pins that contrast.
"""

from __future__ import annotations

import os
import sys

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "server", "model"))

from composite_equilibrium import CompositeEquilibriumRate  # noqa: E402


def _inputs(n):
    idx = pd.date_range("2005-01-31", periods=n, freq="ME")
    rng = np.random.default_rng(0)
    # four distinct model r* series so the regime weighting actually matters
    models = {
        "state_space": pd.Series(4.5 + 0.5 * np.sin(np.arange(n) / 9.0), index=idx),
        "market_implied": pd.Series(5.5 + np.cumsum(rng.normal(0, 0.03, n)), index=idx).clip(2, 10),
        "fiscal": pd.Series(6.0 + 0.8 * np.cos(np.arange(n) / 7.0), index=idx),
        "parity": pd.Series(5.0 + np.cumsum(rng.normal(0, 0.02, n)), index=idx).clip(2, 10),
    }
    # time-varying regime probs (smoothly drifting between carry and stress)
    t = np.arange(n)
    p_carry = 0.5 + 0.4 * np.sin(t / 11.0)
    p_stress = 0.5 - 0.4 * np.sin(t / 11.0)
    p_riskoff = np.full(n, 0.2)
    probs = pd.DataFrame({"P_carry": p_carry, "P_riskoff": p_riskoff, "P_stress": p_stress}, index=idx)
    probs = probs.div(probs.sum(axis=1), axis=0)

    selic = pd.Series(10.0 + np.cumsum(rng.normal(0, 0.05, n)), index=idx)
    ipca_yoy = pd.Series(4.0 + 0.5 * np.sin(t / 8.0), index=idx)
    ipca_exp = pd.Series(4.0 + 0.3 * np.sin(t / 8.0), index=idx)
    ibc_br = pd.Series(100 + np.cumsum(rng.normal(0.1, 0.5, n)), index=idx)
    pi_star = pd.Series(3.0, index=idx)
    return idx, models, probs, selic, ipca_yoy, ipca_exp, ibc_br, pi_star


def test_compute_causal_is_asof_invariant():
    n = 132
    idx, models, probs, selic, ipca_yoy, ipca_exp, ibc_br, pi_star = _inputs(n)
    cut = 96
    early = idx[:cut]

    full = CompositeEquilibriumRate()
    comp_full, _ = full.compute_causal(models, probs, ipca_yoy, ipca_exp, ibc_br, selic, pi_star)

    trunc = CompositeEquilibriumRate()
    comp_trunc, _ = trunc.compute_causal(
        {k: v.loc[:early[-1]] for k, v in models.items()},
        probs.loc[:early[-1]],
        ipca_yoy.loc[:early[-1]], ipca_exp.loc[:early[-1]],
        ibc_br.loc[:early[-1]], selic.loc[:early[-1]], pi_star.loc[:early[-1]],
    )

    common = comp_full.index.intersection(comp_trunc.index)
    assert len(common) > 24
    a = comp_full.reindex(common)
    b = comp_trunc.reindex(common)
    assert np.allclose(a.values, b.values, atol=1e-8), "causal composite r* must not change when future is appended"


def test_legacy_compute_is_not_asof_invariant():
    """Contrast: the legacy dict path applies the as-of regime to all history, so early values DO
    move when the as-of regime changes. This is the leak compute_causal removes."""
    n = 132
    idx, models, probs, selic, ipca_yoy, ipca_exp, ibc_br, pi_star = _inputs(n)
    cut = 96

    # 'as-of' regime at the two horizons (last row of the available probs)
    regime_late = probs.iloc[-1].to_dict()
    regime_early = probs.iloc[cut - 1].to_dict()
    # the two regimes must actually differ for the contrast to be meaningful
    assert abs(regime_late["P_carry"] - regime_early["P_carry"]) > 0.1

    full = CompositeEquilibriumRate()
    comp_full, _ = full.compute(models, regime_late, ipca_yoy, ipca_exp, ibc_br, selic, pi_star)
    trunc = CompositeEquilibriumRate()
    comp_trunc, _ = trunc.compute(
        {k: v.loc[:idx[cut - 1]] for k, v in models.items()}, regime_early,
        ipca_yoy.loc[:idx[cut - 1]], ipca_exp.loc[:idx[cut - 1]],
        ibc_br.loc[:idx[cut - 1]], selic.loc[:idx[cut - 1]], pi_star.loc[:idx[cut - 1]],
    )
    common = comp_full.index.intersection(comp_trunc.index)
    a = comp_full.reindex(common)
    b = comp_trunc.reindex(common)
    # legacy: early history is rewritten by the as-of regime -> NOT invariant
    assert not np.allclose(a.values, b.values, atol=1e-6)


def test_compute_causal_respects_bounds():
    n = 120
    idx, models, probs, selic, ipca_yoy, ipca_exp, ibc_br, pi_star = _inputs(n)
    comp = CompositeEquilibriumRate()
    composite, selic_star = comp.compute_causal(models, probs, ipca_yoy, ipca_exp, ibc_br, selic, pi_star)
    assert (composite >= 2.0 - 1e-9).all() and (composite <= 10.0 + 1e-9).all()
    assert len(selic_star) > 12
