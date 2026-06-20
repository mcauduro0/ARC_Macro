"""Phase 4.4 nowcast — CI-native tests. The crown-jewel is as-of-invariance: the factor at month E
must depend only on data <= E (no look-ahead), proven by trim-and-rebuild. Plus: it tracks a true
common factor, survives a ragged edge, and the surprise transform is causal."""

from __future__ import annotations

import numpy as np
import pandas as pd

from arc.features.nowcast import nowcast_surprise, pit_dynamic_factor


def _panel(n=72, k=4, seed=0, lag_last=0):
    """A common activity factor g with per-series loadings + noise; optionally a ragged edge on col 0."""
    rng = np.random.default_rng(seed)
    g = np.cumsum(rng.normal(scale=0.3, size=n))  # persistent common factor
    idx = pd.date_range("2010-01-31", periods=n, freq="ME")
    cols = {}
    for j in range(k):
        load = 0.5 + 0.5 * rng.random()
        cols[f"s{j}"] = pd.Series(load * g + rng.normal(scale=0.4, size=n), index=idx)
    df = pd.DataFrame(cols)
    if lag_last:
        df.iloc[-lag_last:, 0] = np.nan  # col s0 is the laggy official series
    return df, pd.Series(g, index=idx)


def test_nowcast_is_as_of_invariant():
    """factor(panel)[E] == factor(panel.loc[:E])[E] for every E — the leak gate, true by construction."""
    panel, _ = _panel(72, 4, seed=1)
    full = pit_dynamic_factor(panel, ref_col="s0", min_obs=24)
    for E in [panel.index[40], panel.index[55], panel.index[-1]]:
        trimmed = pit_dynamic_factor(panel.loc[:E], ref_col="s0", min_obs=24)
        assert abs(full.loc[E] - trimmed.loc[E]) < 1e-12


def test_nowcast_tracks_common_factor():
    """The nowcast should correlate strongly with the true common activity factor."""
    panel, g = _panel(72, 4, seed=2)
    f = pit_dynamic_factor(panel, ref_col="s0", min_obs=24).dropna()
    common = f.index.intersection(g.index)
    # compare changes (the factor level is re-standardized each month; co-movement is what matters)
    corr = np.corrcoef(f.loc[common].diff().dropna().values,
                       g.loc[common].diff().dropna().values)[0, 1]
    assert corr > 0.5


def test_nowcast_survives_ragged_edge():
    """With the laggy official series missing at the last 2 months, the nowcast is still computed
    (from the timely series) — that is the whole point of a nowcast."""
    panel, _ = _panel(72, 4, seed=3, lag_last=2)
    f = pit_dynamic_factor(panel, ref_col="s0", min_obs=24)
    assert np.isfinite(f.iloc[-1])
    assert np.isfinite(f.iloc[-2])


def test_nowcast_sign_is_oriented():
    """Higher factor => more activity: the factor co-moves positively with the reference series."""
    panel, _ = _panel(72, 4, seed=4)
    f = pit_dynamic_factor(panel, ref_col="s0", min_obs=24).dropna()
    common = f.index.intersection(panel.index)
    corr = np.corrcoef(f.loc[common].diff().dropna().values,
                       panel["s0"].loc[common].diff().dropna().values)[0, 1]
    assert corr > 0


def test_surprise_is_causal():
    """nowcast_surprise uses expanding stats — appending future data cannot change earlier values."""
    panel, _ = _panel(72, 4, seed=5)
    f = pit_dynamic_factor(panel, ref_col="s0", min_obs=24)
    s_full = nowcast_surprise(f)
    s_short = nowcast_surprise(f.iloc[:50])
    common = s_short.dropna().index.intersection(s_full.dropna().index)
    assert len(common) > 10
    assert (s_full.reindex(common) - s_short.reindex(common)).abs().max() < 1e-12
