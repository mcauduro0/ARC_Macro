"""Cross-refit as-of invariance of the regime model (the leak proven in adversarial review).

The verified leak: the 12-month HMM refit recomputed the ENTIRE past regime_probs history with the
new vintage's parameters AND a full-window Viterbi state->regime relabeling, so a later refit moved
truly-past regime probabilities (canary: past-date P_stress moved ~0.5 between the asof-2017 and
asof-2020 fits). That repaint contaminates the training feature history.

The fix (ARC_REGIME_POINT_IN_TIME, default on): a-priori labeling from fitted means_ + append-only
regime_probs. This test pins the decisive property the prior test_regime_filtered.py misses (it held
the model fixed): fitting at asof=A2 must NOT change get_probs_at(t)/regime_probs for any t <= A1.

Engine import + a real fit need the ML stack and the collected data, so this is guarded.
"""

from __future__ import annotations

import importlib.util
import os
import sys

import numpy as np
import pandas as pd
import pytest

_HAS_ML = all(importlib.util.find_spec(m) is not None for m in ("xgboost", "hmmlearn"))
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DATA = os.path.join(_ROOT, "server", "model", "data")
_HAS_DATA = os.path.isdir(_DATA) and len([f for f in os.listdir(_DATA) if f.endswith(".csv")]) > 20 if os.path.isdir(_DATA) else False

pytestmark = pytest.mark.skipif(not (_HAS_ML and _HAS_DATA), reason="needs xgboost/hmmlearn + collected data")


def _model():
    sys.path.insert(0, os.path.join(_ROOT, "server", "model"))
    sys.path.insert(0, _ROOT)
    import macro_risk_os_v2 as eng
    dl = eng.DataLayer(eng.DEFAULT_CONFIG)
    dl.load_all(); dl.build_monthly()
    return eng, dl


def _fit_sequence(eng, dl, asofs, pit):
    os.environ["ARC_REGIME_POINT_IN_TIME"] = "1" if pit else "0"
    os.environ["ARC_HMM_FILTERED"] = "1"
    os.environ["ARC_REGIME_PER_SERIES"] = "1"
    rm = eng.RegimeModel(dl, eng.DEFAULT_CONFIG)
    snapshots = []
    for a in asofs:
        rm.fit(asof_date=a)
        snapshots.append(rm.regime_probs.copy() if rm.regime_probs is not None else None)
    return rm, snapshots


def test_pointintime_regime_is_cross_refit_invariant(monkeypatch):
    eng, dl = _model()
    a1 = pd.Timestamp("2018-01-31")
    a2 = pd.Timestamp("2021-01-31")
    rm, snaps = _fit_sequence(eng, dl, [a1, a2], pit=True)
    first, second = snaps
    assert first is not None and second is not None and len(first) > 24
    common = first.index.intersection(second.index)
    common = common[common <= a1]
    assert len(common) > 24, "need overlapping past dates to test invariance"
    # every truly-past date must be byte-for-byte unchanged after the later refit (append-only)
    diff = (second.reindex(common) - first.reindex(common)).abs().max().max()
    assert diff < 1e-9, f"point-in-time regime repainted the past by {diff} (should be 0)"


def test_legacy_regime_is_not_cross_refit_invariant(monkeypatch):
    """Contrast: the legacy full-overwrite path DOES repaint past dates when refit later — the leak."""
    eng, dl = _model()
    a1 = pd.Timestamp("2018-01-31")
    a2 = pd.Timestamp("2021-01-31")
    rm, snaps = _fit_sequence(eng, dl, [a1, a2], pit=False)
    first, second = snaps
    common = first.index.intersection(second.index)
    common = common[common <= a1]
    if len(common) < 24:
        pytest.skip("insufficient overlap")
    diff = (second.reindex(common) - first.reindex(common)).abs().max().max()
    assert diff > 1e-3, "expected legacy path to repaint the past (the leak this fix removes)"
