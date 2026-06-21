"""The single source of truth for turning a booked spec into its oriented, point-in-time signal.

Every front-end that runs the paper loop — the CLI (``scripts/paper_loop.py``), the multi-edge readiness
harness (``scripts/score_both_edges.py``), the monthly accrual runner, and the Dagster schedule
(``orchestration/dagster/paper_schedule.py``) — MUST build each edge's signal identically, or a scheduled
run would silently trade a different strategy than the one that was gated and booked. This module is that
one implementation; the front-ends import it rather than each keeping a copy (the copies had already drifted
— the Dagster copy did not know about the fiscal edge and would have fed it price momentum instead of the
primary-balance signal). The sleeve applies the causal expanding z-score (``z_window``/``clip_z`` from the
spec), so this returns the RAW oriented signal; ``None`` means "derive price momentum from the returns".
"""

from __future__ import annotations

from typing import Optional

import pandas as pd


def build_signal(spec: dict, monthly: dict) -> Optional[pd.Series]:
    """Return the oriented PIT signal that drives the position for ``spec`` (``None`` => price momentum).

    - ``momentum``        -> ``None`` (the loop computes 3-month price momentum from the return stream).
    - ``fiscal_momentum`` -> ``primary_balance.diff(lookback)`` (oriented positive: improving primary
      balance tightens the sovereign spread, so the receiver gains).
    - ``nowcast``         -> the negated change/level/surprise of the strictly-PIT activity factor.

    Raises ``KeyError`` for a missing required input and ``ValueError`` for an unknown kind/signal — fail
    loud rather than silently fall back to a different strategy."""
    kind = spec.get("kind")
    if kind == "momentum":
        return None
    if kind == "fiscal_momentum":
        pb = monthly.get("primary_balance")
        if pb is None:
            raise KeyError("'primary_balance' not in monthly — cannot build the fiscal signal")
        return pb.diff(int(spec.get("lookback", 6)))
    if kind == "nowcast":
        from arc.features.nowcast import activity_nowcast, nowcast_surprise
        factor = activity_nowcast(monthly, spec["inputs"], ref_col="ibc_br")
        name = spec["signal"]
        if name == "neg_nowcast":
            return -factor
        if name == "neg_nowcast_mom3":
            return -factor.diff(3)
        if name == "neg_nowcast_surprise":
            return -nowcast_surprise(factor)
        raise ValueError(f"unknown nowcast signal '{name}'")
    raise ValueError(f"unknown spec kind '{kind}'")


__all__ = ["build_signal"]
