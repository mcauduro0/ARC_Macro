"""Phase 7 — autonomy spine: a persistent, honest paper loop for the one verified edge.

The single highest-value Phase 7 deliverable is the paper loop for ``front/mom3`` (the one signal that
survived the gate): the bridge from "validated edge" to a system that OPERATES, PERSISTS state across
restarts, ACCUMULATES the reserved single-use holdout (forward out-of-time months), and FEEDS BACK
(drift / circuit breaker / promotion verdict) — with a human approving promotions.

Design discipline (from an adversarial governance + look-ahead audit): the scored holdout stream is the
UNBREAKERED frozen stream; consumption + deflation basis are DURABLE ledger facts (not in-memory flags);
positions are written once and never recomputed; the verdict is one-shot, pre-scheduled, NaN-fatal, and
deterministic-on-read. See ``docs/PHASE7_AUTONOMY_SPINE_2026-06.md``.
"""

from arc.autonomy.copilot import OperatorProposal, copilot_status, decide, propose
from arc.autonomy.governance import book_trial, issue_token
from arc.autonomy.ledger import (
    DataRevisionError,
    Decision,
    DeflationBasis,
    HoldoutConsumedError,
    HoldoutNotReadyError,
    LedgerIntegrityError,
    LookAheadError,
    MissingDeflationBasisError,
    OperatorDecision,
    PaperLedger,
    Realization,
    RepaintError,
    UnbookedTrialError,
)
from arc.autonomy.loop import Proposal, run_loop
from arc.autonomy.monitor import (
    CircuitState,
    MonitorConfig,
    circuit_breaker,
    detect_drift,
    promotion_verdict,
    signal_psi,
)
from arc.autonomy.paper import forward_telemetry, reconcile, reconcile_operator, tick
from arc.autonomy.pool import (
    book_pool,
    issue_pool_token,
    pooled_forward_returns,
    pooled_verdict,
)
from arc.autonomy.signals import build_signal
from arc.autonomy.spec import (
    FROZEN_HASH,
    FROZEN_SPEC,
    HARD_PB_SPEC,
    NOWCAST_SPEC,
    POOL_HASH,
    POOL_SPEC,
    SPECS,
    strategy_hash,
)

__all__ = [
    "FROZEN_SPEC", "FROZEN_HASH", "NOWCAST_SPEC", "HARD_PB_SPEC", "POOL_SPEC", "POOL_HASH",
    "SPECS", "strategy_hash",
    "pooled_forward_returns", "book_pool", "issue_pool_token", "pooled_verdict",
    "PaperLedger", "Decision", "Realization", "OperatorDecision", "DeflationBasis",
    "RepaintError", "LedgerIntegrityError", "DataRevisionError", "HoldoutConsumedError",
    "MissingDeflationBasisError", "UnbookedTrialError", "LookAheadError", "HoldoutNotReadyError",
    "tick", "reconcile", "reconcile_operator", "forward_telemetry",
    "MonitorConfig", "CircuitState", "circuit_breaker", "detect_drift", "signal_psi", "promotion_verdict",
    "run_loop", "Proposal",
    "propose", "decide", "copilot_status", "OperatorProposal",
    "book_trial", "issue_token",
    "build_signal",
]
