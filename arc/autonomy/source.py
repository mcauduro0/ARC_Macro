"""The as-of return provider — the single look-ahead boundary, made pure and CI-testable (Phase 7).

The pure paper modules push the causal slice to the caller. That caller is this provider: it wraps a
monthly return series with an EXPLICIT publication-lag rule so a month-M return is invisible until its
knowledge time. Keeping it here (not only in the engine-touching script) means the one place leakage can
enter has its own CI-native test with synthetic vintages.

Rule: a month-end-M return is knowable ``pub_lag_days`` after month end (default 1 day => the May return
is known June 1, never within May). ``provider(asof)`` returns only returns with knowledge_time <= asof.
"""

from __future__ import annotations

from typing import Callable

import pandas as pd


def knowledge_time(month_end_ts, pub_lag_days: int = 1) -> pd.Timestamp:
    """When a month-end-M return becomes knowable. Default: 1 day after month end."""
    return pd.Timestamp(month_end_ts) + pd.Timedelta(days=pub_lag_days)


def monthly_return_provider(returns: pd.Series, pub_lag_days: int = 1) -> Callable[[object], pd.Series]:
    """Return a callable ``provider(asof) -> Series`` exposing only returns known by ``asof``."""
    r = pd.Series(returns).dropna()
    r.index = [pd.Timestamp(i) + pd.offsets.MonthEnd(0) for i in r.index]
    r = r.sort_index()

    def provider(asof) -> pd.Series:
        cutoff = pd.Timestamp(asof)
        visible = [m for m in r.index if knowledge_time(m, pub_lag_days) <= cutoff]
        return r.loc[visible]

    return provider


__all__ = ["monthly_return_provider", "knowledge_time"]
