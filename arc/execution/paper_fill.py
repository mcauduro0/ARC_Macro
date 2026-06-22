"""Phase 6 — order finite-state-machine + a deterministic, causal paper-fill simulator.

This module turns a sequence of TARGET positions into simulated *fills* under an explicit
cost / slippage / liquidity model, so a gated candidate book can be paper-traded end-to-end
before any live order is sent. It makes NO alpha claim: it measures the friction drag between a
frictionless (instant, costless, infinitely liquid) book and a realistically-filled one.

Design contract
---------------
* PURE & DETERMINISTIC: no ``datetime.now``, no global RNG, no network. Same inputs -> byte-identical
  output. Any stochasticity must be supplied by the caller as an explicit, seeded series.
* CAUSAL: period ``t`` uses only information at index ``<= t``. The desired trade at ``t`` is
  ``target[t] - position_carried_in_from_t-1``; it is filled at ``t``'s execution price (a value
  known at ``t``), capped by ``t``'s liquidity proxy. No future price/liquidity is consulted.
* CONSERVATIVE FRICTION: a buy *pays up* (price * (1 + slippage)), a sell *receives less*
  (price * (1 - slippage)); commission is charged on traded notional. Both are non-negative drags.

Order FSM (``OrderState`` / ``Order``)
-------------------------------------
A minimal, validated lifecycle for a single child order::

    NEW -> WORKING -> {PARTIAL -> {PARTIAL, FILLED, CANCELED}, FILLED, CANCELED}
    NEW -> REJECTED
    WORKING -> REJECTED

Illegal transitions raise ``IllegalTransition``. The simulator emits one ``Order`` per period that
trades, recording how much of the desired trade was filled vs. capped.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional

import numpy as np
import pandas as pd

__all__ = [
    "OrderState",
    "IllegalTransition",
    "Order",
    "PaperFillSimulator",
    "realized_vs_paper",
]


# ======================================================================================
# Order finite state machine
# ======================================================================================
class OrderState(Enum):
    """Lifecycle states of a single (child) order."""

    NEW = "NEW"
    WORKING = "WORKING"
    PARTIAL = "PARTIAL"
    FILLED = "FILLED"
    CANCELED = "CANCELED"
    REJECTED = "REJECTED"


#: Allowed state transitions. A transition (a -> b) is legal iff b in _ALLOWED[a].
_ALLOWED: dict[OrderState, frozenset[OrderState]] = {
    OrderState.NEW: frozenset({OrderState.WORKING, OrderState.REJECTED}),
    OrderState.WORKING: frozenset(
        {OrderState.PARTIAL, OrderState.FILLED, OrderState.CANCELED, OrderState.REJECTED}
    ),
    OrderState.PARTIAL: frozenset(
        {OrderState.PARTIAL, OrderState.FILLED, OrderState.CANCELED}
    ),
    # terminal states
    OrderState.FILLED: frozenset(),
    OrderState.CANCELED: frozenset(),
    OrderState.REJECTED: frozenset(),
}

#: States from which no further transition is possible.
TERMINAL_STATES: frozenset[OrderState] = frozenset(
    {OrderState.FILLED, OrderState.CANCELED, OrderState.REJECTED}
)


class IllegalTransition(ValueError):
    """Raised when an order is asked to make a transition not permitted by the FSM."""


def can_transition(src: OrderState, dst: OrderState) -> bool:
    """True iff moving from state ``src`` to state ``dst`` is permitted by the FSM."""
    return dst in _ALLOWED[src]


@dataclass
class Order:
    """A single order with a validated lifecycle.

    Attributes
    ----------
    id : str
        Caller-supplied identifier (e.g. ``"fx@2010-03-31"``). Used only for logging.
    side : str
        ``"BUY"`` or ``"SELL"`` (the direction of the *desired* trade).
    qty : float
        Total desired (absolute) quantity to trade. Non-negative.
    state : OrderState
        Current FSM state (starts at ``NEW``).
    filled_qty : float
        Cumulative absolute quantity filled so far. ``0 <= filled_qty <= qty``.
    avg_price : float
        Quantity-weighted average fill price (NaN until the first fill).
    """

    id: str
    side: str
    qty: float
    state: OrderState = OrderState.NEW
    filled_qty: float = 0.0
    avg_price: float = float("nan")

    def __post_init__(self) -> None:
        if self.side not in ("BUY", "SELL"):
            raise ValueError(f"side must be 'BUY' or 'SELL', got {self.side!r}")
        if not np.isfinite(self.qty) or self.qty < 0:
            raise ValueError(f"qty must be finite and >= 0, got {self.qty}")

    # ---- FSM mechanics -------------------------------------------------------------
    def transition(self, dst: OrderState) -> "Order":
        """Move to ``dst``, validating the transition. Returns ``self`` for chaining.

        Raises ``IllegalTransition`` if the move is not permitted from the current state.
        """
        if not can_transition(self.state, dst):
            raise IllegalTransition(
                f"illegal transition {self.state.value} -> {dst.value} for order {self.id!r}"
            )
        self.state = dst
        return self

    def apply_fill(self, fill_qty: float, fill_price: float) -> "Order":
        """Apply a (partial) fill of ``fill_qty`` at ``fill_price`` and update the FSM.

        Accumulates ``filled_qty`` and the quantity-weighted ``avg_price``, then transitions:
        a fill that completes ``qty`` -> ``FILLED``; otherwise -> ``PARTIAL``. A zero-quantity
        fill is a no-op (no state change). The order must be in ``WORKING`` or ``PARTIAL``.

        Raises ``ValueError`` on a negative fill or an over-fill (``filled_qty`` would exceed ``qty``).
        """
        if fill_qty < 0 or not np.isfinite(fill_qty):
            raise ValueError(f"fill_qty must be finite and >= 0, got {fill_qty}")
        if fill_qty == 0.0:
            return self  # nothing to apply (e.g. liquidity proxy was zero this period)
        new_filled = self.filled_qty + fill_qty
        # guard against floating over-fill beyond a tiny tolerance
        if new_filled > self.qty + 1e-9 * max(1.0, self.qty):
            raise ValueError(
                f"over-fill on order {self.id!r}: filled {new_filled} > qty {self.qty}"
            )
        new_filled = min(new_filled, self.qty)
        if self.filled_qty <= 0.0 or not np.isfinite(self.avg_price):
            self.avg_price = fill_price
        else:
            self.avg_price = (
                self.avg_price * self.filled_qty + fill_price * fill_qty
            ) / new_filled
        self.filled_qty = new_filled
        # advance FSM: fully done -> FILLED, else -> PARTIAL
        if abs(self.filled_qty - self.qty) <= 1e-9 * max(1.0, self.qty):
            self.transition(OrderState.FILLED)
        else:
            self.transition(OrderState.PARTIAL)
        return self

    def remaining(self) -> float:
        """Absolute quantity still to be filled (``qty - filled_qty``, floored at 0)."""
        return max(0.0, self.qty - self.filled_qty)

    def is_terminal(self) -> bool:
        return self.state in TERMINAL_STATES


# ======================================================================================
# Paper-fill simulator
# ======================================================================================
@dataclass
class PaperFillSimulator:
    """Deterministic, causal simulator turning TARGET positions into liquidity-capped fills.

    Per period ``t`` (in index order), starting from the position carried in from ``t-1``:

      1. desired trade ``d = target[t] - position[t-1]`` (signed; sign => BUY/SELL).
      2. liquidity cap: ``cap = max_participation * liquidity[t]`` (absolute units). If ``cap`` is
         smaller than ``|d|`` only ``cap`` trades this period (a PARTIAL fill); the unfilled
         remainder is simply re-attempted next period because next period's desired trade is
         recomputed from the *new* (advanced) position vs the (possibly still-standing) target.
      3. execution price: ``price[t]`` adjusted by ``slippage_bps`` against the trader — a BUY
         fills at ``price*(1 + slip)``, a SELL at ``price*(1 - slip)``.
      4. costs: ``commission = cost_bps * |traded| * price`` (on raw mid notional), and
         ``slippage_cost = |traded| * price * slip`` (the slippage drag in cash).
      5. advance: ``position[t] = position[t-1] + traded`` (signed).

    All friction parameters are constants (a simple, transparent model). ``liquidity`` defaults to
    ``+inf`` (no cap) when not supplied. Output is a tidy per-period DataFrame plus an order log.

    Parameters
    ----------
    slippage_bps : float
        Half-spread / market-impact slippage in basis points, charged against the trader. >= 0.
    cost_bps : float
        Commission in basis points of traded mid notional. >= 0.
    max_participation : float
        Fraction of the per-period ``liquidity`` proxy that may be traded in one period, in (0, 1].
    """

    slippage_bps: float = 0.0
    cost_bps: float = 0.0
    max_participation: float = 1.0

    def __post_init__(self) -> None:
        if self.slippage_bps < 0:
            raise ValueError(f"slippage_bps must be >= 0, got {self.slippage_bps}")
        if self.cost_bps < 0:
            raise ValueError(f"cost_bps must be >= 0, got {self.cost_bps}")
        if not (0.0 < self.max_participation <= 1.0):
            raise ValueError(
                f"max_participation must be in (0, 1], got {self.max_participation}"
            )

    # ----------------------------------------------------------------------------------
    def simulate(
        self,
        targets: pd.Series,
        prices: pd.Series,
        *,
        liquidity: Optional[pd.Series] = None,
        initial_position: float = 0.0,
        instrument: str = "inst",
    ) -> tuple[pd.DataFrame, list[Order]]:
        """Simulate fills for a target-position path against a price series.

        Parameters
        ----------
        targets : pd.Series
            Desired position at the *close* of each period (the position we want to be holding).
        prices : pd.Series
            Per-period execution (mid) price. Must be strictly positive on traded periods.
        liquidity : pd.Series, optional
            Per-period liquidity proxy (e.g. ADV) in position units. Defaults to ``+inf`` (no cap).
            ``cap[t] = max_participation * liquidity[t]``.
        initial_position : float
            Position carried in before the first period (default 0).
        instrument : str
            Label used to build order ids.

        Returns
        -------
        (frame, orders) : (pd.DataFrame, list[Order])
            ``frame`` columns: ``target, desired, traded, filled, fill_price, slippage_cost,
            commission, position``. ``orders`` is one ``Order`` per period that traded.
        """
        targets = pd.Series(targets, dtype="float64")
        prices = prices.reindex(targets.index).astype("float64")
        if liquidity is None:
            liq = pd.Series(np.inf, index=targets.index, dtype="float64")
        else:
            liq = liquidity.reindex(targets.index).astype("float64")

        slip = self.slippage_bps * 1e-4
        comm = self.cost_bps * 1e-4

        rows: list[dict] = []
        orders: list[Order] = []
        pos = float(initial_position)

        for ts in targets.index:
            tgt = targets.loc[ts]
            px = prices.loc[ts]
            cap_liq = liq.loc[ts]

            traded = 0.0
            filled_abs = 0.0
            fill_price = float("nan")
            slip_cost = 0.0
            commission = 0.0
            order: Optional[Order] = None

            # desired signed trade from the CARRIED-IN position (causal: uses pos from <= t-1
            # and target/price/liquidity at t only)
            if pd.isna(tgt) or pd.isna(px):
                # cannot act this period; hold position, emit a NaN-trade row
                desired = float("nan")
            else:
                desired = tgt - pos
                if abs(desired) > 0.0:
                    if not (px > 0):
                        raise ValueError(
                            f"price at {ts!r} must be > 0 to trade, got {px}"
                        )
                    side = "BUY" if desired > 0 else "SELL"
                    want_abs = abs(desired)
                    # liquidity cap (NaN liquidity => no trade this period)
                    if pd.isna(cap_liq):
                        cap_abs = 0.0
                    else:
                        cap_abs = max(0.0, self.max_participation * cap_liq)
                    filled_abs = min(want_abs, cap_abs)

                    order = Order(id=f"{instrument}@{ts}", side=side, qty=want_abs)
                    order.transition(OrderState.WORKING)
                    if filled_abs > 0.0:
                        signed = filled_abs if side == "BUY" else -filled_abs
                        traded = signed
                        # execution price moves against the trader
                        fill_price = px * (1.0 + slip) if side == "BUY" else px * (1.0 - slip)
                        order.apply_fill(filled_abs, fill_price)
                        # cash drags (always non-negative)
                        slip_cost = filled_abs * px * slip
                        commission = filled_abs * px * comm
                    # if nothing filled the order remains WORKING (capped to zero this period)
                    orders.append(order)
                    pos = pos + traded

            rows.append(
                {
                    "target": tgt,
                    "desired": desired,
                    "traded": traded,
                    "filled": filled_abs,
                    "fill_price": fill_price,
                    "slippage_cost": slip_cost,
                    "commission": commission,
                    "position": pos,
                }
            )

        frame = pd.DataFrame(rows, index=targets.index)
        frame = frame[
            [
                "target",
                "desired",
                "traded",
                "filled",
                "fill_price",
                "slippage_cost",
                "commission",
                "position",
            ]
        ]
        return frame, orders


# ======================================================================================
# Friction diagnostics
# ======================================================================================
def realized_vs_paper(
    positions: pd.Series,
    returns: pd.Series,
    fills: pd.DataFrame,
) -> pd.DataFrame:
    """Compare a frictionless book vs. the paper-filled book period by period.

    The frictionless ("paper" intent) PnL applies the *frictionless target* position to the
    period return; the realized (filled) PnL applies the *actually-held* filled position and then
    subtracts the slippage + commission cash drag from the ``fills`` frame.

    Causality note: this uses ``position[t-1] * return[t]`` (the position held coming INTO period
    ``t`` earns ``t``'s return), so no future information is used. Both books are lagged identically,
    so the difference isolates *friction*, not timing.

    Parameters
    ----------
    positions : pd.Series
        The frictionless target position path (what we would hold with no friction/liquidity limit).
    returns : pd.Series
        Per-period asset returns (same units/frequency as the position path).
    fills : pd.DataFrame
        Output of :meth:`PaperFillSimulator.simulate` (needs ``position``, ``slippage_cost``,
        ``commission``).

    Returns
    -------
    pd.DataFrame
        Columns: ``frictionless_pnl, filled_pnl, cost, drag`` where
        ``drag = frictionless_pnl - filled_pnl`` (>= 0 when friction hurts). Indexed like the inputs.
    """
    idx = positions.index
    returns = returns.reindex(idx).astype("float64")
    filled_pos = fills["position"].reindex(idx).astype("float64")
    cost = (fills["slippage_cost"] + fills["commission"]).reindex(idx).fillna(0.0)

    # position held INTO period t is the prior period's close position -> shift(1)
    fr_lag = positions.shift(1)
    fl_lag = filled_pos.shift(1)

    frictionless_pnl = (fr_lag * returns).fillna(0.0)
    filled_gross = (fl_lag * returns).fillna(0.0)
    filled_pnl = filled_gross - cost
    drag = frictionless_pnl - filled_pnl

    return pd.DataFrame(
        {
            "frictionless_pnl": frictionless_pnl,
            "filled_pnl": filled_pnl,
            "cost": cost,
            "drag": drag,
        },
        index=idx,
    )
