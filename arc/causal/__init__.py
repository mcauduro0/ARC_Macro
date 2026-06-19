"""Leakage-free (point-in-time) transforms.

These are the *fix* for the audit's pervasive look-ahead findings (feat-1, eq-2): the
current ``_z_score_rolling`` ends in a full-sample ``winsorize`` (macro_risk_os_v2.py
:166-172, :688) whose 5/95 quantiles are computed over the ENTIRE series (incl. the
future). Every transform here guarantees the *as-of invariance* property: the value at
time t depends only on data up to and including t — verified by the leakage canaries in
tests/.
"""

from arc.causal.transforms import causal_winsorize, rolling_zscore

__all__ = ["causal_winsorize", "rolling_zscore"]
