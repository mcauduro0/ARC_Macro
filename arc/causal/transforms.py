"""Point-in-time (causal) feature transforms.

Drop-in, leakage-free replacements for the transforms in macro_risk_os_v2.py. The
invariant every function here satisfies:

    transform(s).iloc[:k]  ==  transform(s.iloc[:k])      for all k

i.e. appending future observations NEVER changes a past output. The legacy
``winsorize`` (full-sample quantiles) violates this; see tests/test_leakage_canary.py.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def causal_winsorize(
    s: pd.Series,
    lower: float = 0.05,
    upper: float = 0.95,
    window: int | None = None,
    min_periods: int = 20,
) -> pd.Series:
    """Clip each point to quantiles computed ONLY from data up to and including it.

    Causal replacement for the look-ahead ``winsorize`` at macro_risk_os_v2.py:166-172,
    which clips to ``s.quantile(0.05/0.95)`` over the full sample (future included).

    - ``window=None`` -> expanding-window quantiles (use all past data).
    - ``window=N``    -> trailing rolling-window quantiles.
    Points before ``min_periods`` are left unclipped (no past information to clip with),
    which is the honest choice — never fabricate bounds from the future.
    """
    s = pd.Series(s).astype("float64")
    if window is None:
        lo = s.expanding(min_periods=min_periods).quantile(lower)
        hi = s.expanding(min_periods=min_periods).quantile(upper)
    else:
        lo = s.rolling(window, min_periods=min_periods).quantile(lower)
        hi = s.rolling(window, min_periods=min_periods).quantile(upper)
    # Where bounds are not yet defined, do not clip.
    lo = lo.where(lo.notna(), -np.inf)
    hi = hi.where(hi.notna(), np.inf)
    return s.clip(lower=lo, upper=hi)


def rolling_zscore(
    s: pd.Series,
    window: int,
    min_periods: int | None = None,
    std_floor: float = 0.0,
    winsor: tuple[float, float] | None = None,
) -> pd.Series:
    """Causal rolling z-score: (x - rolling_mean) / max(rolling_std, std_floor).

    Mean/std use only past+current observations (backward-looking). Optionally apply a
    *causal* winsorize to the resulting z (replacing the leaky full-sample winsorize that
    the legacy ``_z_score_rolling`` appended).
    """
    s = pd.Series(s).astype("float64")
    mp = min_periods if min_periods is not None else max(2, window // 2)
    mean_r = s.rolling(window, min_periods=mp).mean()
    std_r = s.rolling(window, min_periods=mp).std()
    if std_floor:
        std_r = std_r.clip(lower=std_floor)
    z = (s - mean_r) / std_r
    if winsor is not None:
        lo, hi = winsor
        z = causal_winsorize(z, lower=lo, upper=hi, window=window, min_periods=mp)
    return z
