"""Golden-master / wiring test for the engine's causal winsorize swap (audit feat-1/eq-2).

Two layers:
  1. Characterization (runs everywhere): a faithful copy of the LEGACY full-sample winsorize
     leaks the future; the causal replacement the engine now delegates to does not, and it
     materially changes recent values (documenting the leak's magnitude). Properties, not
     pinned floats — robust across pandas quantile-interpolation differences.
  2. Live wiring (skipped unless the full ML stack is installed): imports the ACTUAL engine
     and asserts macro_risk_os_v2.winsorize / composite_equilibrium._winsorize are causal.
"""

from __future__ import annotations

import importlib.util
import os
import sys

import pandas as pd
import pytest

from arc.causal import causal_winsorize
from tests.canary import is_as_of_invariant, make_series


def _legacy_winsorize(s: pd.Series, lower: float = 0.05, upper: float = 0.95) -> pd.Series:
    """Faithful copy of the pre-fix engine winsorize (macro_risk_os_v2.py:166-172)."""
    if len(s) < 10:
        return s
    return s.clip(s.quantile(lower), s.quantile(upper))


def _causal(s: pd.Series) -> pd.Series:
    return causal_winsorize(s, 0.05, 0.95, window=None, min_periods=10)


def test_characterization_legacy_leaks_causal_fix_does_not():
    s = make_series(n=120, future_shock=True, seed=7)
    assert not is_as_of_invariant(_legacy_winsorize, s), "legacy should leak (the bug)"
    assert is_as_of_invariant(_causal, s), "causal replacement must be point-in-time"


def test_fix_materially_changes_recent_values():
    """The swap is not cosmetic: legacy vs causal differ on the recent tail (the leaked region)."""
    s = make_series(n=120, future_shock=True, seed=7)
    div = (_legacy_winsorize(s) - _causal(s)).abs().iloc[-20:].max()
    assert float(div) > 0.0


def test_causal_still_clips_extremes():
    s = make_series(n=120, seed=1)
    s.iloc[110] = s.iloc[:110].max() + 50.0
    assert _causal(s).iloc[110] < s.iloc[110]


# --- live wiring (needs xgboost+hmmlearn to import the engine) ---
_HAS_ML = all(importlib.util.find_spec(m) is not None for m in ("xgboost", "hmmlearn"))


@pytest.mark.skipif(not _HAS_ML, reason="full ML stack (xgboost/hmmlearn) not installed")
def test_engine_modules_use_causal_winsorize():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sys.path.insert(0, os.path.join(root, "server", "model"))  # for feature_selection
    sys.path.insert(0, root)  # for arc
    import composite_equilibrium as ce
    import macro_risk_os_v2 as eng

    s = make_series(n=120, future_shock=True, seed=7)
    assert is_as_of_invariant(eng.winsorize, s), "engine.winsorize must be causal after wiring"
    assert is_as_of_invariant(ce._winsorize, s), "composite._winsorize must be causal after wiring"
    # functionality preserved: a late spike is still clipped down
    sp = s.copy()
    sp.iloc[110] = sp.iloc[:110].max() + 50.0
    assert eng.winsorize(sp).iloc[110] < sp.iloc[110]
