"""StateSpaceRStar credible intervals from the Kalman filtered posterior variance (ask 3b).

CI-native: composite_equilibrium imports cleanly with only numpy/pandas (+ arc.causal), no
engine and no heavy deps. Guarded with importlib.find_spec so it skips gracefully if those
modules are unavailable in a given CI image rather than erroring at collection.

These tests pin the contract of the new uncertainty-quantification surface:
  - estimate() return type/shape is UNCHANGED (still a pd.Series of r*);
  - credible_intervals() exposes [rstar, std, lo, hi] from P[0,0];
  - std >= 0, lo <= rstar <= hi, and the band WIDENS with larger z;
  - before estimate() runs, credible_intervals() returns an EMPTY frame.

Honest by construction: this is uncertainty quantification of the in-sample filtered estimate,
not a forecast and not a claim of alpha.
"""

from __future__ import annotations

import importlib.util
import os
import sys

import pytest

# Skip cleanly if the (light) deps composite_equilibrium needs are missing.
_MISSING = [m for m in ("numpy", "pandas") if importlib.util.find_spec(m) is None]
if _MISSING:
    pytest.skip(f"missing deps: {_MISSING}", allow_module_level=True)

sys.path.insert(
    0,
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "server", "model"),
)

if importlib.util.find_spec("composite_equilibrium") is None:
    pytest.skip("composite_equilibrium not importable", allow_module_level=True)

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

try:
    from composite_equilibrium import StateSpaceRStar  # noqa: E402
except Exception as exc:  # pragma: no cover - heavy/unavailable dep at import time
    pytest.skip(f"composite_equilibrium import failed: {exc}", allow_module_level=True)


def _synthetic(n=96, seed=0):
    """Small, well-behaved monthly inputs matching estimate()'s signature."""
    idx = pd.date_range("2010-01-31", periods=n, freq="ME")
    rng = np.random.default_rng(seed)
    t = np.arange(n)
    selic = pd.Series(10.0 + 0.5 * np.sin(t / 10.0) + np.cumsum(rng.normal(0, 0.03, n)), index=idx)
    ipca_yoy = pd.Series(4.0 + 0.5 * np.sin(t / 8.0), index=idx)
    ipca_exp = pd.Series(4.0 + 0.3 * np.sin(t / 8.0), index=idx)
    ibc_br = pd.Series(100.0 + np.cumsum(rng.normal(0.1, 0.4, n)), index=idx).clip(lower=1)
    debt_gdp = pd.Series(70.0 + np.cumsum(rng.normal(0.05, 0.1, n)), index=idx)
    cds_5y = pd.Series(200.0 + np.cumsum(rng.normal(0, 1.0, n)), index=idx)
    return selic, ipca_yoy, ipca_exp, ibc_br, debt_gdp, cds_5y


def test_estimate_return_unchanged():
    """estimate() still returns a non-empty pd.Series of r* (signature preserved)."""
    model = StateSpaceRStar(window=120)
    rstar = model.estimate(*_synthetic())
    assert isinstance(rstar, pd.Series)
    assert len(rstar) > 12
    assert rstar.notna().all()


def test_credible_intervals_columns_and_alignment():
    model = StateSpaceRStar(window=120)
    rstar = model.estimate(*_synthetic())
    ci = model.credible_intervals()  # default z=1.96
    assert list(ci.columns) == ["rstar", "std", "lo", "hi"]
    assert len(ci) == len(rstar)
    assert ci.index.equals(rstar.index)
    # rstar column matches the estimate() series exactly.
    pd.testing.assert_series_equal(ci["rstar"], rstar, check_names=False)


def test_intervals_well_formed():
    model = StateSpaceRStar(window=120)
    model.estimate(*_synthetic())
    ci = model.credible_intervals()
    assert (ci["std"] >= 0).all()
    assert (ci["lo"] <= ci["rstar"] + 1e-9).all()
    assert (ci["rstar"] <= ci["hi"] + 1e-9).all()
    assert ci[["rstar", "std", "lo", "hi"]].notna().all().all()


def test_intervals_widen_with_z():
    model = StateSpaceRStar(window=120)
    model.estimate(*_synthetic())
    narrow = model.credible_intervals(z=1.0)
    wide = model.credible_intervals(z=3.0)
    w_narrow = (narrow["hi"] - narrow["lo"])
    w_wide = (wide["hi"] - wide["lo"])
    # Strictly wider wherever std > 0; >= everywhere.
    assert (w_wide >= w_narrow - 1e-12).all()
    pos = narrow["std"] > 0
    assert pos.any()
    assert (w_wide[pos] > w_narrow[pos]).all()


def test_empty_before_estimate():
    model = StateSpaceRStar(window=120)
    ci = model.credible_intervals()
    assert list(ci.columns) == ["rstar", "std", "lo", "hi"]
    assert len(ci) == 0


def test_var_series_and_last_P_recorded():
    model = StateSpaceRStar(window=120)
    rstar = model.estimate(*_synthetic())
    assert model.rstar_var_series is not None
    assert model.rstar_var_series.index.equals(rstar.index)
    assert (model.rstar_var_series.dropna() >= 0).all()
    assert model.last_P is not None
    assert model.last_P.shape == (3, 3)
