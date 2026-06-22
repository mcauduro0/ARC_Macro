"""CI-native tests for arc.autonomy.forward_experiments (no engine, no network, no ledger writes).

These assert the PRE-REGISTRATION contract — NOT a result:
  (1) the registry is well-formed (required keys; the pre-registered nowcast_confvol entry present);
  (2) apply_sizing on a synthetic frozen frame is CAUSAL (as-of invariant), DETERMINISTIC, and BOUNDED
      (|sized position| in [CONF_LO, CONF_HI] * |held|, so |sized return| <= CONF_HI * |held*realized|);
  (3) the 0-row / empty-frame path returns an empty Series and does NOT crash (the honest "not ready"
      shape), and an unknown sizing name raises;
  (4) the pre-committed criterion helper is NaN-fatal and implements 'sized DSR >= flat DSR + margin AND
      sized Sharpe > flat Sharpe'.

Nothing here judges the hypothesis in-sample; these are mechanics/causality/shape tests only.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from arc.autonomy.forward_experiments import (
    CONF_HI,
    CONF_LO,
    DSR_MARGIN,
    FORWARD_EXPERIMENTS,
    apply_sizing,
    criterion_met,
    flat_returns,
    get_experiment,
)


def _idx(n: int) -> pd.DatetimeIndex:
    return pd.date_range("2024-01-31", periods=n, freq="ME")


def _synthetic_frozen_frame(n: int = 60, *, seed: int = 0, future_shock: bool = False) -> pd.DataFrame:
    """A frozen-ledger-shaped frame: held_position, realized_return, sleeve_return, signal_z."""
    rng = np.random.default_rng(seed)
    held = pd.Series(np.clip(rng.standard_normal(n), -1.0, 1.0), index=_idx(n))
    realized = pd.Series(rng.standard_normal(n) * 0.03, index=_idx(n))
    if future_shock:  # extreme outliers in the LAST third so full-sample stats differ from prefix stats
        k = n // 3
        realized.iloc[-k:] += rng.standard_normal(k) * 0.20
    cost = held.diff().abs().fillna(0.0) * (2.0 / 10000.0)
    sleeve = held * realized - cost
    return pd.DataFrame(
        {"held_position": held, "realized_return": realized, "sleeve_return": sleeve,
         "signal_z": rng.standard_normal(n)},
        index=_idx(n),
    )


# --------------------------------------------------------------------------------------- (1) registry
def test_registry_is_well_formed():
    assert isinstance(FORWARD_EXPERIMENTS, list) and len(FORWARD_EXPERIMENTS) >= 1
    required = {"name", "base_strategy", "state_key", "sizing", "alpha", "criterion",
               "in_sample_motivation", "prereg_note"}
    names = set()
    for exp in FORWARD_EXPERIMENTS:
        assert required <= set(exp), f"missing keys: {required - set(exp)}"
        assert exp["sizing"] == "confidence_vol"
        assert 0.0 < float(exp["alpha"]) < 1.0
        assert isinstance(exp["criterion"], str) and exp["criterion"]
        assert exp["name"] not in names, "duplicate experiment name"
        names.add(exp["name"])


def test_nowcast_confvol_is_pre_registered():
    exp = get_experiment("nowcast_confvol")
    assert exp["base_strategy"] == "nowcast_long"
    assert exp["state_key"] == "nowcast"
    assert exp["sizing"] == "confidence_vol"
    assert exp["alpha"] == 0.10
    # the pre-committed criterion text must encode both the DSR margin and the Sharpe leg
    crit = exp["criterion"].lower()
    assert "dsr" in crit and "0.05" in crit and "sharpe" in crit


def test_get_experiment_unknown_raises():
    with pytest.raises(KeyError):
        get_experiment("does_not_exist")


# --------------------------------------------------------------------------------------- (2) mechanics
def test_apply_sizing_rejects_unknown_sizing():
    df = _synthetic_frozen_frame(30)
    with pytest.raises(ValueError):
        apply_sizing(df, "not_a_real_sizing", alpha=0.10)


def test_apply_sizing_is_bounded_relative_to_flat():
    """The sized POSITION is confidence_scaled in [CONF_LO, CONF_HI] * |held|; hence on months past warm-up
    |sized_return| <= CONF_HI * |held*realized| and >= CONF_LO * |held*realized| (sign of held*realized
    preserved since the multiplier is non-negative)."""
    df = _synthetic_frozen_frame(72, seed=1)
    sized = apply_sizing(df, "confidence_vol", alpha=0.10)
    gross = (df["held_position"] * df["realized_return"]).reindex(sized.index)

    # warm-up months fall back to flat sleeve_return; compare only months where the multiplier was active.
    flat_sleeve = df["sleeve_return"].reindex(sized.index)
    active = ~np.isclose(sized.to_numpy(), flat_sleeve.to_numpy(), atol=1e-15)
    g = gross[active]
    s = sized[active]
    eps = 1e-9
    assert (s.abs() <= CONF_HI * g.abs() + eps).all(), "sized return exceeds CONF_HI * gross"
    assert (s.abs() >= CONF_LO * g.abs() - eps).all(), "sized return below CONF_LO * gross"
    # sign preserved relative to the gross position*return term
    nz = g.abs() > eps
    assert (np.sign(s[nz]) == np.sign(g[nz])).all()


def test_apply_sizing_is_deterministic():
    df = _synthetic_frozen_frame(50, seed=2)
    a = apply_sizing(df, "confidence_vol", alpha=0.10)
    b = apply_sizing(df, "confidence_vol", alpha=0.10)
    assert np.allclose(a.to_numpy(), b.to_numpy(), equal_nan=True)


def test_apply_sizing_is_as_of_invariant():
    """Appending later forward months must not change an earlier sized return (strict causality). Inject a
    future shock so full-sample conformal widths/confidence differ sharply from prefix values."""
    df = _synthetic_frozen_frame(90, seed=3, future_shock=True)
    full = apply_sizing(df, "confidence_vol", alpha=0.10)
    for k in (30, 50, 70):
        prefix = apply_sizing(df.iloc[:k], "confidence_vol", alpha=0.10)
        # compare the overlapping months by index (prefix is a strict prefix of the full index)
        common = prefix.index
        assert np.allclose(full.reindex(common).to_numpy(), prefix.to_numpy(), equal_nan=True, atol=1e-12), (
            f"sized return at k={k} changed when later months were appended (leakage)")


def test_apply_sizing_support_matches_flat():
    """Sized stream is defined on exactly the months with a realized return (like-for-like vs flat)."""
    df = _synthetic_frozen_frame(40, seed=4)
    sized = apply_sizing(df, "confidence_vol", alpha=0.10)
    flat = flat_returns(df)
    assert list(sized.dropna().index) == list(flat.dropna().index)
    assert sized.notna().all()  # no NaN holes (warm-up falls back to flat)


def test_apply_sizing_warmup_equals_flat():
    """Before the conformal band / confidence is defined, the multiplier is NaN and the sized return must
    fall back EXACTLY to the recorded flat sleeve return (no silent zeroing)."""
    df = _synthetic_frozen_frame(40, seed=5)
    sized = apply_sizing(df, "confidence_vol", alpha=0.10)
    flat = df["sleeve_return"]
    # the first month certainly has no strictly-past residuals -> warm-up -> equals flat
    assert np.isclose(sized.iloc[0], flat.iloc[0], atol=1e-15)


# --------------------------------------------------------------------------------------- (3) 0-row path
def test_apply_sizing_empty_frame_is_empty_not_ready():
    empty = pd.DataFrame(columns=["held_position", "realized_return", "sleeve_return"])
    sized = apply_sizing(empty, "confidence_vol", alpha=0.10)
    assert isinstance(sized, pd.Series) and len(sized) == 0
    # flat baseline on an empty frame is also empty (the honest "not ready" shape)
    assert len(flat_returns(empty)) == 0


def test_apply_sizing_none_frame_is_empty():
    assert len(apply_sizing(None, "confidence_vol", alpha=0.10)) == 0


# --------------------------------------------------------------------------------------- (4) criterion
def test_criterion_pass_when_sized_beats_flat_on_both_legs():
    flat = {"dsr": 0.40, "sharpe_ann": 0.50}
    sized = {"dsr": 0.40 + DSR_MARGIN + 0.01, "sharpe_ann": 0.60}
    passed, reason = criterion_met(flat, sized)
    assert passed and reason.startswith("PASS")


def test_criterion_fail_when_dsr_margin_not_met():
    flat = {"dsr": 0.40, "sharpe_ann": 0.50}
    sized = {"dsr": 0.40 + DSR_MARGIN - 0.001, "sharpe_ann": 0.99}  # Sharpe better, DSR margin short
    passed, _ = criterion_met(flat, sized)
    assert not passed


def test_criterion_fail_when_sharpe_not_better():
    flat = {"dsr": 0.40, "sharpe_ann": 0.50}
    sized = {"dsr": 1.00, "sharpe_ann": 0.50}  # huge DSR but Sharpe not strictly greater
    passed, _ = criterion_met(flat, sized)
    assert not passed


def test_criterion_is_nan_fatal():
    flat = {"dsr": float("nan"), "sharpe_ann": 0.50}
    sized = {"dsr": 0.90, "sharpe_ann": 0.90}
    passed, reason = criterion_met(flat, sized)
    assert not passed and "degenerate" in reason.lower()
