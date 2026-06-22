"""Phase 6 — risk SOTA: VaR/ES pre-trade gates and forward-looking covariance (EWMA / DCC-GARCH).

Pure, causal, CI-tested risk infrastructure. These quantify and bound risk; they make no alpha claim.
"""

from __future__ import annotations

from arc.risk.covariance import (
    dcc_correlation,
    dcc_garch_cov,
    ewma_cov,
    garch11_vol,
    nearest_psd,
)
from arc.risk.var_es import (
    cornish_fisher_var,
    historical_es,
    historical_var,
    parametric_es,
    parametric_var,
    portfolio_var,
    pretrade_var_gate,
)

__all__ = [
    "historical_var", "historical_es", "parametric_var", "parametric_es",
    "cornish_fisher_var", "portfolio_var", "pretrade_var_gate",
    "ewma_cov", "garch11_vol", "dcc_correlation", "dcc_garch_cov", "nearest_psd",
]
