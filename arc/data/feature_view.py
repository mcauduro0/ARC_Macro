"""Point-in-time features = as_of() (vintage-correct data) + causal transform.

This composes the two leakage defenses: the bitemporal store guarantees no future *data*
leaks in, and arc.causal guarantees no future *statistics* leak in. A feature built here
is point-in-time correct end to end.
"""

from __future__ import annotations

from datetime import datetime
from typing import Callable, Optional

import pandas as pd

from arc.causal import rolling_zscore
from arc.data.store import BitemporalStore


def pit_feature(
    store: BitemporalStore,
    asof_ts: datetime,
    series_id: str,
    transform: Callable[[pd.Series], pd.Series],
) -> pd.Series:
    """Apply a causal transform to the as-of view of a series. Returns the full transformed
    series (event_time-indexed); the last value is the live feature reading at asof_ts."""
    s = store.as_of_series(asof_ts, series_id)
    return transform(s)


def pit_zscore(
    store: BitemporalStore,
    asof_ts: datetime,
    series_id: str,
    *,
    window: int = 60,
    min_periods: Optional[int] = None,
    std_floor: float = 0.5,
    winsor: tuple[float, float] | None = (0.05, 0.95),
) -> pd.Series:
    """Convenience: point-in-time rolling z-score of a series."""
    return pit_feature(
        store,
        asof_ts,
        series_id,
        lambda s: rolling_zscore(s, window=window, min_periods=min_periods, std_floor=std_floor, winsor=winsor),
    )
