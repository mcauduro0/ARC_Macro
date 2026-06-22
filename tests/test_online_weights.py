"""CI-native tests for arc.intelligence.online_weights (no engine, no network).

Asserts the causal online-combination-weight contract:
  (1) each defined weight ROW sums to 1 across present columns, and every weight is >= floor (>= 0);
  (2) CAUSAL / as-of-invariant: an interior weight row is unchanged when later rows are appended;
  (3) EWMA performance weights give a column with consistently higher past risk-adjusted return a
      strictly higher weight than a worse column;
  (4) inverse-variance weights give the lower-variance column a strictly higher weight.

These functions only COMBINE already-causal return streams; they assert no alpha. Fixed seeds throughout.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from arc.intelligence.online_weights import (
    ewma_performance_weights,
    rolling_inverse_variance_weights,
)


def _idx(n: int) -> pd.DatetimeIndex:
    return pd.date_range("2010-01-31", periods=n, freq="ME")


def _panel(n: int, seed: int, ncols: int = 3) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    cols = [f"s{i}" for i in range(ncols)]
    data = rng.standard_normal((n, ncols)) * 0.02
    return pd.DataFrame(data, index=_idx(n), columns=cols)


# --------------------------------------------------------------------------------------
# (1) ROWS SUM TO 1 (where defined) AND >= floor
# --------------------------------------------------------------------------------------
@pytest.mark.parametrize("fn,kw", [
    (ewma_performance_weights, {"halflife": 12, "min_periods": 12, "floor": 0.0}),
    (ewma_performance_weights, {"halflife": 6, "min_periods": 12, "floor": 0.1}),
    (rolling_inverse_variance_weights, {"window": 12, "min_periods": 12}),
])
def test_rows_sum_to_one_and_respect_floor(fn, kw):
    panel = _panel(120, seed=0)
    w = fn(panel, **kw)
    assert list(w.columns) == list(panel.columns)
    assert w.index.equals(panel.index)

    floor = kw.get("floor", 0.0)
    # Every emitted (non-NaN) weight is >= floor (>= 0).
    vals = w.to_numpy()
    finite = np.isfinite(vals)
    assert (vals[finite] >= floor - 1e-12).all(), "weight below floor"

    # Every row with ANY defined weight sums to 1 across present columns.
    row_sums = np.nansum(vals, axis=1)
    any_defined = finite.any(axis=1)
    assert np.allclose(row_sums[any_defined], 1.0, atol=1e-9), "defined rows must sum to 1"


def test_floor_is_binding_floor_when_positive():
    """With a positive floor, no emitted weight may fall below it (after normalization)."""
    panel = _panel(120, seed=1, ncols=3)
    floor = 0.2
    w = ewma_performance_weights(panel, halflife=12, min_periods=12, floor=floor)
    vals = w.to_numpy()
    finite = np.isfinite(vals)
    assert (vals[finite] >= floor - 1e-12).all()


def test_insufficient_history_rows_are_equal_weight():
    """Before min_periods (+lag) every defined row is EQUAL across present columns (the fallback)."""
    n, ncols = 60, 3
    panel = _panel(n, seed=2, ncols=ncols)
    w = ewma_performance_weights(panel, halflife=12, min_periods=12, floor=0.0)
    # Row 0 cannot have any strictly-past stat -> equal weights 1/ncols.
    first = w.iloc[0].to_numpy()
    assert np.allclose(first, 1.0 / ncols, atol=1e-12)

    w_iv = rolling_inverse_variance_weights(panel, window=12, min_periods=12)
    first_iv = w_iv.iloc[0].to_numpy()
    assert np.allclose(first_iv, 1.0 / ncols, atol=1e-12)


def test_absent_column_excluded_and_present_still_sum_to_one():
    """A column that is NaN at a row gets NaN weight; the present columns still sum to 1 there."""
    n = 80
    panel = _panel(n, seed=3, ncols=3)
    panel.iloc[40:, 2] = np.nan  # third stream stops existing partway through
    for fn, kw in [
        (ewma_performance_weights, {"halflife": 12, "min_periods": 12, "floor": 0.0}),
        (rolling_inverse_variance_weights, {"window": 12, "min_periods": 12}),
    ]:
        w = fn(panel, **kw)
        tail = w.iloc[60:]
        assert tail["s2"].isna().all(), "absent column must have NaN weight"
        row_sums = tail[["s0", "s1"]].sum(axis=1)
        assert np.allclose(row_sums.to_numpy(), 1.0, atol=1e-9)


# --------------------------------------------------------------------------------------
# (2) CAUSAL — as-of invariance (interior rows unchanged by appending later data)
# --------------------------------------------------------------------------------------
@pytest.mark.parametrize("fn,kw", [
    (ewma_performance_weights, {"halflife": 12, "min_periods": 12, "floor": 0.0}),
    (ewma_performance_weights, {"halflife": 6, "min_periods": 12, "floor": 0.05}),
    (rolling_inverse_variance_weights, {"window": 12, "min_periods": 12}),
])
def test_as_of_invariant_interior_rows(fn, kw):
    n = 120
    panel = _panel(n, seed=4)
    # Inject an extreme future shock in the last third: full-sample stats differ sharply from prefixes,
    # so a non-causal implementation would change earlier rows.
    rng = np.random.default_rng(99)
    panel.iloc[-40:] += rng.standard_normal((40, panel.shape[1])) * 0.5

    full = fn(panel, **kw)
    for k in (30, 60, 90):
        prefix = fn(panel.iloc[:k], **kw)
        assert np.allclose(
            full.iloc[:k].to_numpy(), prefix.to_numpy(), equal_nan=True, atol=1e-9
        ), f"weights at rows < {k} changed when later rows were appended ({fn.__name__})"


def test_weight_row_uses_only_strictly_past_returns():
    """Mutating ONLY the current row's returns must not change that row's weights (strict-past contract)."""
    n = 80
    panel = _panel(n, seed=5)
    t = 50
    for fn, kw in [
        (ewma_performance_weights, {"halflife": 12, "min_periods": 12, "floor": 0.0}),
        (rolling_inverse_variance_weights, {"window": 12, "min_periods": 12}),
    ]:
        base = fn(panel, **kw)
        bumped = panel.copy()
        bumped.iloc[t] = bumped.iloc[t] + 10.0  # change ONLY row t's returns
        after = fn(bumped, **kw)
        assert np.allclose(
            base.iloc[t].to_numpy(), after.iloc[t].to_numpy(), equal_nan=True, atol=1e-12
        ), f"weights at t depend on the current row's own return ({fn.__name__})"


# --------------------------------------------------------------------------------------
# (3) EWMA — a consistently better column earns more weight
# --------------------------------------------------------------------------------------
def test_ewma_rewards_higher_past_risk_adjusted_return():
    """A column with a higher, equally-noisy past mean (=> higher EW Sharpe) gets the larger weight."""
    n = 120
    idx = _idx(n)
    rng = np.random.default_rng(7)
    noise_a = rng.standard_normal(n) * 0.01
    noise_b = rng.standard_normal(n) * 0.01
    good = pd.Series(0.02 + noise_a, index=idx)   # clearly higher mean, same noise scale
    bad = pd.Series(0.00 + noise_b, index=idx)    # zero mean
    panel = pd.DataFrame({"good": good, "bad": bad})

    w = ewma_performance_weights(panel, halflife=12, min_periods=12, floor=0.0)
    tail = w.dropna()
    # Once history exists, the good column should dominate on average and at the final row.
    assert tail["good"].mean() > tail["bad"].mean() + 0.1
    assert w["good"].iloc[-1] > w["bad"].iloc[-1]


def test_ewma_negative_sharpe_column_is_floored_out():
    """A column with a consistently NEGATIVE past mean is floored to 0 (never shorted via weights)."""
    n = 120
    idx = _idx(n)
    rng = np.random.default_rng(8)
    pos = pd.Series(0.02 + rng.standard_normal(n) * 0.005, index=idx)   # positive Sharpe
    neg = pd.Series(-0.02 + rng.standard_normal(n) * 0.005, index=idx)  # negative Sharpe
    panel = pd.DataFrame({"pos": pos, "neg": neg})
    w = ewma_performance_weights(panel, halflife=12, min_periods=12, floor=0.0)
    # Skip the equal-weight fallback warmup (first ~min_periods rows are 0.5/0.5 by design); once the EW
    # scores are defined the negative-Sharpe column floors to 0 and the positive one takes all the weight.
    tail = w.iloc[20:]
    assert np.allclose(tail["neg"].to_numpy(), 0.0, atol=1e-9)
    assert np.allclose(tail["pos"].to_numpy(), 1.0, atol=1e-9)


# --------------------------------------------------------------------------------------
# (4) inverse-variance — lower-variance column gets more weight
# --------------------------------------------------------------------------------------
def test_inverse_variance_favors_lower_variance_column():
    n = 120
    idx = _idx(n)
    rng = np.random.default_rng(10)
    calm = pd.Series(rng.standard_normal(n) * 0.01, index=idx)   # low variance
    wild = pd.Series(rng.standard_normal(n) * 0.05, index=idx)   # ~25x variance
    panel = pd.DataFrame({"calm": calm, "wild": wild})

    w = rolling_inverse_variance_weights(panel, window=12, min_periods=12)
    # Skip the equal-weight fallback warmup (first ~window rows are 0.5/0.5 by design); once trailing
    # variances are defined the calm (lower-variance) stream must carry the majority of weight throughout.
    tail = w.iloc[20:]
    assert (tail["calm"] > tail["wild"]).all()
    assert tail["calm"].mean() > 0.7


def test_inverse_variance_two_equal_columns_split_evenly():
    """Two i.i.d. columns with the same variance get ~equal weight (sanity on the normalization)."""
    n = 200
    idx = _idx(n)
    rng = np.random.default_rng(11)
    a = pd.Series(rng.standard_normal(n) * 0.02, index=idx)
    b = pd.Series(rng.standard_normal(n) * 0.02, index=idx)
    panel = pd.DataFrame({"a": a, "b": b})
    w = rolling_inverse_variance_weights(panel, window=24, min_periods=24).dropna()
    assert abs(w["a"].mean() - 0.5) < 0.06  # close to even on average


# --------------------------------------------------------------------------------------
# input validation
# --------------------------------------------------------------------------------------
def test_rejects_bad_params():
    panel = _panel(30, seed=12)
    with pytest.raises(ValueError):
        ewma_performance_weights(panel, floor=-0.1)
    with pytest.raises(ValueError):
        ewma_performance_weights(panel, halflife=0)
    with pytest.raises(ValueError):
        rolling_inverse_variance_weights(panel, window=0)
