"""Phase 6 — execution: an order state machine + a deterministic paper-fill simulator.

Pure, CI-tested. Simulates fills (next-price + slippage, liquidity-capped, costed) so the gated book can be
paper-traded end-to-end before any live order. No alpha claim.
"""

from __future__ import annotations

from arc.execution.paper_fill import (
    IllegalTransition,
    Order,
    OrderState,
    PaperFillSimulator,
    realized_vs_paper,
)

__all__ = [
    "OrderState", "Order", "IllegalTransition", "PaperFillSimulator", "realized_vs_paper",
]
