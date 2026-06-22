"""ARC Macro 2.0 web API — the bridge from the pure autonomy spine to the UI.

The frontend talks to the SAME ``arc.autonomy`` functions the CLI does: read endpoints serve the durable
JSONL ledger state (fast, always fresh) merged with an engine-heavy proposals/macro snapshot precomputed
by ``scripts/dump_web_state.py``; the write endpoint records a co-pilot operator decision via
``arc.autonomy.copilot.decide`` (ledger-only, fast). Honesty law applies: the API never invents a track
record — pre-verdict it exposes operational state only (counts, positions, drawdown), never a forward
Sharpe/DSR, and surfaces NOT-READY / verdict-refuses verbatim.
"""

from arc.webapi.state import (
    POOL_KEY,
    STATE_KEY,
    build_pool_state,
    build_sleeve_state,
    build_web_state,
)

__all__ = [
    "build_web_state", "build_sleeve_state", "build_pool_state", "STATE_KEY", "POOL_KEY",
]
