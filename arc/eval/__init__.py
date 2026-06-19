"""Honest measurement — the trustworthy ruler (Phase 2, ARCHITECTURE_SOTA.md §4.2).

Modules:
  - labels     : forward-return + triple-barrier labels (fixes the contemporaneous-target bug)
  - cv         : PurgedKFold + embargo, combinatorial purged CV (leakage-free resampling)
  - metrics    : Probabilistic / Deflated Sharpe, PBO, Newey-West t-stats, IC
  - governance : trial ledger (multiple-testing accounting) + single-use holdout token

The point: a signal does not enter production on an in-sample Sharpe. It must survive
purged/embargoed CV, deflation against the number of trials, and a PBO check — and the
holdout is touched once, under a human-gated token.
"""

from arc.eval.labels import forward_returns, triple_barrier_labels
from arc.eval.cv import PurgedKFold, combinatorial_purged_splits
from arc.eval.metrics import (
    deflated_sharpe_ratio,
    expected_max_sharpe,
    information_coefficient,
    newey_west_tstat,
    probabilistic_sharpe_ratio,
    probability_of_backtest_overfitting,
)
from arc.eval.governance import GovernanceLedger, HoldoutToken, HoldoutConsumedError

__all__ = [
    "forward_returns", "triple_barrier_labels",
    "PurgedKFold", "combinatorial_purged_splits",
    "probabilistic_sharpe_ratio", "deflated_sharpe_ratio", "expected_max_sharpe",
    "probability_of_backtest_overfitting", "newey_west_tstat", "information_coefficient",
    "GovernanceLedger", "HoldoutToken", "HoldoutConsumedError",
]
