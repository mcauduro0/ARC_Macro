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
    promotion_report,
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


def test_cpcv_ic_reports_paths():
    rng = np.random.default_rng(5)
    pred = rng.normal(size=120)
    realized = pred + rng.normal(scale=0.5, size=120)
    out = cpcv_ic(pred, realized, n_groups=6, n_test_groups=2)
    assert out["n_paths"] == 15  # C(6,2)
    assert out["mean"] > 0


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
