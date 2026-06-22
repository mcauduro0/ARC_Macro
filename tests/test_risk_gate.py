"""Live pre-trade VaR/ES risk gate — CI-native tests (pure numpy/pandas/scipy; no engine, no network).

The gate is an OPERATIONAL sizing overlay: it caps leverage to a pre-committed monthly loss budget. The
non-negotiable invariant: wiring it into run_loop changes ONLY the sized exposure — the scored `frozen`
stream is byte-identical with the gate on or off. Plus the gate's own behaviour: inactive below the
history floor, binds & caps on fat tails, monotone in the budget, and the portfolio gate uses the
cross-asset covariance.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from arc.autonomy.governance import book_trial
from arc.autonomy.ledger import PaperLedger
from arc.autonomy.loop import run_loop
from arc.autonomy.paper import reconcile
from arc.autonomy.risk_gate import (
    RiskLimits,
    portfolio_pretrade_gate,
    pretrade_leverage_gate,
)
from arc.autonomy.source import monthly_return_provider


# ----------------------------------------------------------------- fixtures
def _ar1(n=80, phi=0.55, scale=0.02, seed=7):
    rng = np.random.default_rng(seed)
    x = np.zeros(n)
    for t in range(1, n):
        x[t] = phi * x[t - 1] + rng.normal(scale=scale)
    return pd.Series(x, index=pd.date_range("2008-01-31", periods=n, freq="ME"))


def _fat_tailed(n=60, seed=3):
    rng = np.random.default_rng(seed)
    x = rng.standard_t(df=3, size=n) * 0.015      # fat-tailed monthly returns (~1.5% scale)
    x[::13] -= 0.06                                # occasional large negative shocks (negative skew)
    return pd.Series(x, index=pd.date_range("2018-01-31", periods=n, freq="ME"))


def _booked(tmp_path):
    led = PaperLedger(tmp_path)
    book_trial(led, n_trials=45, sr_std=0.07, eval_at_n=24, dsr_min=0.50, issued_by="t")
    return led


# ----------------------------------------------------------------- single-sleeve gate
def test_gate_inactive_below_min_months():
    g = pretrade_leverage_gate(_fat_tailed(10), requested_leverage=12.0, limits=RiskLimits(min_months=24))
    assert g.active is False and g.applied_leverage == 12.0 and g.binding == "inactive"


def test_gate_inactive_on_nan_request():
    g = pretrade_leverage_gate(_fat_tailed(40), requested_leverage=float("nan"))
    assert g.active is False and g.binding == "inactive"


def test_gate_binds_and_caps_on_fat_tail():
    r = _fat_tailed(60)
    tight = RiskLimits(var_limit=0.02, es_limit=0.03, min_months=24)
    g = pretrade_leverage_gate(r, requested_leverage=12.0, limits=tight)
    assert g.active is True
    assert g.applied_leverage < 12.0                       # the tight budget caps leverage
    assert g.binding in ("var_limit", "es_limit")
    if g.binding == "var_limit":                           # the cap binds exactly to the budget
        assert abs(g.var_at_applied - tight.var_limit) < 1e-9
    else:
        assert abs(g.es_at_applied - tight.es_limit) < 1e-9


def test_gate_passes_through_when_budget_loose():
    g = pretrade_leverage_gate(_fat_tailed(60), requested_leverage=3.0,
                               limits=RiskLimits(var_limit=10.0, es_limit=10.0, min_months=24))
    assert g.binding == "vol_target" and abs(g.applied_leverage - 3.0) < 1e-12


def test_gate_is_monotone_in_the_budget():
    r = _fat_tailed(60)
    tight = pretrade_leverage_gate(r, requested_leverage=50.0,
                                   limits=RiskLimits(var_limit=0.02, es_limit=10.0, min_months=24))
    loose = pretrade_leverage_gate(r, requested_leverage=50.0,
                                   limits=RiskLimits(var_limit=0.04, es_limit=10.0, min_months=24))
    assert tight.applied_leverage < loose.applied_leverage  # tighter VaR budget -> lower leverage


# ----------------------------------------------------------------- portfolio gate (uses covariance)
def test_portfolio_gate_uses_correlation():
    rng = np.random.default_rng(7)
    idx = pd.date_range("2018-01-31", periods=60, freq="ME")
    common = rng.standard_normal((60, 1)) * 0.02
    corr = pd.DataFrame(np.hstack([common + rng.standard_normal((60, 1)) * 0.002 for _ in range(3)]),
                        index=idx, columns=list("abc"))            # highly correlated book
    indep = pd.DataFrame(rng.standard_normal((60, 3)) * 0.02, index=idx, columns=list("abc"))
    w = np.full(3, 1 / 3)
    lim = RiskLimits(var_limit=0.02, es_limit=10.0, min_months=24)
    g_corr = portfolio_pretrade_gate(corr, w, requested_leverage=50.0, limits=lim, cov_method="ewma")
    g_indep = portfolio_pretrade_gate(indep, w, requested_leverage=50.0, limits=lim, cov_method="ewma")
    assert g_corr.var_per_unit > g_indep.var_per_unit          # correlation raises the book VaR
    assert g_corr.applied_leverage < g_indep.applied_leverage  # so it caps leverage harder


def test_portfolio_gate_inactive_below_min():
    df = pd.DataFrame(np.random.default_rng(1).standard_normal((8, 3)) * 0.02, columns=list("abc"))
    g = portfolio_pretrade_gate(df, np.full(3, 1 / 3), requested_leverage=5.0,
                                limits=RiskLimits(min_months=24))
    assert g.active is False and g.applied_leverage == 5.0


# ----------------------------------------------------------------- loop integration (THE invariant)
def test_loop_gate_never_touches_the_frozen_stream(tmp_path):
    """Wiring the gate into run_loop changes ONLY the operational sizing; the scored frozen stream is
    byte-identical with the gate on vs off."""
    r = _ar1(60)
    led_off, led_on = _booked(tmp_path / "off"), _booked(tmp_path / "on")
    prov = monthly_return_provider(r, pub_lag_days=1)
    lim = RiskLimits(var_limit=0.02, es_limit=0.03, min_months=6)
    for m in r.index[20:]:
        asof = m + pd.Timedelta(days=2)
        run_loop(asof, prov, led_off)                       # gate OFF
        run_loop(asof, prov, led_on, risk_limits=lim)       # gate ON
    reconcile(r.index[-1] + pd.Timedelta(days=5), r, led_off)
    reconcile(r.index[-1] + pd.Timedelta(days=5), r, led_on)
    fz_off, fz_on = led_off.frozen_frame(), led_on.frozen_frame()
    common = fz_off.index.intersection(fz_on.index)
    assert len(common) == len(fz_off) == len(fz_on) > 0
    assert (fz_off.loc[common, "sleeve_return"] - fz_on.loc[common, "sleeve_return"]).abs().max() < 1e-12
    assert (fz_off.loc[common, "held_position"] - fz_on.loc[common, "held_position"]).abs().max() < 1e-12


def test_loop_proposal_carries_gate_fields(tmp_path):
    r = _ar1(60)
    led = _booked(tmp_path)
    prov = monthly_return_provider(r, pub_lag_days=1)
    out = None
    for m in r.index[20:]:
        out = run_loop(m + pd.Timedelta(days=2), prov, led,
                       risk_limits=RiskLimits(var_limit=0.02, es_limit=0.03, min_months=6))
    p = out["proposal"]
    for k in ("var_forecast", "es_forecast", "risk_gate_binding", "risk_gate_active"):
        assert k in p
    # gate off by default => fields are inert
    out2 = run_loop(r.index[-1] + pd.Timedelta(days=2), prov, _booked(tmp_path / "off"))
    assert out2["proposal"]["risk_gate_active"] is False
