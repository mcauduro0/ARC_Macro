"""CI-native tests for arc.execution.paper_fill (no engine, no network).

Asserts the order-FSM + paper-fill contract:
  (FSM)  legal transitions advance; illegal transitions raise; apply_fill drives PARTIAL/FILLED;
         over-fill / bad side / bad qty raise.
  (FILL) a target within liquidity FILLS fully in one period;
         a target beyond liquidity PARTIAL-fills and CONVERGES over periods;
         slippage makes buys pay more / sells receive less (positive cash drag);
         zero-cost zero-slippage reproduces frictionless target tracking EXACTLY;
         deterministic: same inputs -> identical output (and causal: a prefix matches the full run).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from arc.execution.paper_fill import (
    IllegalTransition,
    Order,
    OrderState,
    PaperFillSimulator,
    can_transition,
    realized_vs_paper,
)


def _idx(n: int) -> pd.DatetimeIndex:
    return pd.date_range("2010-01-31", periods=n, freq="ME")


# ======================================================================================
# (FSM) order state machine
# ======================================================================================
def test_legal_transitions_advance():
    o = Order(id="x", side="BUY", qty=10.0)
    assert o.state is OrderState.NEW
    o.transition(OrderState.WORKING)
    assert o.state is OrderState.WORKING
    o.transition(OrderState.PARTIAL)
    assert o.state is OrderState.PARTIAL
    o.transition(OrderState.FILLED)
    assert o.state is OrderState.FILLED


def test_new_can_be_rejected_and_working_canceled():
    a = Order(id="a", side="SELL", qty=1.0).transition(OrderState.REJECTED)
    assert a.state is OrderState.REJECTED
    b = Order(id="b", side="BUY", qty=1.0)
    b.transition(OrderState.WORKING).transition(OrderState.CANCELED)
    assert b.state is OrderState.CANCELED


@pytest.mark.parametrize(
    "src,dst",
    [
        (OrderState.NEW, OrderState.FILLED),     # cannot fill before working
        (OrderState.NEW, OrderState.PARTIAL),    # cannot partial before working
        (OrderState.FILLED, OrderState.WORKING),  # terminal
        (OrderState.CANCELED, OrderState.PARTIAL),  # terminal
        (OrderState.REJECTED, OrderState.WORKING),  # terminal
        (OrderState.PARTIAL, OrderState.WORKING),   # cannot go back to working
        (OrderState.PARTIAL, OrderState.REJECTED),  # reject only from NEW/WORKING
    ],
)
def test_illegal_transitions_raise(src, dst):
    assert not can_transition(src, dst)
    o = Order(id="z", side="BUY", qty=1.0)
    o.state = src  # force into the source state for the unit check
    with pytest.raises(IllegalTransition):
        o.transition(dst)


def test_apply_fill_partial_then_full():
    o = Order(id="p", side="BUY", qty=10.0).transition(OrderState.WORKING)
    o.apply_fill(4.0, 100.0)
    assert o.state is OrderState.PARTIAL
    assert o.filled_qty == pytest.approx(4.0)
    assert o.avg_price == pytest.approx(100.0)
    assert o.remaining() == pytest.approx(6.0)
    # second fill at a different price -> qty-weighted avg, completes -> FILLED
    o.apply_fill(6.0, 110.0)
    assert o.state is OrderState.FILLED
    assert o.filled_qty == pytest.approx(10.0)
    assert o.avg_price == pytest.approx((4 * 100 + 6 * 110) / 10.0)
    assert o.remaining() == pytest.approx(0.0)


def test_apply_fill_rejects_overfill_and_bad_qty():
    o = Order(id="of", side="BUY", qty=5.0).transition(OrderState.WORKING)
    with pytest.raises(ValueError):
        o.apply_fill(6.0, 100.0)  # over-fill
    with pytest.raises(ValueError):
        o.apply_fill(-1.0, 100.0)  # negative
    # zero-qty fill is a benign no-op
    state_before = o.state
    o.apply_fill(0.0, 100.0)
    assert o.state is state_before and o.filled_qty == 0.0


def test_order_construction_validates():
    with pytest.raises(ValueError):
        Order(id="bad", side="LONG", qty=1.0)
    with pytest.raises(ValueError):
        Order(id="bad", side="BUY", qty=-1.0)


# ======================================================================================
# (FILL) within-liquidity target fills fully
# ======================================================================================
def test_target_within_liquidity_fills_fully_in_one_period():
    n = 3
    targets = pd.Series([100.0, 100.0, 100.0], index=_idx(n))
    prices = pd.Series([10.0, 10.0, 10.0], index=_idx(n))
    liq = pd.Series([1000.0] * n, index=_idx(n))  # cap 100% * 1000 = 1000 >> 100
    sim = PaperFillSimulator(slippage_bps=0.0, cost_bps=0.0, max_participation=1.0)
    frame, orders = sim.simulate(targets, prices, liquidity=liq)
    # first period trades the full 100, then nothing more
    assert frame["traded"].iloc[0] == pytest.approx(100.0)
    assert frame["position"].iloc[0] == pytest.approx(100.0)
    assert frame["traded"].iloc[1:].abs().sum() == pytest.approx(0.0)
    assert orders[0].state is OrderState.FILLED


# ======================================================================================
# (FILL) beyond-liquidity target partial-fills and converges
# ======================================================================================
def test_target_beyond_liquidity_partial_fills_and_converges():
    n = 10
    targets = pd.Series([100.0] * n, index=_idx(n))
    prices = pd.Series([10.0] * n, index=_idx(n))
    # cap = 0.5 * 60 = 30 per period -> needs ceil(100/30)=4 periods to converge
    liq = pd.Series([60.0] * n, index=_idx(n))
    sim = PaperFillSimulator(slippage_bps=0.0, cost_bps=0.0, max_participation=0.5)
    frame, orders = sim.simulate(targets, prices, liquidity=liq)
    # first three periods are capped at 30; fourth fills the residual 10
    assert frame["traded"].iloc[0] == pytest.approx(30.0)
    assert frame["traded"].iloc[1] == pytest.approx(30.0)
    assert frame["traded"].iloc[2] == pytest.approx(30.0)
    assert frame["traded"].iloc[3] == pytest.approx(10.0)
    # converged to target and stays
    assert frame["position"].iloc[3] == pytest.approx(100.0)
    assert np.allclose(frame["position"].iloc[3:].to_numpy(), 100.0, atol=1e-9)
    # the capped periods produced PARTIAL/WORKING orders, the converging one FILLED
    assert orders[0].state is OrderState.PARTIAL
    assert orders[3].state is OrderState.FILLED


def test_capped_period_order_stays_working_when_zero_liquidity():
    n = 2
    targets = pd.Series([50.0, 50.0], index=_idx(n))
    prices = pd.Series([10.0, 10.0], index=_idx(n))
    liq = pd.Series([0.0, 100.0], index=_idx(n))  # no liquidity period 0
    sim = PaperFillSimulator(max_participation=1.0)
    frame, orders = sim.simulate(targets, prices, liquidity=liq)
    assert frame["traded"].iloc[0] == pytest.approx(0.0)
    assert orders[0].state is OrderState.WORKING  # nothing filled -> still working
    # next period with liquidity catches up
    assert frame["traded"].iloc[1] == pytest.approx(50.0)
    assert frame["position"].iloc[1] == pytest.approx(50.0)


# ======================================================================================
# (FILL) slippage: buys pay more, sells receive less; drag > 0
# ======================================================================================
def test_slippage_buy_pays_more_sell_receives_less():
    n = 2
    # period 0: buy from 0 -> +100 ; period 1: sell back to 0 -> -100
    targets = pd.Series([100.0, 0.0], index=_idx(n))
    prices = pd.Series([10.0, 10.0], index=_idx(n))
    sim = PaperFillSimulator(slippage_bps=50.0, cost_bps=0.0, max_participation=1.0)
    frame, _ = sim.simulate(targets, prices)
    slip = 50e-4
    # buy fill price above mid
    assert frame["fill_price"].iloc[0] == pytest.approx(10.0 * (1 + slip))
    # sell fill price below mid
    assert frame["fill_price"].iloc[1] == pytest.approx(10.0 * (1 - slip))
    # slippage cash drag strictly positive on both legs
    assert (frame["slippage_cost"] > 0).all()
    assert frame["slippage_cost"].iloc[0] == pytest.approx(100 * 10.0 * slip)


def test_realized_vs_paper_drag_nonnegative_with_friction():
    n = 6
    rng = np.random.default_rng(0)
    targets = pd.Series(np.r_[np.zeros(1), np.full(n - 1, 100.0)], index=_idx(n))
    prices = pd.Series(np.full(n, 10.0), index=_idx(n))
    returns = pd.Series(rng.standard_normal(n) * 0.01, index=_idx(n))
    sim = PaperFillSimulator(slippage_bps=20.0, cost_bps=5.0, max_participation=1.0)
    frame, _ = sim.simulate(targets, prices)
    cmp = realized_vs_paper(targets, returns, frame)
    # total cash cost is strictly positive (we traded with friction)
    assert cmp["cost"].sum() > 0
    # frictionless == filled gross here (liquidity uncapped, same positions), so total drag == total cost
    assert cmp["drag"].sum() == pytest.approx(cmp["cost"].sum())
    assert cmp["drag"].sum() > 0


# ======================================================================================
# (FILL) zero-cost zero-slippage reproduces frictionless target tracking exactly
# ======================================================================================
def test_zero_friction_tracks_target_exactly():
    n = 24
    rng = np.random.default_rng(7)
    targets = pd.Series(np.cumsum(rng.standard_normal(n)), index=_idx(n))
    prices = pd.Series(np.full(n, 10.0) + rng.random(n), index=_idx(n))  # positive prices
    sim = PaperFillSimulator(slippage_bps=0.0, cost_bps=0.0, max_participation=1.0)
    frame, _ = sim.simulate(targets, prices)  # liquidity = +inf
    # position equals target every period (instant, costless, infinitely liquid)
    assert np.allclose(frame["position"].to_numpy(), targets.to_numpy(), atol=1e-12)
    assert frame["slippage_cost"].abs().sum() == pytest.approx(0.0)
    assert frame["commission"].abs().sum() == pytest.approx(0.0)
    # fill price equals mid exactly on traded periods
    traded = frame["traded"] != 0
    assert np.allclose(
        frame.loc[traded, "fill_price"].to_numpy(),
        prices[traded].to_numpy(),
        atol=1e-12,
    )
    # and the friction comparison shows zero drag
    returns = pd.Series(rng.standard_normal(n) * 0.01, index=_idx(n))
    cmp = realized_vs_paper(targets, returns, frame)
    assert cmp["drag"].abs().sum() == pytest.approx(0.0, abs=1e-12)


# ======================================================================================
# determinism + causality
# ======================================================================================
def test_deterministic_same_inputs_identical_output():
    n = 30
    rng = np.random.default_rng(11)
    targets = pd.Series(np.cumsum(rng.standard_normal(n)) * 5.0, index=_idx(n))
    prices = pd.Series(10.0 + rng.random(n), index=_idx(n))
    liq = pd.Series(rng.random(n) * 20.0 + 1.0, index=_idx(n))
    sim = PaperFillSimulator(slippage_bps=12.0, cost_bps=3.0, max_participation=0.4)
    f1, o1 = sim.simulate(targets, prices, liquidity=liq)
    f2, o2 = sim.simulate(targets, prices, liquidity=liq)
    pd.testing.assert_frame_equal(f1, f2)
    assert [(o.state, o.filled_qty, o.avg_price) for o in o1] == [
        (o.state, o.filled_qty, o.avg_price) for o in o2
    ]


def test_causal_prefix_matches_full_run():
    """Appending future periods must not change earlier per-period outputs (strictly causal)."""
    n = 40
    rng = np.random.default_rng(13)
    targets = pd.Series(np.cumsum(rng.standard_normal(n)) * 3.0, index=_idx(n))
    prices = pd.Series(10.0 + rng.random(n), index=_idx(n))
    liq = pd.Series(rng.random(n) * 15.0 + 1.0, index=_idx(n))
    sim = PaperFillSimulator(slippage_bps=8.0, cost_bps=2.0, max_participation=0.5)
    full, _ = sim.simulate(targets, prices, liquidity=liq)
    k = 25
    prefix, _ = sim.simulate(
        targets.iloc[:k], prices.iloc[:k], liquidity=liq.iloc[:k]
    )
    pd.testing.assert_frame_equal(full.iloc[:k], prefix)


def test_nan_target_or_price_holds_position():
    n = 4
    targets = pd.Series([50.0, np.nan, 50.0, 50.0], index=_idx(n))
    prices = pd.Series([10.0, 10.0, np.nan, 10.0], index=_idx(n))
    sim = PaperFillSimulator(max_participation=1.0)
    frame, _ = sim.simulate(targets, prices)
    # period 0 fills to 50; periods 1 & 2 cannot act -> hold; period 3 already at target
    assert frame["position"].iloc[0] == pytest.approx(50.0)
    assert frame["position"].iloc[1] == pytest.approx(50.0)  # held (NaN target)
    assert frame["position"].iloc[2] == pytest.approx(50.0)  # held (NaN price)
    assert frame["traded"].iloc[1:].abs().sum() == pytest.approx(0.0)
