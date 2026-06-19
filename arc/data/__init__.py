"""Bitemporal point-in-time data platform (Phase 1).

The single causal boundary of the whole system: every series is stored append-only with
both an ``event_time`` (the period the datum describes) and a ``knowledge_time`` (the
earliest wall-clock instant the value was KNOWABLE, = publication lag applied). Revisions
are NEW rows, never updates, so full vintage history is preserved.

``as_of(t)`` is the one primitive every consumer (backtest, live signal, risk marks,
execution) must use — it returns, per event_time, the latest value with
``knowledge_time <= t``. This eliminates the audit's #1 macro leakage (no vintage /
publication lag) and the "last-write-wins CSV destroys revisions" defect in
data_collector.save_series.
"""

from arc.data.observation import Observation, compute_knowledge_time
from arc.data.store import BitemporalStore, as_of_long, as_of_wide

__all__ = [
    "Observation",
    "compute_knowledge_time",
    "BitemporalStore",
    "as_of_long",
    "as_of_wide",
]
