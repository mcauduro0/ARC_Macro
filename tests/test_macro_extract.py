"""Honesty guard for the macro extractor (scripts/dump_web_state.py::_extract_macro).

No engine, no network — stub objects standing in for the engine. Proves the extractor is DEFENSIVE and HONEST:
it never crashes on a missing/odd engine, it emits a field ONLY when genuinely populated (null + a note
otherwise), it FITS the regime model when initialize() left it unfit, and it REFUSES the degenerate 1/3
placeholder (a "regime" with no variation is omitted, never shown as if real). Mirrors the discipline of the
rest of the codebase: report absence as absence; never fabricate.
"""

from __future__ import annotations

import importlib.util
import json
import os

import pandas as pd
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture(scope="module")
def extract():
    spec = importlib.util.spec_from_file_location(
        "dump_web_state_mod", os.path.join(ROOT, "scripts", "dump_web_state.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # top level only sets sys.path/env; the engine import lives in main()
    return mod._extract_macro


def _idx(n):
    return pd.date_range("2025-01-31", periods=n, freq="ME")


class _FE:
    def __init__(self, *, rstar=None, fdf=None, fx=None):
        if rstar is not None:
            self._composite_rstar = rstar
        if fdf is not None:
            self.feature_df = fdf
        if fx is not None:
            self._fx_fair = fx


class _RM:
    def __init__(self, *, probs=None, fit_probs=None):
        self.regime_probs = probs
        self._fit_probs = fit_probs

    def fit(self):
        self.regime_probs = self._fit_probs


class _DL:
    def __init__(self, *, monthly=None, ret_df=None):
        self.monthly = monthly
        self.ret_df = ret_df


class _Eng:
    def __init__(self, fe=None, rm=None, dl=None):
        self.feature_engine = fe
        self.regime_model = rm
        self.data_layer = dl


def test_empty_engine_is_all_null_and_never_crashes(extract):
    m = extract(_Eng())
    assert m["rstar"] is None and m["regime"] is None and m["state_vars"] is None
    assert m["fx_fair"] is None and m["di_curve"] is None
    assert len(m["notes"]) >= 4          # each absent field is explained, not hidden
    assert json.dumps(m)                  # fully serializable for the API


def test_populates_only_real_fields(extract):
    rstar = pd.Series([3.0, 3.5, 4.0], index=_idx(3))
    fdf = pd.DataFrame({"Z_fiscal": [0.1, 0.2], "Z_vix": [-0.3, -0.1]}, index=_idx(2))
    monthly = {"ptax": pd.Series([5.1, 5.2]), "di_1y": pd.Series([14.0, 14.4]),
               "di_10y": pd.Series([14.8, 14.9])}
    regime = pd.DataFrame({"P_carry": [0.8, 0.2], "P_riskoff": [0.1, 0.7], "P_stress": [0.1, 0.1]}, index=_idx(2))
    eng = _Eng(_FE(rstar=rstar, fdf=fdf, fx=5.4),
               _RM(probs=regime),
               _DL(monthly=monthly, ret_df=pd.DataFrame(index=_idx(3))))
    m = extract(eng)
    assert m["rstar"]["latest"] == 4.0 and len(m["rstar"]["history"]) == 3
    assert m["regime"]["latest"]["P_riskoff"] == 0.7
    assert {v["key"] for v in m["state_vars"]} == {"Z_fiscal", "Z_vix"}
    assert m["fx_fair"]["fair"] == 5.4 and m["fx_fair"]["spot"] == 5.2
    assert m["fx_fair"]["misalignment_pct"] == round((5.2 / 5.4 - 1) * 100, 2)
    assert {p["tenor"] for p in m["di_curve"]} == {"1Y", "10Y"}
    assert m["notes"] == []               # nothing omitted -> no noise


def test_refuses_degenerate_regime_placeholder(extract):
    # the unfit model returns a constant 1/3 across all states — NOT a real estimate. Must be omitted.
    flat = pd.DataFrame({"P_carry": [1 / 3, 1 / 3], "P_riskoff": [1 / 3, 1 / 3],
                         "P_stress": [1 / 3, 1 / 3]}, index=_idx(2))
    m = extract(_Eng(rm=_RM(probs=flat)))
    assert m["regime"] is None
    assert any("placeholder" in n for n in m["notes"])


def test_fits_unfit_regime_model(extract):
    # initialize() leaves regime_probs None; the extractor must call fit() and then emit the real posterior.
    real = pd.DataFrame({"P_carry": [0.9, 0.1], "P_riskoff": [0.05, 0.85], "P_stress": [0.05, 0.05]}, index=_idx(2))
    m = extract(_Eng(rm=_RM(probs=None, fit_probs=real)))
    assert m["regime"] is not None
    assert m["regime"]["latest"]["P_riskoff"] == 0.85


def test_build_web_state_passes_macro_through(tmp_path):
    """The bridge must forward the cached macro context verbatim to the UI (state.py passthrough)."""
    from arc.webapi.state import build_web_state
    macro = {"as_of": "2026-06-30", "rstar": None, "regime": None, "state_vars": None,
             "fx_fair": None, "di_curve": None, "notes": ["x"]}
    state = build_web_state(str(tmp_path), cached={"as_of": "2026-06-30", "proposals": {}, "macro": macro})
    assert state["macro"] == macro
