"""CI-native tests for arc.intelligence.meta_labeling (Phase 5, López de Prado meta-labeling).

No engine, no network, deterministic (fixed seed). Three properties:
  (1) meta_labels correctness on constructed cases: right bet -> 1, wrong -> 0, zero/NaN -> NaN.
  (2) NO LEAKAGE / as-of invariance: a prediction at an interior t is unchanged when later rows are
      appended (the fit uses only index < t); and corrupting the FUTURE (shuffling labels at index > t)
      cannot move a past prediction.
  (3) LEARNABILITY: where a feature genuinely predicts correctness, out-of-sample mean P for the
      true-positive rows exceeds that for the true-negative rows; on PURE NOISE features the
      probabilities cluster near 0.5 (no spurious confidence).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from arc.intelligence.meta_labeling import meta_labels, meta_label_proba


# ---------------------------------------------------------------------------
# (1) meta_labels correctness
# ---------------------------------------------------------------------------
def test_meta_labels_constructed_cases():
    idx = pd.RangeIndex(8)
    pos = pd.Series([1.0, 1.0, -1.0, -1.0, 0.0, np.nan, 2.0, -3.0], index=idx)
    ret = pd.Series([0.5, -0.2, -0.1, 0.3, 0.9, 0.4, np.nan, -0.05], index=idx)
    lab = meta_labels(pos, ret)

    assert lab.iloc[0] == 1.0   # long, market up  -> right
    assert lab.iloc[1] == 0.0   # long, market down -> wrong
    assert lab.iloc[2] == 1.0   # short, market down -> right
    assert lab.iloc[3] == 0.0   # short, market up   -> wrong
    assert np.isnan(lab.iloc[4])  # position == 0 -> no bet -> NaN
    assert np.isnan(lab.iloc[5])  # position NaN  -> NaN
    assert np.isnan(lab.iloc[6])  # return NaN    -> NaN
    assert lab.iloc[7] == 1.0   # short (mag 3), market down -> right (magnitude irrelevant)


def test_meta_labels_zero_return_counts_as_wrong():
    pos = pd.Series([1.0, -1.0])
    ret = pd.Series([0.0, 0.0])  # no move -> a directional bet did not pay -> wrong
    lab = meta_labels(pos, ret)
    assert lab.iloc[0] == 0.0
    assert lab.iloc[1] == 0.0


def test_meta_labels_only_defined_rows_are_non_nan():
    pos = pd.Series([0.0, np.nan, 1.0])
    ret = pd.Series([1.0, 1.0, np.nan])
    lab = meta_labels(pos, ret)
    assert lab.isna().all()  # every row is undefined for one reason or another


# ---------------------------------------------------------------------------
# helpers for the probability tests
# ---------------------------------------------------------------------------
def _make_predictive_data(n: int, seed: int) -> tuple[pd.DataFrame, pd.Series]:
    """A 2-feature dataset where label=1 with probability rising in f0 (f1 is irrelevant noise)."""
    rng = np.random.default_rng(seed)
    f0 = rng.normal(size=n)
    f1 = rng.normal(size=n)
    logit = 1.6 * f0  # genuine signal in f0 only
    p = 1.0 / (1.0 + np.exp(-logit))
    y = (rng.uniform(size=n) < p).astype("float64")
    feats = pd.DataFrame({"f0": f0, "f1": f1})
    return feats, pd.Series(y, name="label")


# ---------------------------------------------------------------------------
# (2) no leakage / as-of invariance
# ---------------------------------------------------------------------------
def test_proba_is_invariant_to_future_rows_being_appended():
    """The probability at an interior t must not change when MORE rows are appended after the frame."""
    feats, y = _make_predictive_data(160, seed=7)
    full = meta_label_proba(feats, y, min_train=36, refit_every=1)

    cut = 110  # an interior, already-predicted row
    feats_trunc = feats.iloc[: cut + 1]
    y_trunc = y.iloc[: cut + 1]
    trunc = meta_label_proba(feats_trunc, y_trunc, min_train=36, refit_every=1)

    # Every prediction up to and including `cut` is identical with or without the future tail.
    a = full.iloc[: cut + 1].to_numpy()
    b = trunc.to_numpy()
    both = ~np.isnan(a) & ~np.isnan(b)
    assert both.any()
    assert np.allclose(a[both], b[both], atol=1e-12, rtol=0.0)


def test_proba_unchanged_when_future_labels_are_shuffled():
    """Corrupting labels STRICTLY AFTER t cannot move the prediction at t (fit uses only index < t)."""
    feats, y = _make_predictive_data(160, seed=11)
    base = meta_label_proba(feats, y, min_train=36, refit_every=1)

    t = 120
    y_corrupt = y.copy()
    rng = np.random.default_rng(999)
    future = np.arange(t + 1, len(y))  # indices strictly after t
    y_corrupt.iloc[future] = rng.permutation(y_corrupt.iloc[future].to_numpy())
    corrupt = meta_label_proba(feats, y_corrupt, min_train=36, refit_every=1)

    # The prediction at t (and any earlier row) must be byte-for-byte unchanged.
    assert np.isfinite(base.iloc[t]) and np.isfinite(corrupt.iloc[t])
    assert base.iloc[t] == corrupt.iloc[t]
    head = base.iloc[: t + 1].to_numpy()
    head_c = corrupt.iloc[: t + 1].to_numpy()
    ok = ~np.isnan(head)
    assert np.array_equal(head[ok], head_c[ok])


def test_proba_nan_before_min_train_and_on_missing_features():
    feats, y = _make_predictive_data(80, seed=3)
    feats.iloc[50, 0] = np.nan  # missing feature -> cannot predict this row
    out = meta_label_proba(feats, y, min_train=36, refit_every=1)

    assert out.iloc[:36].isna().all()       # nothing before min_train labeled history
    assert np.isnan(out.iloc[50])           # missing feature row is NaN
    assert out.iloc[36:].notna().sum() > 0  # but real predictions appear once eligible


def test_refit_cadence_preserves_causality_and_resembles_step_refit():
    """An expanding refit cadence stays causal and gives results close to per-step refit."""
    feats, y = _make_predictive_data(180, seed=5)
    step = meta_label_proba(feats, y, min_train=36, refit_every=1)
    cadence = meta_label_proba(feats, y, min_train=36, refit_every=10)

    # Same support (same rows predicted) and same broad behavior; cadence only changes WHICH past
    # prefix the coefficients came from, never introduces future data.
    assert np.array_equal(step.notna().to_numpy(), cadence.notna().to_numpy())
    both = step.notna() & cadence.notna()
    # correlated and bounded difference -> a stale-but-causal model, not a leak
    assert np.corrcoef(step[both], cadence[both])[0, 1] > 0.9
    assert (cadence[both] >= 0.0).all() and (cadence[both] <= 1.0).all()


# ---------------------------------------------------------------------------
# (3) learnability
# ---------------------------------------------------------------------------
def test_learns_true_signal_out_of_sample():
    """OOS mean P for actually-correct rows > for actually-wrong rows when a feature truly predicts."""
    feats, y = _make_predictive_data(400, seed=42)
    proba = meta_label_proba(feats, y, min_train=50, refit_every=5)

    evaluated = proba.notna()
    # restrict to OOS rows (every prediction here is OOS by construction: fit on index < t)
    p = proba[evaluated]
    truth = y[evaluated]
    mean_p_correct = p[truth == 1.0].mean()   # true positives
    mean_p_wrong = p[truth == 0.0].mean()     # true negatives
    assert mean_p_correct > mean_p_wrong + 0.05, (mean_p_correct, mean_p_wrong)
    # And probabilities are genuinely informative (spread away from a flat 0.5).
    assert p.std() > 0.05


def test_pure_noise_features_give_no_spurious_confidence():
    """With features that carry NO information, predictions hover near the base rate (~0.5), not
    confidently sorted by the (unpredictable) realized outcome."""
    rng = np.random.default_rng(123)
    n = 400
    feats = pd.DataFrame({"a": rng.normal(size=n), "b": rng.normal(size=n)})
    y = pd.Series((rng.uniform(size=n) < 0.5).astype("float64"))  # label independent of features

    proba = meta_label_proba(feats, y, min_train=50, refit_every=5)
    p = proba.dropna()
    assert len(p) > 100
    # centered near the 0.5 base rate...
    assert abs(p.mean() - 0.5) < 0.08
    # ...and crucially NOT able to separate correct from wrong rows out of sample.
    truth = y.reindex(p.index)
    gap = p[truth == 1.0].mean() - p[truth == 0.0].mean()
    assert abs(gap) < 0.05, gap
