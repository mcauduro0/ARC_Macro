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
from arc.autonomy.paper import forward_telemetry, reconcile, tick
from arc.autonomy.spec import FROZEN_HASH, FROZEN_SPEC, strategy_hash

__all__ = [
    "FROZEN_SPEC", "FROZEN_HASH", "strategy_hash",
    "PaperLedger", "Decision", "Realization", "DeflationBasis",
    "RepaintError", "LedgerIntegrityError", "DataRevisionError", "HoldoutConsumedError",
    "MissingDeflationBasisError", "UnbookedTrialError", "LookAheadError", "HoldoutNotReadyError",
    "tick", "reconcile", "forward_telemetry",
    "MonitorConfig", "CircuitState", "circuit_breaker", "detect_drift", "signal_psi", "promotion_verdict",
    "run_loop", "Proposal",
    "book_trial", "issue_token",
]
