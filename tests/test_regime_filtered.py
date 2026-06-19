"""Filtered (causal) HMM posteriors vs smoothed predict_proba (audit regime-1).

The defining causal property: the filtered posterior at month t must be invariant to observations
after t. We verify filtered_posteriors satisfies it and that hmmlearn's smoothed predict_proba does
NOT — which is exactly why the smoothed probs were a look-ahead as a historical feature.
"""

from __future__ import annotations

import importlib.util

import numpy as np
import pytest

_HAS_HMM = importlib.util.find_spec("hmmlearn") is not None

pytestmark = pytest.mark.skipif(not _HAS_HMM, reason="hmmlearn not installed")


def _fit_model(seed=0):
    from hmmlearn.hmm import GaussianHMM

    rng = np.random.default_rng(seed)
    # two OVERLAPPING regimes (mean +-1.2, std 1.0) so the posterior is genuinely ambiguous at
    # interior points — that is where smoothing (conditioning on the future) actually differs from
    # filtering, i.e. where the look-ahead bites. Perfectly separated regimes hide the bug.
    a = rng.normal(-1.2, 1.0, size=(100, 2))
    b = rng.normal(1.2, 1.0, size=(100, 2))
    X = np.vstack([a, b, a[:40]])  # two regime switches, length 240
    model = GaussianHMM(n_components=2, covariance_type="full", n_iter=100, random_state=42, tol=0.01)
    model.fit(X)
    return model, X


def test_filtered_shape_and_normalization():
    from arc.regime import filtered_posteriors

    model, X = _fit_model()
    post = filtered_posteriors(model, X)
    assert post.shape == (len(X), 2)
    assert np.allclose(post.sum(axis=1), 1.0, atol=1e-9)
    assert (post >= -1e-12).all() and (post <= 1 + 1e-9).all()


def test_filtered_is_causal_prefix_invariant():
    """filtered_posteriors(X[:k]) == filtered_posteriors(X)[:k] for all k — past ⟂ future."""
    from arc.regime import filtered_posteriors

    model, X = _fit_model()
    full = filtered_posteriors(model, X)
    for k in (30, 80, 150, 199):
        prefix = filtered_posteriors(model, X[:k])
        assert np.allclose(prefix, full[:k], atol=1e-8), f"filtered not prefix-invariant at k={k}"


def test_smoothed_is_not_causal():
    """Sanity: hmmlearn predict_proba (smoothed) DOES depend on the future, so the prefix-invariance
    above is a real, non-trivial property — not something any posterior would satisfy. Under regime
    ambiguity the smoothed prefix differs from the full-sequence smoothed value."""
    model, X = _fit_model()
    full_smoothed = model.predict_proba(X)
    k = 100  # near the first regime switch
    prefix_smoothed = model.predict_proba(X[:k])
    diff = np.abs(prefix_smoothed[-5:] - full_smoothed[k - 5:k]).max()
    assert diff > 1e-6, "expected smoothed posteriors to be future-dependent near a switch"


def test_filtered_differs_from_smoothed_interior():
    """The substantive claim: filtered != smoothed at interior points (it equals it only at the very
    last observation, where there is no future). If they were identical everywhere, the fix would be
    a no-op."""
    from arc.regime import filtered_posteriors

    model, X = _fit_model()
    filt = filtered_posteriors(model, X)
    smooth = model.predict_proba(X)
    # last row: filtered == smoothed (no future to condition on)
    assert np.allclose(filt[-1], smooth[-1], atol=1e-6)
    # somewhere in the interior they must differ (the look-ahead)
    assert np.abs(filt[:-1] - smooth[:-1]).max() > 1e-3


def test_filtered_tracks_regime():
    """The filtered posterior should still identify the dominant regime in each block."""
    from arc.regime import filtered_posteriors

    model, X = _fit_model()
    post = filtered_posteriors(model, X)
    # first block (obs ~ -2) and second block (obs ~ +2) should be dominated by different states
    first_state = int(post[20:80].mean(axis=0).argmax())
    second_state = int(post[120:180].mean(axis=0).argmax())
    assert first_state != second_state
