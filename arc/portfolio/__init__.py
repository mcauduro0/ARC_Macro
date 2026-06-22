"""Phase 6 — portfolio construction: Black-Litterman blend of an equilibrium prior with macro views.

Pure, CI-tested linear algebra. A construction tool, not an alpha claim — views must come from gated
signals before any allocation is real.
"""

from __future__ import annotations

from arc.portfolio.black_litterman import (
    bl_optimal_weights,
    black_litterman_posterior,
    default_omega,
    implied_equilibrium_returns,
)

__all__ = [
    "implied_equilibrium_returns", "black_litterman_posterior", "bl_optimal_weights", "default_omega",
]
