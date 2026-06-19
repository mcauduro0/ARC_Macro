"""Forward-return and triple-barrier labels (Lopez de Prado).

The alpha target MUST be the FORWARD return (what you earn after deciding at t), not the
contemporaneous return — the audit found the engine trains on (feature_t, return_t) then
deploys as a 1-step-ahead predictor, which destroys OOS IC. ``forward_returns`` produces a
strictly forward, point-in-time target. ``triple_barrier_labels`` adds path-dependent
profit-take / stop-loss / time-out labels and the touch time used for purging.
"""

from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd


def forward_returns(returns: pd.Series, horizon: int = 1) -> pd.Series:
    """h-period forward cumulative return aligned to the DECISION date t.

    label_t = prod_{k=1..h}(1 + r_{t+k}) - 1, indexed at t. The last h points are NaN
    (their future is unknown) — never fabricate the future.
    """
    if horizon < 1:
        raise ValueError("horizon must be >= 1")
    r = pd.Series(returns).astype("float64")
    growth = (1.0 + r)
    fwd = growth.shift(-1).rolling(horizon).apply(np.prod, raw=True).shift(-(horizon - 1)) - 1.0
    fwd.iloc[-horizon:] = np.nan
    fwd.name = f"fwd_ret_{horizon}"
    return fwd


def _ewm_vol(returns: pd.Series, span: int = 20) -> pd.Series:
    return pd.Series(returns).astype("float64").ewm(span=span).std()


def triple_barrier_labels(
    prices: pd.Series,
    t_events: Optional[pd.Index] = None,
    *,
    pt: float = 1.0,
    sl: float = 1.0,
    max_holding: int = 10,
    vol_span: int = 20,
    target: Optional[pd.Series] = None,
) -> pd.DataFrame:
    """Triple-barrier labels for events.

    For each event start t: an upper barrier at +pt*target_t, a lower at -sl*target_t, and a
    vertical barrier at t+max_holding bars. Returns a DataFrame indexed by event start with:
      - t1    : time of FIRST barrier touch (used for purging/embargo)
      - ret   : realized return from t to t1
      - label : +1 (upper), -1 (lower), 0 (vertical/time-out)
    """
    prices = pd.Series(prices).astype("float64")
    rets = prices.pct_change()
    tgt = (target if target is not None else _ewm_vol(rets, vol_span)).reindex(prices.index).bfill()
    events = pd.Index(t_events) if t_events is not None else prices.index[:-1]

    rows = []
    idx_list = list(prices.index)
    pos = {ts: i for i, ts in enumerate(idx_list)}
    for t in events:
        i0 = pos[t]
        i_end = min(i0 + max_holding, len(idx_list) - 1)
        if i_end <= i0:
            continue
        p0 = prices.iloc[i0]
        up = pt * tgt.iloc[i0]
        dn = sl * tgt.iloc[i0]
        touch_i = i_end
        label = 0
        for i in range(i0 + 1, i_end + 1):
            r = prices.iloc[i] / p0 - 1.0
            if r >= up:
                touch_i, label = i, 1
                break
            if r <= -dn:
                touch_i, label = i, -1
                break
        t1 = idx_list[touch_i]
        rows.append((t, t1, prices.iloc[touch_i] / p0 - 1.0, label))
    out = pd.DataFrame(rows, columns=["t0", "t1", "ret", "label"]).set_index("t0")
    return out
