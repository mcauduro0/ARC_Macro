"""Shared helpers for leakage (as-of invariance) canaries.

The core property of a point-in-time transform: appending future data must not change
any past output. We test it by comparing ``fn(full)[:k]`` against ``fn(full[:k])``.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def make_series(n: int = 120, *, future_shock: bool = False, seed: int = 7) -> pd.Series:
    """A monthly-ish series; optionally inject extreme values in the LAST third so that
    full-sample statistics (quantiles/mean/std) differ sharply from prefix statistics."""
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2010-01-31", periods=n, freq="ME")
    x = pd.Series(rng.standard_normal(n), index=idx).cumsum() * 0.3
    if future_shock:
        k = n // 3  # NB: -n // 3 == (-n)//3 != -(n//3) for n not divisible by 3
        x.iloc[-k:] += rng.standard_normal(k) * 12.0  # large future outliers
    return x


def as_of_pair(fn, s: pd.Series, k: int):
    """Return (full_truncated_to_k, computed_on_prefix_k) as numpy arrays."""
    full = pd.Series(fn(s)).to_numpy()[:k]
    prefix = pd.Series(fn(s.iloc[:k])).to_numpy()
    return full, prefix


def is_as_of_invariant(fn, s: pd.Series, ks=(30, 60, 90), atol: float = 1e-9) -> bool:
    """True iff fn satisfies fn(s)[:k] == fn(s[:k]) for all k (NaN-aware)."""
    for k in ks:
        if k > len(s):
            continue
        full, prefix = as_of_pair(fn, s, k)
        if not np.allclose(full, prefix, equal_nan=True, atol=atol):
            return False
    return True
