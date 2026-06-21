"""CI-native tests for arc.intelligence.sizing (no engine, no network).

Asserts the leakage-safe sizing contract:
  (1) confidence_scaled_position is BOUNDED: |out| in [lo*|base|, hi*|base|] elementwise;
  (2) MONOTONE: higher confidence (base fixed) => >= scale (tested on a ramp);
  (3) CAUSAL: an interior output is unchanged when later data is appended;
  (4) inverse_vol_position: doubling pred_vol halves the size (pre-clip), respects clip, keeps sign.

These functions only RESIZE a causal position; they never create signal.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from arc.intelligence.sizing import confidence_scaled_position, inverse_vol_position
from tests.canary import is_as_of_invariant, make_series


def _idx(n: int) -> pd.DatetimeIndex:
    return pd.date_range("2010-01-31", periods=n, freq="ME")


# --------------------------------------------------------------------------------------
# (1) BOUNDED
# --------------------------------------------------------------------------------------
def test_confidence_scaled_is_bounded_elementwise():
    n = 120
    rng = np.random.default_rng(0)
    base = pd.Series(rng.standard_normal(n) * 2.0, index=_idx(n))
    conf = pd.Series(rng.random(n), index=_idx(n))
    lo, hi = 0.25, 1.0

    out = confidence_scaled_position(base, conf, lo=lo, hi=hi)
    mask = out.notna()
    lo_bound = lo * base.abs()
    hi_bound = hi * base.abs()
    eps = 1e-12
    assert (out.abs()[mask] >= lo_bound[mask] - eps).all(), "below lower bound"
    assert (out.abs()[mask] <= hi_bound[mask] + eps).all(), "above upper bound"
    # sign preserved where base != 0
    nz = mask & (base != 0)
    assert (np.sign(out[nz]) == np.sign(base[nz])).all()


def test_confidence_scaled_nan_propagates():
    n = 40
    base = pd.Series(np.ones(n), index=_idx(n))
    conf = pd.Series(np.ones(n), index=_idx(n))
    base.iloc[5] = np.nan
    conf.iloc[7] = np.nan
    out = confidence_scaled_position(base, conf)
    assert np.isnan(out.iloc[5]) and np.isnan(out.iloc[7])


def test_confidence_scaled_rejects_bad_bounds():
    s = pd.Series([1.0, 2.0], index=_idx(2))
    with pytest.raises(ValueError):
        confidence_scaled_position(s, s, lo=0.5, hi=0.2)
    with pytest.raises(ValueError):
        confidence_scaled_position(s, s, lo=-0.1, hi=1.0)


# --------------------------------------------------------------------------------------
# (2) MONOTONE — higher confidence (base fixed) => >= scale
# --------------------------------------------------------------------------------------
def test_scale_monotone_in_confidence_on_a_ramp():
    n = 60
    base = pd.Series(np.ones(n), index=_idx(n))  # base fixed at 1 => out == scale
    conf = pd.Series(np.linspace(0.0, 1.0, n), index=_idx(n))  # strictly increasing ramp

    out = confidence_scaled_position(base, conf, lo=0.25, hi=1.0)
    # out == scale (since base == 1). On a strictly increasing confidence ramp every point is the
    # max-so-far, so the causal expanding-rank is 1.0 everywhere and the scale is non-decreasing
    # (in fact a constant == hi). The key monotonicity contract: scale never DROPS as confidence
    # rises holding the past fixed.
    diffs = np.diff(out.to_numpy())
    assert (diffs >= -1e-12).all(), "scale must be non-decreasing on an increasing confidence ramp"
    # each point is its own running max -> rank 1.0 -> scale == hi
    assert np.allclose(out.to_numpy(), 1.0, atol=1e-12)


def test_scale_uses_full_range_on_varied_confidence():
    """A confidence series that genuinely varies (not monotone) must exercise scale in [lo, hi]."""
    n = 80
    rng = np.random.default_rng(9)
    base = pd.Series(np.ones(n), index=_idx(n))  # out == scale
    conf = pd.Series(rng.random(n), index=_idx(n))  # non-monotone -> ranks span (0,1]
    lo, hi = 0.25, 1.0
    out = confidence_scaled_position(base, conf, lo=lo, hi=hi).dropna()
    assert out.min() >= lo - 1e-12 and out.max() <= hi + 1e-12
    # the spread is non-trivial: low-rank points are well below hi
    assert out.max() - out.min() > 0.2


def test_higher_confidence_gives_at_least_as_large_scale_pointwise():
    """Holding the past + base fixed, a higher current confidence => >= scale at that point."""
    n = 50
    rng = np.random.default_rng(3)
    base = pd.Series(np.ones(n), index=_idx(n))
    conf = pd.Series(rng.random(n), index=_idx(n))

    out_lowlast = confidence_scaled_position(base, conf, lo=0.25, hi=1.0)
    conf_high = conf.copy()
    conf_high.iloc[-1] = conf.iloc[:-1].max() + 1.0  # make the last reading the new max
    out_highlast = confidence_scaled_position(base, conf_high, lo=0.25, hi=1.0)
    # earlier points unchanged (causal), last point's scale must not decrease
    assert out_highlast.iloc[-1] >= out_lowlast.iloc[-1] - 1e-12
    assert np.allclose(out_highlast.iloc[:-1], out_lowlast.iloc[:-1], equal_nan=True)


# --------------------------------------------------------------------------------------
# (3) CAUSAL — as-of invariance
# --------------------------------------------------------------------------------------
def test_confidence_scaled_is_as_of_invariant():
    base = make_series(n=120, seed=11)
    # confidence with a sharp future shock so full-sample rank differs from prefix rank
    conf = make_series(n=120, future_shock=True, seed=12).abs() + 0.01

    def fn(s: pd.Series) -> pd.Series:
        b = base.reindex(s.index)
        return confidence_scaled_position(b, s, lo=0.25, hi=1.0)

    assert is_as_of_invariant(fn, conf, ks=(30, 60, 90))


def test_inverse_vol_is_as_of_invariant():
    sig = make_series(n=120, seed=21)
    vol = make_series(n=120, future_shock=True, seed=22).abs() + 0.05  # strictly positive vol

    def fn(s: pd.Series) -> pd.Series:
        g = sig.reindex(s.index)
        return inverse_vol_position(g, s, target_vol_ann=0.10, clip=3.0)

    assert is_as_of_invariant(fn, vol, ks=(30, 60, 90))


def test_confidence_scaled_interior_value_unchanged_by_append():
    n = 80
    rng = np.random.default_rng(5)
    base = pd.Series(rng.standard_normal(n), index=_idx(n))
    conf = pd.Series(rng.random(n), index=_idx(n))
    full = confidence_scaled_position(base, conf)
    k = 50
    prefix = confidence_scaled_position(base.iloc[:k], conf.iloc[:k])
    assert np.allclose(full.iloc[:k].to_numpy(), prefix.to_numpy(), equal_nan=True)


# --------------------------------------------------------------------------------------
# (4) inverse_vol_position behaviour
# --------------------------------------------------------------------------------------
def test_inverse_vol_doubling_vol_halves_size_preclip():
    n = 40
    sig = pd.Series(np.ones(n), index=_idx(n))
    # choose vol small enough that the gross factor stays below clip in BOTH cases (pre-clip regime)
    vol = pd.Series(np.full(n, 0.30), index=_idx(n))     # ann ~ 0.30*sqrt(12) ~ 1.039
    target = 0.50
    clip = 100.0  # effectively no clipping for this magnitude

    out1 = inverse_vol_position(sig, vol, target_vol_ann=target, clip=clip)
    out2 = inverse_vol_position(sig, 2.0 * vol, target_vol_ann=target, clip=clip)
    # exactly halved
    assert np.allclose(out2.to_numpy(), 0.5 * out1.to_numpy(), atol=1e-12)
    # sanity: matches closed form target/(vol*sqrt(12))
    expected = target / (0.30 * np.sqrt(12.0))
    assert np.allclose(out1.to_numpy(), expected, atol=1e-12)


def test_inverse_vol_respects_clip():
    n = 30
    sig = pd.Series(np.full(n, 2.0), index=_idx(n))  # |signal| = 2
    vol = pd.Series(np.full(n, 1e-6), index=_idx(n))  # tiny vol -> gross scale huge -> must clip
    clip = 3.0
    out = inverse_vol_position(sig, vol, target_vol_ann=0.10, clip=clip)
    # |out| must be capped at clip * |signal|
    assert (out.abs() <= clip * sig.abs() + 1e-9).all()
    assert np.allclose(out.to_numpy(), clip * 2.0, atol=1e-9)  # hit the cap exactly


def test_inverse_vol_preserves_sign_and_handles_bad_vol():
    n = 12
    sig = pd.Series([1.0, -1.0] * (n // 2), index=_idx(n))
    vol = pd.Series(np.full(n, 0.20), index=_idx(n))
    vol.iloc[3] = 0.0      # non-positive -> NaN out
    vol.iloc[4] = -0.10    # negative     -> NaN out
    out = inverse_vol_position(sig, vol, target_vol_ann=0.10, clip=5.0)
    assert np.isnan(out.iloc[3]) and np.isnan(out.iloc[4])
    good = out.notna()
    # sign preserved (scale >= 0)
    assert (np.sign(out[good]) == np.sign(sig[good])).all()


def test_inverse_vol_rejects_negative_clip():
    s = pd.Series([1.0, 2.0], index=_idx(2))
    with pytest.raises(ValueError):
        inverse_vol_position(s, s, clip=-1.0)
