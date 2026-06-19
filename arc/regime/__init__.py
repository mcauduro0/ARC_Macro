"""Causal regime inference — fixes the smoothed-HMM look-ahead (audit regime-1).

The monolith feeds ``hmm.predict_proba`` (the forward-backward *smoothed* posterior, which
conditions on the WHOLE observation sequence including the future) into historical features.
``filtered_posteriors`` returns the causal object P(state_t | o_1..o_t) instead.
"""

from arc.regime.filtered import filtered_posteriors

__all__ = ["filtered_posteriors"]
