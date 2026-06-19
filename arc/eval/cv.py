"""Purged & embargoed cross-validation (Lopez de Prado).

Standard k-fold leaks when labels span multiple periods: a train sample whose label window
overlaps the test window shares information with it. PurgedKFold removes those, plus an
embargo after each test block. ``combinatorial_purged_splits`` (CPCV) yields many
leakage-free train/test paths, giving a distribution of OOS performance (the input to PBO).
"""

from __future__ import annotations

import itertools
from typing import Iterator, Optional

import numpy as np
import pandas as pd


def t1_from_horizon(index: pd.Index, horizon: int) -> pd.Series:
    """Label-end time per sample for a fixed forward horizon: index[i] -> index[i+horizon]
    (clamped to the last timestamp). Used to drive purging."""
    n = len(index)
    ends = [index[min(i + horizon, n - 1)] for i in range(n)]
    return pd.Series(ends, index=index)


def _purge_train(
    train_idx: np.ndarray,
    test_idx: np.ndarray,
    start_times: np.ndarray,
    end_times: np.ndarray,
    embargo_n: int,
    n_total: int,
) -> np.ndarray:
    """Drop train samples whose label interval overlaps any test sample's interval, plus an
    embargo of ``embargo_n`` positions after each test index."""
    if len(test_idx) == 0:
        return train_idx
    test_start = start_times[test_idx].min()
    test_end = end_times[test_idx].max()
    keep = []
    embargoed = set()
    for p in test_idx:
        for q in range(p + 1, min(p + 1 + embargo_n, n_total)):
            embargoed.add(q)
    for j in train_idx:
        if j in embargoed:
            continue
        # interval overlap with the [test_start, test_end] envelope
        if start_times[j] <= test_end and end_times[j] >= test_start:
            continue
        keep.append(j)
    return np.array(keep, dtype=int)


class PurgedKFold:
    """K-fold with purging + embargo. ``t1`` maps each sample (by position via the X index)
    to its label-end time; default = identity (horizon 0)."""

    def __init__(self, n_splits: int = 5, t1: Optional[pd.Series] = None, embargo: float = 0.0):
        if n_splits < 2:
            raise ValueError("n_splits must be >= 2")
        self.n_splits = n_splits
        self.t1 = t1
        self.embargo = embargo

    def get_n_splits(self, X=None, y=None, groups=None) -> int:
        return self.n_splits

    def split(self, X, y=None, groups=None) -> Iterator[tuple[np.ndarray, np.ndarray]]:
        index = X.index if hasattr(X, "index") else pd.RangeIndex(len(X))
        n = len(index)
        t1 = self.t1 if self.t1 is not None else pd.Series(index, index=index)
        start_times = np.asarray(index)
        end_times = np.asarray(t1.reindex(index).values)
        embargo_n = int(n * self.embargo)
        all_idx = np.arange(n)
        for fold in np.array_split(all_idx, self.n_splits):
            test_idx = fold
            train_idx = np.setdiff1d(all_idx, test_idx)
            train_idx = _purge_train(train_idx, test_idx, start_times, end_times, embargo_n, n)
            yield train_idx, test_idx


def combinatorial_purged_splits(
    n_samples: int,
    n_groups: int = 6,
    n_test_groups: int = 2,
    *,
    t1: Optional[pd.Series] = None,
    index: Optional[pd.Index] = None,
    embargo: float = 0.0,
) -> list[tuple[np.ndarray, np.ndarray]]:
    """CPCV: partition samples into ``n_groups`` contiguous groups; for every combination of
    ``n_test_groups`` test groups, return (train, test) with purging + embargo. The number of
    paths is C(n_groups, n_test_groups)."""
    if not (1 <= n_test_groups < n_groups):
        raise ValueError("require 1 <= n_test_groups < n_groups")
    idx = pd.RangeIndex(n_samples) if index is None else index
    start_times = np.asarray(idx)
    end_times = np.asarray((t1.reindex(idx).values if t1 is not None else idx))
    embargo_n = int(n_samples * embargo)
    groups = np.array_split(np.arange(n_samples), n_groups)
    out = []
    for combo in itertools.combinations(range(n_groups), n_test_groups):
        test_idx = np.sort(np.concatenate([groups[g] for g in combo]))
        train_idx = np.setdiff1d(np.arange(n_samples), test_idx)
        train_idx = _purge_train(train_idx, test_idx, start_times, end_times, embargo_n, n_samples)
        out.append((train_idx, test_idx))
    return out
