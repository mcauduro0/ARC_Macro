"""Behavioural tests for the causal transforms (beyond the as-of invariance canary)."""

from __future__ import annotations

import numpy as np
import pandas as pd

from arc.causal import causal_winsorize, rolling_zscore
from tests.canary import make_series


def test_causal_winsorize_actually_clips_extremes():
    """It must still bound outliers — just causally. A late spike, once enough history
    exists, gets clipped to the trailing upper quantile (which is < the raw spike)."""
    s = make_series(n=120, future_shock=False, seed=1)
    s.iloc[100] = s.iloc[:100].max() + 50  # a spike with 100 obs of history behind it
    w = causal_winsorize(s, lower=0.05, upper=0.95, window=60, min_periods=24)
    assert w.iloc[100] < s.iloc[100], "spike should be clipped down"
    assert w.iloc[100] >= s.iloc[:101].quantile(0.90) - 1e6  # sane bound, not -inf


def test_causal_winsorize_leaves_early_points_unclipped():
    """Before min_periods there is no past distribution to clip with: pass values through."""
    s = make_series(n=120, seed=2)
    w = causal_winsorize(s, window=60, min_periods=24)
    # first (min_periods-1) expanding/rolling quantiles are NaN -> unclipped == original
    assert np.allclose(w.iloc[:23].to_numpy(), s.iloc[:23].to_numpy())


def test_rolling_zscore_mean_and_std_are_backward_looking():
    s = make_series(n=120, seed=3)
    z = rolling_zscore(s, window=36, min_periods=24, std_floor=0.5)
    # recompute z at one index by hand using only the trailing window -> must match
    i = 80
    win = s.iloc[i - 36 + 1 : i + 1]
    expected = (s.iloc[i] - win.mean()) / max(win.std(), 0.5)
    assert abs(z.iloc[i] - expected) < 1e-9


def test_rolling_zscore_std_floor_prevents_blowup():
    """A near-constant series would give std~0 and explode without the floor."""
    s = pd.Series(np.r_[np.zeros(60), 0.001 * np.arange(60)],
                  index=pd.date_range("2010-01-31", periods=120, freq="ME"))
    z = rolling_zscore(s, window=36, min_periods=24, std_floor=0.5)
    assert np.isfinite(z.iloc[60:]).all()


def test_winsor_option_matches_standalone():
    s = make_series(n=120, seed=4)
    z_plain = rolling_zscore(s, window=48, min_periods=24, std_floor=0.5)
    z_wins = rolling_zscore(s, window=48, min_periods=24, std_floor=0.5, winsor=(0.05, 0.95))
    manual = causal_winsorize(z_plain, 0.05, 0.95, window=48, min_periods=24)
    # compare on the overlapping non-NaN region
    mask = z_wins.notna() & manual.notna()
    assert np.allclose(z_wins[mask].to_numpy(), manual[mask].to_numpy(), atol=1e-9)
