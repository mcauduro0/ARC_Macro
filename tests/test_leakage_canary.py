"""Leakage canaries — the quantitative proof of audit findings feat-1 / eq-2.

These tests demonstrate that the LEGACY full-sample winsorize leaks future information,
and that the causal replacement does not. The legacy function below is a faithful copy of
macro_risk_os_v2.py:166-172 (we copy rather than import because the engine module pulls
xgboost/hmmlearn at import time; copying keeps the canary runnable everywhere).

When the engine is refactored to use arc.causal, the "legacy leaks" test becomes the
regression guard that must never be reintroduced.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from arc.causal import causal_winsorize, rolling_zscore
from tests.canary import is_as_of_invariant, make_series, as_of_pair


def legacy_winsorize(s: pd.Series, lower: float = 0.05, upper: float = 0.95) -> pd.Series:
    """Faithful copy of macro_risk_os_v2.py:166-172 — the leaky version (full-sample quantiles)."""
    if len(s) < 10:
        return s
    lo = s.quantile(lower)
    hi = s.quantile(upper)
    return s.clip(lo, hi)


def legacy_zscore(s: pd.Series, window: int = 60) -> pd.Series:
    """Faithful copy of the leaky _z_score_rolling (macro_risk_os_v2.py:680-688):
    rolling mean/std (causal) but a FINAL full-sample winsorize (look-ahead)."""
    mean_r = s.rolling(window, min_periods=max(24, window // 2)).mean()
    std_r = s.rolling(window, min_periods=max(24, window // 2)).std().clip(lower=0.5)
    z = (s - mean_r) / std_r
    return legacy_winsorize(z.dropna())


def test_legacy_winsorize_leaks_lookahead():
    """The current winsorize is NOT as-of invariant: adding future outliers changes past
    clipped values. This is the bug; if this ever stops failing for the legacy fn the
    canary is broken."""
    s = make_series(future_shock=True)
    assert not is_as_of_invariant(legacy_winsorize, s), (
        "legacy full-sample winsorize unexpectedly looked causal"
    )
    # Show the concrete divergence at a specific cut.
    full, prefix = as_of_pair(legacy_winsorize, s, 60)
    assert not np.allclose(full, prefix, equal_nan=True), "expected past values to change"


def test_legacy_zscore_leaks_lookahead():
    s = make_series(future_shock=True)
    assert not is_as_of_invariant(legacy_zscore, s), (
        "legacy _z_score_rolling unexpectedly looked causal"
    )


def test_causal_winsorize_is_as_of_invariant():
    """The fix: causal winsorize never lets the future change the past."""
    for shock in (False, True):
        s = make_series(future_shock=shock)
        assert is_as_of_invariant(lambda x: causal_winsorize(x, window=60, min_periods=24), s)


def test_causal_zscore_is_as_of_invariant():
    for shock in (False, True):
        s = make_series(future_shock=shock)
        fn = lambda x: rolling_zscore(x, window=60, min_periods=24, std_floor=0.5, winsor=(0.05, 0.95))
        assert is_as_of_invariant(fn, s)
