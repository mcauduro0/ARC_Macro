"""Honest edge search (Phase 4, ARCHITECTURE_SOTA.md §5).

The audit verdict: the historical track record was carry + period-concentrated regime-timing, not
demonstrated stationary alpha. With the ruler trustworthy (arc.eval) and the feature pipeline proven
point-in-time (Phase 3), this package searches for genuinely predictive, orthogonal-to-carry signals —
each evaluated through the full gate battery and deflated for the number of hypotheses tested.
"""

from arc.research.signals import (
    SignalThresholds,
    evaluate_signal,
    rank_signals,
)
from arc.research.sleeve import (
    causal_position,
    momentum_signal,
    momentum_sleeve_returns,
    signal_sleeve_returns,
    sleeve_stats,
)

__all__ = [
    "SignalThresholds", "evaluate_signal", "rank_signals",
    "causal_position", "momentum_signal", "momentum_sleeve_returns", "signal_sleeve_returns",
    "sleeve_stats",
]
