"""Phase 5 — intelligence layer: causal, leakage-safe uncertainty, sizing, and meta-labeling.

These are MEASURED infrastructure, not an alpha claim. The project's ruler says there is no demonstrated
edge beyond carry yet; the three booked sleeves are candidates awaiting forward paper. This package adds
the machinery to (a) quantify predictive uncertainty (credible/conformal intervals), (b) scale position
size by confidence, and (c) meta-label (predict whether the primary signal will be right) — each strictly
point-in-time (expanding/trailing only) so it cannot leak. Whether any of it actually improves a
candidate's deflated, out-of-sample risk-adjusted return is an empirical question answered by
``scripts/measure_intelligence.py`` and, ultimately, the forward holdout — never asserted here.

Measured outcome (scripts/measure_intelligence.py, in-sample, deflated, NOT an alpha claim): sizing did NOT
beat flat for momentum_front or fiscal_hard; nowcast_long showed a TENTATIVE in-sample gain from conformal-
width confidence scaling (deflated DSR +0.060, leverage-invariant) — a hypothesis to confirm on forward
paper, never a promotion. See docs/PHASE5_INTELLIGENCE_2026-06.md.
"""

from __future__ import annotations

from arc.intelligence.meta_labeling import meta_label_proba, meta_labels
from arc.intelligence.online_weights import (
    ewma_performance_weights,
    rolling_inverse_variance_weights,
)
from arc.intelligence.sizing import confidence_scaled_position, inverse_vol_position
from arc.intelligence.uncertainty import (
    conformal_intervals,
    interval_confidence,
    predictive_vol,
)

__all__ = [
    "predictive_vol", "conformal_intervals", "interval_confidence",
    "confidence_scaled_position", "inverse_vol_position",
    "meta_labels", "meta_label_proba",
    "ewma_performance_weights", "rolling_inverse_variance_weights",
]
