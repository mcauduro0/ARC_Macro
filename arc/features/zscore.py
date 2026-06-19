"""Rolling z-score, extracted verbatim from FeatureEngine._z_score_rolling.

The mean/std use only trailing data (causal); the caller injects its winsorize function so
the engine can keep its (toggle-aware) winsorize while the z-score logic lives in one place.
A shadow-diff test asserts this reproduces the engine method exactly on real data.
"""

from __future__ import annotations

from typing import Callable

import pandas as pd


def rolling_zscore(
    series: pd.Series,
    window: int,
    std_floor: float,
    winsorize_fn: Callable[[pd.Series], pd.Series],
) -> pd.Series:
    """(x - rolling_mean) / max(rolling_std, std_floor), then winsorize_fn(z.dropna()).

    min_periods = max(24, window // 2) — the engine's convention. ``winsorize_fn`` is injected
    (the engine passes its causal winsorize) so behavior is identical to the original method.
    """
    mp = max(24, window // 2)
    mean_r = series.rolling(window, min_periods=mp).mean()
    std_r = series.rolling(window, min_periods=mp).std().clip(lower=std_floor)
    z = (series - mean_r) / std_r
    return winsorize_fn(z.dropna())
