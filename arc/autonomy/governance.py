"""Human-issued booking: the pre-commitment that must exist BEFORE a forward window can accrue (Phase 7).

A forward holdout is honest only if the deflation bar is fixed before the data exists. ``book_trial``
is the human action that (1) records the strategy as a counted trial (so retuning the spec raises the
deflation bar, not free) and (2) freezes the immutable ``DeflationBasis`` — the exact ``(n_trials,
sr_std)`` the original gate used, the pre-committed evaluation sample size ``eval_at_n``, and the
pre-committed promotion bar ``dsr_min``. Until a hash is booked, ``paper.tick`` refuses to run.

``issue_token`` mints the single-use ``HoldoutToken`` capability bound to the frozen hash. The DURABLE
single-use lock is the ledger (a re-issued token for an already-consumed hash still fails); the token is
only the human's capability to *attempt* one consumption.
"""

from __future__ import annotations

from typing import Optional

from arc.autonomy.ledger import DeflationBasis, PaperLedger, RepaintError, TrialBooking
from arc.autonomy.spec import FROZEN_SPEC, strategy_hash
from arc.eval.governance import HoldoutToken


def book_trial(
    ledger: PaperLedger,
    *,
    spec: dict = FROZEN_SPEC,
    n_trials: int,
    sr_std: Optional[float] = None,
    eval_at_n: int,
    dsr_min: float,
    forward_start: Optional[str] = None,
    issued_by: str,
    min_forward_n: int = 24,
) -> str:
    """Book the trial + freeze the deflation basis for ``spec``. Returns the strategy hash.

    ``n_trials`` MUST be the real multiple-testing count the gate used to deflate this strategy (45
    hypotheses for front/mom3) so the forward DSR is measured against the identical bar — not a fresh,
    weak one. ``sr_std=None`` uses the Lo-2002 auto null SE — the SAME default ``sleeve_stats`` used to
    screen the sleeve in-sample, so the forward methodology matches. ``eval_at_n`` is when the one-shot
    verdict fires; ``dsr_min`` is the bar — both committed here, before any forward data is seen."""
    if eval_at_n < min_forward_n:
        raise ValueError(f"eval_at_n={eval_at_n} below min_forward_n={min_forward_n}: too few months to judge")
    if n_trials < 1:
        raise ValueError("n_trials must reflect the real multiple-testing count (>=1)")
    h = strategy_hash(spec)
    now = ""  # Date.now is forbidden in this codebase's deterministic contexts; caller stamps if needed
    ledger.append_booking(TrialBooking(strategy_hash=h, label=str(spec), issued_by=issued_by, created_at=now))
    try:
        ledger.append_basis(DeflationBasis(
            strategy_hash=h, n_trials=int(n_trials),
            sr_std=(None if sr_std is None else float(sr_std)),
            eval_at_n=int(eval_at_n), dsr_min=float(dsr_min),
            forward_start=(None if forward_start is None else str(forward_start)),
            issued_by=issued_by, created_at=now))
    except RepaintError:
        pass  # basis already frozen — immutable, keep the original (idempotent re-book)
    return h


def issue_token(spec: dict = FROZEN_SPEC, *, issued_by: str) -> HoldoutToken:
    """Mint the single-use capability bound to the frozen hash. The ledger is the durable lock."""
    return HoldoutToken(strategy_hash=strategy_hash(spec), issued_by=issued_by)


__all__ = ["book_trial", "issue_token"]
