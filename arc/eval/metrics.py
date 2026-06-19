"""Selection-bias-aware performance statistics.

- probabilistic_sharpe_ratio (PSR) and deflated_sharpe_ratio (DSR): is the Sharpe real once
  you account for sample length, non-normality, AND the number of trials? (Bailey & Lopez de
  Prado). The audit's 0.39->3.92 Sharpe trail is exactly what DSR exists to deflate.
- probability_of_backtest_overfitting (PBO): via Combinatorially Symmetric CV — the chance
  the in-sample-best config is below the OOS median.
- newey_west_tstat: HAC t-stat for autocorrelated, overlapping monthly returns/IC.
"""

from __future__ import annotations

import itertools
from typing import Optional

import numpy as np
import pandas as pd
from scipy.stats import norm

_EULER_GAMMA = 0.5772156649015329


def probabilistic_sharpe_ratio(
    sr: float, n: int, skew: float = 0.0, kurt: float = 3.0, sr_benchmark: float = 0.0
) -> float:
    """P(true Sharpe > sr_benchmark) given observed per-period ``sr`` over ``n`` returns.
    ``kurt`` is non-excess kurtosis (normal = 3)."""
    if n < 2:
        return float("nan")
    denom = np.sqrt(max(1e-12, 1.0 - skew * sr + (kurt - 1.0) / 4.0 * sr ** 2))
    z = (sr - sr_benchmark) * np.sqrt(n - 1) / denom
    return float(norm.cdf(z))


def expected_max_sharpe(n_trials: int, sr_std: float = 1.0) -> float:
    """Expected maximum of ``n_trials`` i.i.d. Sharpe estimates (each ~N(0, sr_std^2)).
    This is the benchmark a strategy must beat to be considered non-spurious."""
    if n_trials <= 1:
        return 0.0
    z1 = norm.ppf(1.0 - 1.0 / n_trials)
    z2 = norm.ppf(1.0 - 1.0 / (n_trials * np.e))
    return float(sr_std * ((1.0 - _EULER_GAMMA) * z1 + _EULER_GAMMA * z2))


def deflated_sharpe_ratio(
    sr: float, n: int, n_trials: int, sr_std: float, skew: float = 0.0, kurt: float = 3.0
) -> float:
    """DSR = PSR with the benchmark set to E[max Sharpe] over ``n_trials`` (variance
    ``sr_std^2`` across trials). High DSR => the Sharpe survives selection bias."""
    sr0 = expected_max_sharpe(n_trials, sr_std)
    return probabilistic_sharpe_ratio(sr, n, skew, kurt, sr_benchmark=sr0)


def newey_west_tstat(x, lags: Optional[int] = None) -> float:
    """HAC (Newey-West) t-stat of the mean of ``x`` — honest SE under autocorrelation."""
    a = np.asarray(x, dtype="float64")
    a = a[~np.isnan(a)]
    n = len(a)
    if n < 3:
        return float("nan")
    if lags is None:
        lags = int(np.floor(4 * (n / 100.0) ** (2.0 / 9.0)))
    mu = a.mean()
    e = a - mu
    s = (e @ e) / n
    for l in range(1, max(1, lags) + 1):
        if l >= n:
            break
        w = 1.0 - l / (lags + 1.0)
        s += 2.0 * w * (e[l:] @ e[:-l]) / n
    se = np.sqrt(s / n)
    return float(mu / se) if se > 0 else float("nan")


def information_coefficient(pred, real, method: str = "spearman") -> float:
    """Rank (default) or Pearson correlation of predictions vs realized — the OOS edge."""
    df = pd.concat([pd.Series(pred).reset_index(drop=True),
                    pd.Series(real).reset_index(drop=True)], axis=1).dropna()
    if len(df) < 3:
        return float("nan")
    return float(df.iloc[:, 0].corr(df.iloc[:, 1], method=method))


def probability_of_backtest_overfitting(perf, n_splits: int = 10, metric: str = "sharpe") -> float:
    """PBO via Combinatorially Symmetric CV. ``perf`` is a (T x N) matrix of per-period
    performance for N configs over T periods. Returns the probability that the in-sample-best
    config ranks below the OOS median (~0.5 for noise, high for overfitting)."""
    M = np.asarray(perf, dtype="float64")
    if M.ndim != 2:
        raise ValueError("perf must be 2D (T x N)")
    T, N = M.shape
    if n_splits % 2 != 0:
        raise ValueError("n_splits must be even")
    blocks = np.array_split(np.arange(T), n_splits)

    def agg(sub: np.ndarray) -> np.ndarray:
        if metric == "sharpe":
            mu = sub.mean(0)
            sd = sub.std(0, ddof=1)
            return np.where(sd > 0, mu / sd, 0.0)
        return sub.mean(0)

    half = n_splits // 2
    lambdas = []
    for combo in itertools.combinations(range(n_splits), half):
        is_rows = np.concatenate([blocks[b] for b in combo])
        oos_rows = np.concatenate([blocks[b] for b in range(n_splits) if b not in combo])
        is_perf = agg(M[is_rows])
        oos_perf = agg(M[oos_rows])
        n_star = int(np.argmax(is_perf))
        order = np.argsort(oos_perf)  # ascending; higher rank = better OOS
        rank = int(np.where(order == n_star)[0][0]) + 1  # 1..N
        omega = rank / (N + 1.0)
        lambdas.append(np.log(omega / (1.0 - omega)))
    lam = np.asarray(lambdas)
    return float(np.mean(lam <= 0.0))
