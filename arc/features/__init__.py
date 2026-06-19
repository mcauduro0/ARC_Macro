"""Feature transforms extracted from the monolith (strangler-fig, ARCHITECTURE_SOTA.md §3).

One implementation of each feature transform, pure and tested, that the engine delegates to
— shrinking macro_risk_os_v2.py and removing duplicate/divergent logic.
"""

from arc.features.zscore import rolling_zscore
from arc.features.staleness import bounded_ffill

__all__ = ["rolling_zscore", "bounded_ffill"]
