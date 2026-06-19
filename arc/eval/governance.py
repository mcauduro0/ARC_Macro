"""Multiple-testing governance: a global trial ledger + a single-use holdout token.

Every config tried by ANY actor (human or agent) logs a trial here; ``n_trials`` and
``sharpe_std`` feed the Deflated Sharpe Ratio so selection bias is accounted for globally
(without this, the autonomous research loop manufactures false positives — the 0.39->3.92
trail, automated). The locked holdout is touched at most once, via a human-issued token
bound to a frozen strategy hash that an agent cannot self-issue.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

import numpy as np
import pandas as pd


@dataclass
class TrialRecord:
    config_hash: str
    sharpe: Optional[float] = None
    label: str = ""
    metrics: dict[str, Any] = field(default_factory=dict)


class GovernanceLedger:
    """Append-only ledger of every trial. The join point for multiple-testing control."""

    def __init__(self) -> None:
        self._trials: list[TrialRecord] = []
        self._counts: dict[str, int] = {}

    def record_trial(self, config_hash: str, sharpe: Optional[float] = None, label: str = "", **metrics) -> int:
        self._trials.append(TrialRecord(config_hash, sharpe, label, dict(metrics)))
        self._counts[config_hash] = self._counts.get(config_hash, 0) + 1
        return len(self._trials)

    def n_trials(self) -> int:
        return len(self._trials)

    def n_unique_configs(self) -> int:
        return len(self._counts)

    def sharpe_std(self) -> float:
        """Std of trial Sharpes — the ``sr_std`` input to expected_max_sharpe / DSR."""
        srs = [t.sharpe for t in self._trials if t.sharpe is not None and not np.isnan(t.sharpe)]
        return float(np.std(srs, ddof=1)) if len(srs) > 1 else 0.0

    def best(self) -> Optional[TrialRecord]:
        scored = [t for t in self._trials if t.sharpe is not None and not np.isnan(t.sharpe)]
        return max(scored, key=lambda t: t.sharpe) if scored else None

    def to_frame(self) -> pd.DataFrame:
        return pd.DataFrame([{"config_hash": t.config_hash, "sharpe": t.sharpe, "label": t.label, **t.metrics}
                             for t in self._trials])


class HoldoutConsumedError(RuntimeError):
    """Raised when a holdout token is used more than once."""


class HoldoutToken:
    """Single-use token gating the locked holdout, bound to a frozen strategy hash.

    Models the rule that the holdout is an unbiased estimate ONLY if touched once: an agent
    cannot self-issue (a human constructs it), and consuming it with a different strategy
    hash than it was issued for is refused.
    """

    def __init__(self, strategy_hash: str, issued_by: str) -> None:
        if not strategy_hash:
            raise ValueError("holdout token must be bound to a frozen strategy hash")
        self.strategy_hash = strategy_hash
        self.issued_by = issued_by
        self._consumed = False

    @property
    def consumed(self) -> bool:
        return self._consumed

    def consume(self, strategy_hash: str) -> bool:
        if self._consumed:
            raise HoldoutConsumedError("holdout token already used — the holdout is now biased")
        if strategy_hash != self.strategy_hash:
            raise ValueError("strategy hash mismatch — token is bound to a frozen spec")
        self._consumed = True
        return True
