"""CI-native tests for arc.intelligence.uncertainty (pure: pandas/numpy/sklearn only, no engine, no net).

We assert the four contracted properties:
  (1) AS-OF INVARIANCE: an interior conformal interval is unchanged whether or not later data exists
      (split-conformal calibrates on STRICTLY-PAST residuals -> appending the future cannot move it);
  (2) COVERAGE SANITY: on synthetic pred/realized with known noise, realized falls in [lo, hi] at roughly
      (1 - alpha) frequency over the evaluated region (tolerance band);
  (3) predictive_vol is causal (interior value unchanged by appending later returns) and > 0;
  (4) interval_confidence rises as width falls (monotone on a monotone width series) and is bounded (0, 1].
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from arc.intelligence.uncertainty import (
    conformal_intervals,
    interval_confidence,
    predictive_vol,
)


def _idx(n: int) -> pd.DatetimeIndex:
    return pd.date_range("2010-01-31", periods=n, freq="ME")


def _synthetic(n: int = 400, *, sigma: float = 1.0, seed: int = 0):
    """A smooth-ish prediction plus homoscedastic noise -> realized; stationary residuals so
    split-conformal coverage is meaningful."""
    rng = np.random.default_rng(seed)
    idx = _idx(n)
    signal = pd.Series(np.sin(np.arange(n) / 11.0) * 3.0, index=idx)
    noise = pd.Series(rng.standard_normal(n) * sigma, index=idx)
    pred = signal
    realized = signal + noise
    return pred, realized


# ----------------------------------------------------------------------------------------------------------
# (1) AS-OF INVARIANCE
# ----------------------------------------------------------------------------------------------------------

def test_conformal_intervals_are_as_of_invariant():
    """An interior row's [point, lo, hi, width] must be identical whether computed on the full series or on
    a prefix that stops just after that row. This is the leakage canary: q[t] depends only on residuals at
    index < t, so the future is irrelevant to it."""
    pred, realized = _synthetic(n=300, seed=1)
    full = conformal_intervals(pred, realized, alpha=0.1, min_train=24)

    # Evaluate at several interior decision dates; cut the prefix a few rows AFTER the date so the date is
    # strictly interior to the prefix (not on its frontier).
    for t in (60, 120, 200):
        T = t + 5  # prefix includes a small margin of "future" beyond t
        sub = conformal_intervals(pred.iloc[:T], realized.iloc[:T], alpha=0.1, min_train=24)
        a = full.iloc[t]
        b = sub.iloc[t]
        assert np.allclose(a.to_numpy(), b.to_numpy(), equal_nan=True, atol=1e-12), (
            f"as-of leak at t={t}: full={a.to_dict()} vs prefix={b.to_dict()}")


def test_conformal_band_does_not_use_the_predicted_rows_own_realized():
    """Stronger causality probe: corrupting realized at and after an interior row must NOT change that row's
    band (the band is calibrated on strictly-past residuals only)."""
    pred, realized = _synthetic(n=300, seed=2)
    base = conformal_intervals(pred, realized, alpha=0.1, min_train=24)

    t = 150
    poisoned = realized.copy()
    poisoned.iloc[t:] += 1000.0  # blow up the present + future outcomes
    after = conformal_intervals(pred, poisoned, alpha=0.1, min_train=24)

    assert np.allclose(base.iloc[t].to_numpy(), after.iloc[t].to_numpy(), equal_nan=True, atol=1e-9), (
        "band at t changed when t..end realized was poisoned -> it leaked present/future outcomes")
    # And of course rows strictly before t are untouched too.
    assert np.allclose(
        base.iloc[:t].to_numpy(), after.iloc[:t].to_numpy(), equal_nan=True, atol=1e-9)


# ----------------------------------------------------------------------------------------------------------
# (2) COVERAGE SANITY
# ----------------------------------------------------------------------------------------------------------

def test_conformal_coverage_is_near_one_minus_alpha():
    """Over the evaluated (finite-band) region, empirical coverage should sit close to (1 - alpha)."""
    alpha = 0.1
    pred, realized = _synthetic(n=600, sigma=1.0, seed=3)
    ci = conformal_intervals(pred, realized, alpha=alpha, min_train=50)

    mask = ci["lo"].notna() & ci["hi"].notna() & realized.notna()
    y = realized[mask]
    lo = ci["lo"][mask]
    hi = ci["hi"][mask]
    covered = ((y >= lo) & (y <= hi)).mean()

    assert mask.sum() > 200, "too few evaluated rows to judge coverage"
    # Split-conformal is finite-sample valid (>= 1-alpha in expectation); allow a tolerance band for sampling.
    assert 0.86 <= covered <= 0.985, f"coverage {covered:.3f} not within tolerance of {1 - alpha:.2f}"


def test_conformal_coverage_holds_at_higher_alpha():
    """Sanity at a second level: ~80% target -> empirical coverage in a band around 0.80."""
    alpha = 0.2
    pred, realized = _synthetic(n=600, sigma=1.5, seed=4)
    ci = conformal_intervals(pred, realized, alpha=alpha, min_train=50)
    mask = ci["lo"].notna() & realized.notna()
    y, lo, hi = realized[mask], ci["lo"][mask], ci["hi"][mask]
    covered = ((y >= lo) & (y <= hi)).mean()
    assert 0.74 <= covered <= 0.92, f"coverage {covered:.3f} off target {1 - alpha:.2f}"


def test_width_is_two_q_and_positive():
    pred, realized = _synthetic(n=300, seed=5)
    ci = conformal_intervals(pred, realized, alpha=0.1, min_train=24)
    fin = ci.dropna()
    assert (fin["width"] > 0).all()
    assert np.allclose((fin["hi"] - fin["lo"]).to_numpy(), fin["width"].to_numpy(), atol=1e-12)
    # Symmetric about the point.
    assert np.allclose((fin["point"] - fin["lo"]).to_numpy(),
                       (fin["hi"] - fin["point"]).to_numpy(), atol=1e-12)


def test_conformal_min_train_gates_nan():
    pred, realized = _synthetic(n=120, seed=6)
    mt = 30
    ci = conformal_intervals(pred, realized, alpha=0.1, min_train=mt)
    # The first row that can possibly have a finite band needs >= mt strictly-past residuals, i.e. index mt.
    assert ci["lo"].iloc[:mt].isna().all(), "band appeared before min_train strictly-past residuals existed"
    assert ci["lo"].iloc[mt:].notna().any(), "band never appeared after min_train"


# ----------------------------------------------------------------------------------------------------------
# (3) predictive_vol: causal and positive
# ----------------------------------------------------------------------------------------------------------

def test_predictive_vol_is_causal():
    rng = np.random.default_rng(7)
    r = pd.Series(rng.standard_normal(200) * 0.02, index=_idx(200))
    full = predictive_vol(r, window=12, min_periods=12)
    for t in (40, 90, 150):
        T = t + 8
        sub = predictive_vol(r.iloc[:T], window=12, min_periods=12)
        assert np.isclose(full.iloc[t], sub.iloc[t], equal_nan=True, atol=1e-12), (
            f"predictive_vol leaked future at t={t}")


def test_predictive_vol_positive_and_matches_trailing_std():
    rng = np.random.default_rng(8)
    r = pd.Series(rng.standard_normal(120) * 0.03, index=_idx(120))
    vol = predictive_vol(r, window=12, min_periods=12)
    fin = vol.dropna()
    assert (fin > 0).all(), "trailing std of noisy returns must be > 0"
    # Recompute one value by hand from the trailing window only.
    i = 80
    win = r.iloc[i - 12 + 1 : i + 1]
    assert abs(vol.iloc[i] - win.std(ddof=1)) < 1e-12


def test_predictive_vol_nan_before_min_periods():
    rng = np.random.default_rng(9)
    r = pd.Series(rng.standard_normal(60), index=_idx(60))
    vol = predictive_vol(r, window=12, min_periods=12)
    assert vol.iloc[:11].isna().all()
    assert vol.iloc[11:].notna().all()


# ----------------------------------------------------------------------------------------------------------
# (4) interval_confidence: monotone in width, bounded (0, 1]
# ----------------------------------------------------------------------------------------------------------

def test_interval_confidence_rises_as_width_falls():
    """On a strictly DECREASING width series, confidence must be NON-DECREASING (narrower-than-past ->
    higher confidence)."""
    n = 120
    width = pd.Series(np.linspace(5.0, 1.0, n), index=_idx(n))  # monotonically shrinking band
    conf = interval_confidence(width, min_periods=24)
    fin = conf.dropna()
    diffs = np.diff(fin.to_numpy())
    assert (diffs >= -1e-9).all(), "confidence should not fall while width is strictly falling"
    assert fin.iloc[-1] >= fin.iloc[0], "end (narrowest) should be at least as confident as start"


def test_interval_confidence_falls_as_width_rises():
    n = 120
    width = pd.Series(np.linspace(1.0, 5.0, n), index=_idx(n))  # widening band
    conf = interval_confidence(width, min_periods=24)
    fin = conf.dropna()
    diffs = np.diff(fin.to_numpy())
    assert (diffs <= 1e-9).all(), "confidence should not rise while width is strictly rising"


def test_interval_confidence_is_bounded_open_zero_to_one():
    rng = np.random.default_rng(10)
    width = pd.Series(np.abs(rng.standard_normal(200)) + 0.1, index=_idx(200))
    conf = interval_confidence(width, min_periods=24)
    fin = conf.dropna()
    assert (fin > 0.0).all(), "confidence must be strictly > 0 (open lower bound)"
    assert (fin <= 1.0 + 1e-12).all(), "confidence must be <= 1"


def test_interval_confidence_is_causal():
    rng = np.random.default_rng(11)
    width = pd.Series(np.abs(rng.standard_normal(200)) + 0.5, index=_idx(200))
    full = interval_confidence(width, min_periods=24)
    for t in (40, 100, 160):
        T = t + 7
        sub = interval_confidence(width.iloc[:T], min_periods=24)
        assert np.isclose(full.iloc[t], sub.iloc[t], equal_nan=True, atol=1e-12), (
            f"interval_confidence leaked future at t={t}")


def test_interval_confidence_nan_before_min_periods_and_on_bad_width():
    n = 60
    width = pd.Series(np.linspace(2.0, 1.0, n), index=_idx(n))
    width.iloc[40] = np.nan
    width.iloc[45] = 0.0  # non-positive width -> invalid
    conf = interval_confidence(width, min_periods=24)
    assert conf.iloc[:23].isna().all(), "confidence before min_periods must be NaN"
    assert pd.isna(conf.iloc[40]), "NaN width -> NaN confidence"
    assert pd.isna(conf.iloc[45]), "non-positive width -> NaN confidence"
