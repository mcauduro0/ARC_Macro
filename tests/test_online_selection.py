"""CI-native tests for arc.intelligence.online_selection (no engine, no network).

Asserts the causal ONLINE feature-selection contract:
  (1) CAUSAL / as-of-invariant: an interior importance/frequency row is unchanged when later rows are
      appended (the fit at t uses ONLY rows with index < t);
  (2) RECOVERY: on synthetic data where ONLY feature f0 truly drives the (forward) target, f0 is selected
      far more often across time than the noise features, and pure-noise features are selected rarely;
  (3) NaN before min_train (no strictly-past complete window -> undecided row);
  (4) the mask respects top_k and threshold (count cap, score cut, and their AND combination).

Everything uses fixed seeds. These functions assert NO alpha — they only choose feature SETS causally.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from arc.intelligence.online_selection import (
    online_selected_mask,
    rolling_elasticnet_importance,
    rolling_stability_selection,
)


def _idx(n: int) -> pd.DatetimeIndex:
    return pd.date_range("2010-01-31", periods=n, freq="ME")


def _synthetic(n: int, seed: int, n_noise: int = 4, signal_scale: float = 3.0):
    """Build (features, target) where ONLY f0 drives the target; f1.. are pure noise.

    target_t = signal_scale * f0_t + small_noise  (a strong, stationary linear relation). The other columns
    are independent standard-normal noise with NO relation to the target. Causal-shaped: caller may treat
    ``target`` as already aligned to the decision date."""
    rng = np.random.default_rng(seed)
    cols = ["f0"] + [f"noise{i}" for i in range(n_noise)]
    X = rng.standard_normal((n, 1 + n_noise))
    target = signal_scale * X[:, 0] + 0.25 * rng.standard_normal(n)
    feats = pd.DataFrame(X, index=_idx(n), columns=cols)
    tgt = pd.Series(target, index=_idx(n), name="target")
    return feats, tgt


# --------------------------------------------------------------------------------------
# (1) CAUSALITY / AS-OF INVARIANCE
# --------------------------------------------------------------------------------------
def test_elasticnet_importance_is_asof_invariant():
    """Appending later rows must NOT change earlier importance rows (strictly causal fit)."""
    feats, tgt = _synthetic(120, seed=1)
    full = rolling_elasticnet_importance(feats, tgt, window=48, min_train=24, refit_every=1)

    cut = 90
    part = rolling_elasticnet_importance(
        feats.iloc[:cut], tgt.iloc[:cut], window=48, min_train=24, refit_every=1
    )
    # Compare the overlapping interior rows: must be bit-for-bit identical.
    common = part.index
    pd.testing.assert_frame_equal(full.loc[common], part.loc[common])


def test_stability_selection_is_asof_invariant():
    """Bootstrap frequency rows are reproducible AND causal: earlier rows unchanged by later data."""
    feats, tgt = _synthetic(110, seed=2)
    kw = dict(window=48, min_train=24, n_bootstrap=20, seed=7)
    full = rolling_stability_selection(feats, tgt, **kw)

    cut = 85
    part = rolling_stability_selection(feats.iloc[:cut], tgt.iloc[:cut], **kw)
    common = part.index
    pd.testing.assert_frame_equal(full.loc[common], part.loc[common])


def test_stability_selection_is_reproducible_same_seed():
    feats, tgt = _synthetic(90, seed=3)
    kw = dict(window=48, min_train=24, n_bootstrap=15, seed=11)
    a = rolling_stability_selection(feats, tgt, **kw)
    b = rolling_stability_selection(feats, tgt, **kw)
    pd.testing.assert_frame_equal(a, b)


# --------------------------------------------------------------------------------------
# (2) RECOVERY: only f0 truly drives the target
# --------------------------------------------------------------------------------------
def test_elasticnet_recovers_true_driver():
    """f0 must carry far more average importance than any noise feature; noise stays small."""
    feats, tgt = _synthetic(160, seed=4, n_noise=4, signal_scale=3.0)
    imp = rolling_elasticnet_importance(feats, tgt, window=60, min_train=36, refit_every=1)
    defined = imp.dropna(how="all")
    assert len(defined) > 20

    mean_imp = defined.mean()
    # f0's average |coef| dominates the largest noise feature's by a wide margin.
    noise_max = mean_imp.drop("f0").max()
    assert mean_imp["f0"] > 3.0 * (noise_max + 1e-9), (mean_imp.to_dict())


def test_stability_selects_true_driver_far_more():
    """f0's bootstrap selection frequency >> each noise feature's; noise rarely selected."""
    feats, tgt = _synthetic(160, seed=5, n_noise=4, signal_scale=3.0)
    freq = rolling_stability_selection(
        feats, tgt, window=60, min_train=36, n_bootstrap=40, threshold=0.6, seed=0
    )
    defined = freq.dropna(how="all")
    assert len(defined) > 20

    mean_freq = defined.mean()
    # f0 is selected by the vast majority of bootstraps on average; noise rarely is.
    assert mean_freq["f0"] > 0.8, mean_freq.to_dict()
    noise_mean = mean_freq.drop("f0")
    assert (noise_mean < 0.5).all(), mean_freq.to_dict()
    assert mean_freq["f0"] > 2.0 * noise_mean.max() + 1e-9, mean_freq.to_dict()

    # And via the suggested threshold cut, f0 is the most-frequently-selected feature over time.
    mask = online_selected_mask(freq, threshold=freq.attrs["threshold"])
    sel_rate = mask.loc[defined.index].mean()
    assert sel_rate["f0"] >= sel_rate.drop("f0").max()
    assert sel_rate["f0"] > 0.5


# --------------------------------------------------------------------------------------
# (3) NaN BEFORE min_train
# --------------------------------------------------------------------------------------
def test_nan_before_min_train():
    feats, tgt = _synthetic(80, seed=6)
    min_train = 36
    imp = rolling_elasticnet_importance(feats, tgt, window=60, min_train=min_train, refit_every=1)
    freq = rolling_stability_selection(feats, tgt, window=60, min_train=min_train, n_bootstrap=10, seed=0)

    # No row can be defined before there are min_train STRICTLY-PAST complete rows: the earliest a defined
    # row can appear is index == min_train (rows 0..min_train-1 lie before it).
    for mat in (imp, freq):
        assert mat.iloc[:min_train].isna().all(axis=None), "rows before min_train must be all-NaN"
    # And at least some later rows ARE defined.
    assert imp.iloc[min_train:].notna().any(axis=None)
    assert freq.iloc[min_train:].notna().any(axis=None)


# --------------------------------------------------------------------------------------
# (4) MASK respects top_k / threshold
# --------------------------------------------------------------------------------------
def test_mask_respects_top_k():
    idx = _idx(3)
    cols = ["a", "b", "c", "d"]
    df = pd.DataFrame(
        [[0.9, 0.1, 0.5, 0.3],
         [np.nan, np.nan, np.nan, np.nan],   # undecided row -> all-False
         [0.2, 0.8, 0.7, 0.05]],
        index=idx, columns=cols,
    )
    mask = online_selected_mask(df, top_k=2)
    # Row 0: top-2 are a(0.9), c(0.5).
    assert mask.iloc[0].tolist() == [True, False, True, False]
    # Row 1: all-NaN -> all-False.
    assert mask.iloc[1].tolist() == [False, False, False, False]
    # Row 2: top-2 are b(0.8), c(0.7).
    assert mask.iloc[2].tolist() == [False, True, True, False]
    # Never more than top_k selected per defined row.
    assert (mask.sum(axis=1) <= 2).all()


def test_mask_respects_threshold():
    idx = _idx(2)
    cols = ["a", "b", "c"]
    df = pd.DataFrame([[0.7, 0.6, 0.4], [0.61, 0.59, 0.9]], index=idx, columns=cols)
    mask = online_selected_mask(df, threshold=0.6)
    # strictly greater than 0.6
    assert mask.iloc[0].tolist() == [True, False, False]
    assert mask.iloc[1].tolist() == [True, False, True]


def test_mask_top_k_and_threshold_is_conservative_and():
    idx = _idx(1)
    cols = ["a", "b", "c", "d"]
    df = pd.DataFrame([[0.9, 0.65, 0.62, 0.1]], index=idx, columns=cols)
    # threshold 0.6 admits {a,b,c}; top_k=2 admits {a,b}; AND -> {a,b}.
    mask = online_selected_mask(df, top_k=2, threshold=0.6)
    assert mask.iloc[0].tolist() == [True, True, False, False]


def test_mask_default_rule_is_positive():
    idx = _idx(1)
    cols = ["a", "b", "c"]
    df = pd.DataFrame([[0.0, 0.3, -0.1]], index=idx, columns=cols)
    mask = online_selected_mask(df)  # default: value > 0
    assert mask.iloc[0].tolist() == [False, True, False]


def test_refit_every_carries_forward_causally():
    """refit_every>1 carries the last fit forward but stays as-of-invariant on interior rows."""
    feats, tgt = _synthetic(120, seed=8)
    full = rolling_elasticnet_importance(feats, tgt, window=48, min_train=24, refit_every=3)
    cut = 95
    part = rolling_elasticnet_importance(feats.iloc[:cut], tgt.iloc[:cut], window=48, min_train=24, refit_every=3)
    pd.testing.assert_frame_equal(full.loc[part.index], part)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
