"""Promotion gate — carry-neutralized IC, carry-only benchmark, DSR/CPCV verdict (arc.eval.gate)."""

from __future__ import annotations

import numpy as np
import pandas as pd

from arc.eval.gate import (
    GateThresholds,
    carry_neutralized_ic,
    carry_only_ic,
    carry_only_portfolio,
    cpcv_ic,
    half_sample_carry_neutral_ic,
    promotion_report,
    refit_oos_cpcv,
    residualize,
    sharpe_stats,
)


def test_residualize_removes_linear_component():
    rng = np.random.default_rng(0)
    x = pd.Series(rng.normal(size=200))
    y = 3.0 + 2.0 * x  # perfectly explained by x
    resid = residualize(y, x)
    assert np.allclose(resid.values, 0.0, atol=1e-8)


def test_carry_neutralized_ic_kills_pure_carry_signal():
    """If the prediction IS carry and the return IS carry, raw IC is high but carry-neutralized IC
    collapses — the gate's whole point."""
    rng = np.random.default_rng(1)
    carry = pd.Series(rng.normal(size=300))
    realized = carry + rng.normal(scale=0.05, size=300)  # return is basically carry
    pred = carry.copy()                                   # signal is just carry in disguise
    raw = carry_only_ic(pred, realized)
    neutral = carry_neutralized_ic(pred, realized, carry)
    assert raw > 0.8
    assert abs(neutral) < 0.2


def test_carry_neutralized_ic_keeps_genuine_signal():
    rng = np.random.default_rng(2)
    carry = pd.Series(rng.normal(size=300))
    alpha = pd.Series(rng.normal(size=300))
    realized = 0.5 * carry + 0.5 * alpha + rng.normal(scale=0.05, size=300)
    pred = alpha.copy()  # orthogonal to carry, genuinely predictive
    neutral = carry_neutralized_ic(pred, realized, carry)
    assert neutral > 0.4


def test_carry_only_portfolio_runs_and_is_finite():
    idx = pd.date_range("2010-01-31", periods=60, freq="ME")
    rng = np.random.default_rng(3)
    carry = pd.DataFrame(rng.normal(size=(60, 3)), index=idx, columns=["a", "b", "c"])
    realized = pd.DataFrame(rng.normal(size=(60, 3)), index=idx, columns=["a", "b", "c"])
    ret = carry_only_portfolio(carry, realized)
    assert len(ret) == 60
    assert np.isfinite(ret.values).all()


def test_sharpe_stats_dsr_deflates_with_more_trials():
    rng = np.random.default_rng(4)
    r = rng.normal(0.01, 0.03, size=120)  # decent monthly Sharpe
    few = sharpe_stats(r, n_trials=1)
    many = sharpe_stats(r, n_trials=1000)
    assert few["dsr"] >= many["dsr"]  # deflation is monotone in trial count


def test_sharpe_stats_auto_sr_std_is_per_period_not_annual():
    """Units guard (regression for the adversarial-review bug): the default sr_std must be the
    per-period Sharpe SE (~sqrt(1/n)), NOT 1.0. With sr_std=1.0 the DSR of a healthy monthly Sharpe
    collapses to ~0 (impossible benchmark); with the auto default it is a sane, non-degenerate value."""
    rng = np.random.default_rng(11)
    r = rng.normal(0.012, 0.03, size=138)  # ~Sharpe 0.8 annualized, like the overlay
    auto = sharpe_stats(r, n_trials=30)              # auto sr_std
    buggy = sharpe_stats(r, n_trials=30, sr_std=1.0)  # the old default
    assert 0.0 < auto["sr_std"] < 0.3                 # per-period scale
    assert auto["dsr"] > 0.2                           # not spuriously zero
    assert buggy["dsr"] < 1e-6                          # the bug: over-deflated to ~0
    assert auto["dsr"] > buggy["dsr"]


def test_cpcv_ic_reports_paths():
    rng = np.random.default_rng(5)
    pred = rng.normal(size=120)
    realized = pred + rng.normal(scale=0.5, size=120)
    out = cpcv_ic(pred, realized, n_groups=6, n_test_groups=2)
    assert out["n_paths"] == 15  # C(6,2)
    assert out["mean"] > 0


def test_refit_oos_cpcv_recovers_signal_and_rejects_noise():
    """True OOS CPCV: a genuine linear feature->forward-return relationship gives positive OOS IC;
    pure-noise features give ~0. Confirms the refit (not just IC-stability) works."""
    rng = np.random.default_rng(21)
    n = 180
    f = rng.normal(size=n)
    y = 0.6 * f + rng.normal(scale=1.0, size=n)          # genuine signal in feature f
    X = np.column_stack([f, rng.normal(size=n)])          # one signal col + one noise col
    sig = refit_oos_cpcv(X, y, n_groups=6, n_test_groups=2)
    assert sig["n_paths"] >= 12                            # ~C(6,2), minus widest-span purged combos
    assert sig["mean"] > 0.2                               # OOS recovers the signal

    Xn = rng.normal(size=(n, 2))                           # all noise
    yn = rng.normal(size=n)
    noise = refit_oos_cpcv(Xn, yn, n_groups=6, n_test_groups=2)
    assert abs(noise["mean"]) < 0.15                       # no OOS edge from noise


def test_refit_oos_cpcv_handles_short_and_nan():
    assert refit_oos_cpcv(np.zeros((5, 2)), np.zeros(5))["n_paths"] == 0  # too short
    rng = np.random.default_rng(22)
    X = rng.normal(size=(120, 2)); y = X[:, 0] + rng.normal(scale=0.5, size=120)
    X[:10, 0] = np.nan  # some NaNs are dropped per-fold, not crash
    out = refit_oos_cpcv(X, y)
    assert out["n_paths"] > 0


def test_half_sample_ic_flags_decay_and_passes_stationary():
    """A signal whose carry-neutral IC is strong early and dead late shows a large H1->H2 drop; a
    stationary signal of the same average strength shows ~0 drop. This is the contamination probe."""
    rng = np.random.default_rng(31)
    n = 160
    carry = pd.Series(rng.normal(size=n))
    # contaminated: predictive only in the first half
    p_decay = pd.Series(rng.normal(size=n))
    r_decay = pd.Series(rng.normal(scale=0.3, size=n))
    r_decay.iloc[: n // 2] += 1.5 * p_decay.iloc[: n // 2]  # strong early link, none late
    hs_d = half_sample_carry_neutral_ic(p_decay, r_decay, carry)
    assert hs_d["h1"] - hs_d["h2"] > 0.3
    assert hs_d["drop"] > 0.3

    # stationary: equally predictive in both halves
    p_stat = pd.Series(rng.normal(size=n))
    r_stat = 0.8 * p_stat + pd.Series(rng.normal(scale=0.6, size=n))
    hs_s = half_sample_carry_neutral_ic(p_stat, r_stat, carry)
    assert abs(hs_s["drop"]) < 0.25


def test_half_sample_ic_short_sample_is_nan():
    out = half_sample_carry_neutral_ic(pd.Series(np.zeros(10)), pd.Series(np.zeros(10)), pd.Series(np.zeros(10)))
    assert np.isnan(out["drop"])
    assert out["n_h1"] == 0


def test_promotion_report_fails_on_ic_decay():
    """Even with a high average carry-neutral IC and a healthy Sharpe, a steep first->second half
    decay must FAIL the gate — this is exactly the false-PASS the audit's leaked overlay produced."""
    idx = pd.date_range("2014-01-31", periods=160, freq="ME")
    rng = np.random.default_rng(32)
    insts = ["front", "belly", "long"]
    carry = pd.DataFrame(rng.normal(size=(160, 3)), index=idx, columns=insts)
    pred = pd.DataFrame(rng.normal(size=(160, 3)), index=idx, columns=insts)
    # realized tracks pred strongly in the first half, weakly in the second (contamination signature)
    realized = pd.DataFrame(rng.normal(scale=0.3, size=(160, 3)), index=idx, columns=insts)
    realized.iloc[:80] += 1.5 * pred.iloc[:80]
    realized.iloc[80:] += 0.1 * pred.iloc[80:]
    overlay = (pred.sub(pred.mean(axis=1), axis=0) * realized).sum(axis=1)
    verdict = promotion_report(
        pred_panel=pred, realized_panel=realized, carry_panel=carry,
        overlay_returns=overlay.values, n_trials=30,
    )
    assert verdict.passed is False
    assert any("decay" in r.lower() for r in verdict.reasons)
    d = verdict.to_dict()
    assert not np.isnan(d["aggregate"]["median_cn_ic_decay"])
    assert "half_sample" in d["per_instrument"]["front"]


def test_promotion_report_fails_pure_carry():
    """A book that is pure carry should FAIL: carry-neutralized IC ~ 0 and overlay can't beat carry."""
    idx = pd.date_range("2008-01-31", periods=150, freq="ME")
    rng = np.random.default_rng(6)
    insts = ["front", "belly", "long"]
    carry = pd.DataFrame(rng.normal(size=(150, 3)), index=idx, columns=insts)
    realized = carry + pd.DataFrame(rng.normal(scale=0.05, size=(150, 3)), index=idx, columns=insts)
    pred = carry.copy()  # signal == carry
    overlay = (pred.sub(pred.mean(axis=1), axis=0) * realized).sum(axis=1)
    verdict = promotion_report(
        pred_panel=pred, realized_panel=realized, carry_panel=carry,
        overlay_returns=overlay.values, n_trials=30,
    )
    assert verdict.passed is False
    assert any("carry" in r.lower() for r in verdict.reasons)


def test_promotion_report_structure():
    idx = pd.date_range("2008-01-31", periods=150, freq="ME")
    rng = np.random.default_rng(7)
    insts = ["front", "belly", "long"]
    carry = pd.DataFrame(rng.normal(size=(150, 3)), index=idx, columns=insts)
    alpha = pd.DataFrame(rng.normal(size=(150, 3)), index=idx, columns=insts)
    realized = 0.5 * carry + 0.5 * alpha + pd.DataFrame(rng.normal(scale=0.05, size=(150, 3)), index=idx, columns=insts)
    verdict = promotion_report(
        pred_panel=alpha, realized_panel=realized, carry_panel=carry,
        overlay_returns=(alpha * realized).sum(axis=1).values, n_trials=30,
    )
    d = verdict.to_dict()
    assert set(["passed", "reasons", "overlay", "carry_only", "aggregate", "per_instrument"]).issubset(d)
    assert set(insts) == set(d["per_instrument"].keys())
    for inst in insts:
        assert "carry_neutral_ic" in d["per_instrument"][inst]
