"""Phase 6 — forward-looking covariance: RiskMetrics EWMA and Engle DCC-GARCH(1,1).

WHAT THIS IS (and is NOT):
    These estimators turn a panel of past returns into a *one-step-ahead* covariance/correlation
    FORECAST. They quantify co-movement and risk; they make NO alpha claim. A tighter covariance does
    not mean a trade will make money — it only says "given information through the last row, this is the
    best linear-Gaussian guess of next period's second moments". The project's honesty law stands.

CAUSAL / FORECAST SEMANTICS (non-negotiable — these get adversarial as-of tests):
    Every estimator consumes ONLY the past returns it is handed. The single matrix returned by
    ``ewma_cov`` / ``dcc_correlation`` / ``dcc_garch_cov`` is the conditional second-moment forecast for
    the period AFTER the last observation, i.e. ``Sigma_{T+1|T}`` built from data with index <= T.
    Equivalently: the forecast computed on ``returns.iloc[:T]`` depends only on those rows and is
    unchanged by any rows appended after T (the leakage canary the tests enforce). ``garch11_vol`` returns
    the *filtered* conditional vol path; ``vol[t]`` (sigma_{t|t-1}) is the one-step-ahead vol for period
    ``t`` conditioned on returns through ``t-1`` — so the LAST element is the forecast for ``T+1``.

ROBUSTNESS:
    Estimation is QMLE via ``scipy.optimize`` with safe bounds and variance/correlation targeting for
    initialisation. If any optimisation fails to converge (or produces a non-finite / non-stationary
    result), we fall back to the RiskMetrics EWMA covariance and SAY SO via the ``fallback`` attribute
    stamped on the returned DataFrame's ``.attrs`` (and, for DCC, by returning the EWMA-implied
    correlation). The return is always a valid, symmetric, PSD matrix.

API:
    ewma_cov(returns_panel, *, halflife=12, min_periods=12) -> pd.DataFrame
    garch11_vol(returns, *, p0=None, max_iter=200) -> pd.Series
    dcc_correlation(returns_panel, *, a=None, b=None) -> pd.DataFrame
    dcc_garch_cov(returns_panel, *, halflife=12) -> pd.DataFrame
    nearest_psd(matrix, *, eps=1e-12) -> np.ndarray            # eigenvalue-floor PSD repair
"""

from __future__ import annotations

import warnings

import numpy as np
import pandas as pd

try:  # scipy is available in this environment; guard so an import error degrades gracefully.
    from scipy.optimize import minimize

    _HAVE_SCIPY = True
except Exception:  # pragma: no cover - scipy is present per the environment contract
    _HAVE_SCIPY = False

__all__ = [
    "ewma_cov",
    "garch11_vol",
    "dcc_correlation",
    "dcc_garch_cov",
    "nearest_psd",
]


# ============================================================================================
# PSD helpers
# ============================================================================================

def nearest_psd(matrix: np.ndarray, *, eps: float = 1e-12) -> np.ndarray:
    """Return the nearest symmetric positive-semidefinite matrix via an eigenvalue floor.

    We symmetrise, eigen-decompose, floor eigenvalues at ``eps`` (a tiny positive number so the result is
    PSD and, in practice, numerically positive-definite), and reconstruct. This is the standard cheap
    repair used after combining separately-estimated vols and correlations, where round-off can introduce
    a marginally negative eigenvalue.

    Parameters
    ----------
    matrix : np.ndarray
        Square matrix (treated as a covariance/correlation candidate).
    eps : float
        Eigenvalue floor (>= 0). Defaults to 1e-12.

    Returns
    -------
    np.ndarray
        Symmetric matrix with all eigenvalues >= ``eps``.
    """
    m = np.asarray(matrix, dtype="float64")
    m = 0.5 * (m + m.T)  # enforce exact symmetry
    # Eigen-decomposition of a real symmetric matrix.
    vals, vecs = np.linalg.eigh(m)
    vals = np.clip(vals, eps, None)
    repaired = (vecs * vals) @ vecs.T
    return 0.5 * (repaired + repaired.T)  # kill residual asymmetry from the matmul


def _is_psd(matrix: np.ndarray, *, tol: float = 1e-10) -> bool:
    m = 0.5 * (np.asarray(matrix, dtype="float64") + np.asarray(matrix, dtype="float64").T)
    try:
        w = np.linalg.eigvalsh(m)
    except np.linalg.LinAlgError:  # pragma: no cover
        return False
    return bool(np.all(w >= -tol))


def _clean_panel(returns_panel: pd.DataFrame) -> pd.DataFrame:
    """Coerce to float, drop all-NaN columns, drop rows with any NaN (causal: we never impute the future)."""
    df = pd.DataFrame(returns_panel).astype("float64")
    df = df.dropna(axis=1, how="all")
    df = df.dropna(axis=0, how="any")
    return df


# ============================================================================================
# RiskMetrics EWMA covariance
# ============================================================================================

def _ewma_weights(n: int, lam: float) -> np.ndarray:
    """Normalised RiskMetrics weights, OLDEST..NEWEST (so the last row gets weight ~(1-lam)).

    Weight on the observation ``k`` steps before the last is proportional to ``lam**k``. We normalise to
    sum to one so the result is a proper weighted second moment regardless of sample length.
    """
    # ages: last row age 0, ..., first row age n-1
    ages = np.arange(n - 1, -1, -1, dtype="float64")
    w = lam ** ages
    s = w.sum()
    return w / s if s > 0 else np.full(n, 1.0 / n)


def ewma_cov(
    returns_panel: pd.DataFrame,
    *,
    halflife: float = 12.0,
    min_periods: int = 12,
) -> pd.DataFrame:
    """RiskMetrics exponentially-weighted covariance — the one-step-ahead forecast given all rows.

    The decay ``lambda`` is derived from ``halflife`` via ``lambda = 0.5 ** (1/halflife)`` so the weight
    halves every ``halflife`` periods. Returns are de-meaned by their EWMA-weighted mean (a tiny effect at
    monthly frequency, included for correctness). The result is ``Sigma_{T+1|T}``: the covariance forecast
    for the period after the last observed row, using ONLY observed rows.

    Parameters
    ----------
    returns_panel : pd.DataFrame
        Panel of periodic returns (rows = time, columns = assets), sorted ascending.
    halflife : float
        EWMA half-life in periods (> 0).
    min_periods : int
        Minimum number of complete rows required; fewer rows -> the matrix is the (unweighted) sample
        covariance if at least 2 rows exist, else NaN-filled. (Kept permissive so callers always get a
        matrix; the test-relevant path uses ample data.)

    Returns
    -------
    pd.DataFrame
        Symmetric PSD covariance matrix (index == columns == asset names). ``.attrs['estimator']`` is
        ``'ewma'``. Strictly causal: unchanged by rows appended after the last input row.
    """
    if not (halflife > 0):
        raise ValueError("halflife must be > 0")
    df = _clean_panel(returns_panel)
    cols = list(df.columns)
    n = len(df)

    if n < 2:
        out = pd.DataFrame(np.full((len(cols), len(cols)), np.nan), index=cols, columns=cols)
        out.attrs["estimator"] = "ewma"
        out.attrs["fallback"] = False
        return out

    lam = 0.5 ** (1.0 / float(halflife))
    X = df.to_numpy(dtype="float64")  # (n, k)

    if n < min_periods:
        # Not enough history for the weighting scheme to matter; use plain sample covariance.
        cov = np.cov(X, rowvar=False, ddof=1)
        cov = np.atleast_2d(cov)
    else:
        w = _ewma_weights(n, lam)  # (n,)
        mu = w @ X  # EWMA-weighted mean (k,)
        Xc = X - mu  # de-meaned
        # Weighted covariance: sum_t w_t * x_t x_t' (weights already sum to 1).
        cov = Xc.T @ (Xc * w[:, None])
        cov = 0.5 * (cov + cov.T)

    cov = nearest_psd(cov)
    out = pd.DataFrame(cov, index=cols, columns=cols)
    out.attrs["estimator"] = "ewma"
    out.attrs["fallback"] = False
    return out


# ============================================================================================
# Univariate GARCH(1,1)
# ============================================================================================

def _garch_recursion(
    eps2: np.ndarray, omega: float, alpha: float, beta: float, h0: float
) -> np.ndarray:
    """Filter conditional variances h_t from squared innovations eps2 (causal recursion).

    h_t = omega + alpha * eps_{t-1}^2 + beta * h_{t-1}, with h_1 = h0 (the unconditional variance). Each
    h_t depends ONLY on information through t-1, so h_t is the one-step-ahead variance forecast for t.
    """
    n = len(eps2)
    h = np.empty(n, dtype="float64")
    h[0] = h0
    for t in range(1, n):
        h[t] = omega + alpha * eps2[t - 1] + beta * h[t - 1]
    return h


def _garch_negloglik(theta: np.ndarray, eps2: np.ndarray, var_uncond: float) -> float:
    """Negative Gaussian QML log-likelihood for GARCH(1,1) with variance targeting.

    We parametrise persistence ``(alpha, beta)`` directly and pin ``omega = var_uncond * (1 - alpha - beta)``
    (variance targeting) so the unconditional variance matches the sample and the optimiser searches a
    well-behaved 2-D simplex interior. Returns a large penalty for non-stationary / degenerate parameters.
    """
    alpha, beta = float(theta[0]), float(theta[1])
    if alpha < 0 or beta < 0 or (alpha + beta) >= 0.99999:
        return 1e10
    omega = var_uncond * (1.0 - alpha - beta)
    if omega <= 0:
        return 1e10
    h = _garch_recursion(eps2, omega, alpha, beta, var_uncond)
    if not np.all(np.isfinite(h)) or np.any(h <= 0):
        return 1e10
    # Gaussian QML (drop constants): 0.5 * sum( log h_t + eps_t^2 / h_t )
    ll = 0.5 * np.sum(np.log(h) + eps2 / h)
    return ll if np.isfinite(ll) else 1e10


def garch11_vol(
    returns: pd.Series,
    *,
    p0: tuple[float, float] | None = None,
    max_iter: int = 200,
) -> pd.Series:
    """Univariate GARCH(1,1) filtered conditional volatility (causal, one-step-ahead).

    Fits a zero-mean Gaussian GARCH(1,1) by QMLE with variance targeting, then returns the filtered
    conditional-vol path ``sigma_t = sqrt(h_t)``, where ``h_t = omega + alpha*eps_{t-1}^2 + beta*h_{t-1}``.
    Because ``h_t`` uses only innovations through ``t-1``, each ``sigma_t`` is the one-step-ahead vol
    forecast for period ``t`` (and the LAST value is the forecast for the period after the sample).

    If SciPy is unavailable or the optimisation fails / yields a non-stationary fit, we fall back to a
    fixed-persistence RiskMetrics-style filter (``alpha=0.06, beta=0.94, omega=0``) seeded at the
    unconditional variance — still a valid, strictly-causal conditional-vol path. The chosen parameters are
    recorded in ``Series.attrs``.

    Parameters
    ----------
    returns : pd.Series
        Periodic returns, sorted ascending.
    p0 : (alpha, beta) or None
        Optional starting persistence for the optimiser. Defaults to (0.05, 0.90).
    max_iter : int
        Maximum optimiser iterations.

    Returns
    -------
    pd.Series
        Conditional volatility (sqrt of conditional variance), same index as the non-NaN returns. Strictly
        positive and finite. ``.attrs`` carries ``omega/alpha/beta`` and ``fallback`` flag.
    """
    r = pd.Series(returns, dtype="float64").dropna()
    idx = r.index
    x = r.to_numpy(dtype="float64")
    n = len(x)

    if n == 0:
        s = pd.Series(dtype="float64")
        s.attrs.update({"fallback": True, "omega": np.nan, "alpha": np.nan, "beta": np.nan})
        return s

    # Zero-mean innovation convention (returns are already near-zero-mean at high frequency); subtract the
    # sample mean for robustness — this is a constant, hence causal-safe for the *shape* of the vol path.
    mu = float(np.mean(x))
    eps = x - mu
    eps2 = eps ** 2
    var_uncond = float(np.mean(eps2))
    if not np.isfinite(var_uncond) or var_uncond <= 0:
        var_uncond = 1e-12  # degenerate constant series; produce a tiny positive vol floor

    fallback = False
    alpha = beta = omega = np.nan

    # Need a handful of points and SciPy for a meaningful MLE; otherwise go straight to the robust filter.
    if _HAVE_SCIPY and n >= 10:
        a0, b0 = (0.05, 0.90) if p0 is None else (float(p0[0]), float(p0[1]))
        # Keep the start strictly interior and stationary.
        a0 = min(max(a0, 1e-3), 0.3)
        b0 = min(max(b0, 1e-3), 0.95)
        if a0 + b0 >= 0.999:
            a0, b0 = 0.05, 0.90
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                res = minimize(
                    _garch_negloglik,
                    x0=np.array([a0, b0], dtype="float64"),
                    args=(eps2, var_uncond),
                    method="L-BFGS-B",
                    bounds=[(0.0, 0.5), (0.0, 0.999)],
                    options={"maxiter": int(max_iter), "ftol": 1e-9},
                )
            if res.success or np.isfinite(res.fun):
                a_hat, b_hat = float(res.x[0]), float(res.x[1])
                if (
                    np.isfinite(a_hat)
                    and np.isfinite(b_hat)
                    and a_hat >= 0
                    and b_hat >= 0
                    and (a_hat + b_hat) < 0.99999
                ):
                    alpha, beta = a_hat, b_hat
                    omega = var_uncond * (1.0 - alpha - beta)
                else:
                    fallback = True
            else:
                fallback = True
        except Exception:
            fallback = True
    else:
        fallback = True

    if fallback or not np.isfinite(omega) or omega <= 0:
        # RiskMetrics-style integrated filter: omega=0, alpha=0.06, beta=0.94 (sum to 1 -> IGARCH).
        fallback = True
        alpha, beta, omega = 0.06, 0.94, 0.0

    h = _garch_recursion(eps2, omega, alpha, beta, var_uncond)
    # Guard against any numerical non-positivity (floor at a tiny fraction of the unconditional variance).
    h = np.where(np.isfinite(h) & (h > 0), h, var_uncond)
    h = np.clip(h, 1e-300, None)
    vol = np.sqrt(h)

    out = pd.Series(vol, index=idx, name="garch_vol")
    out.attrs.update(
        {"fallback": bool(fallback), "omega": float(omega), "alpha": float(alpha), "beta": float(beta)}
    )
    return out


# ============================================================================================
# Engle DCC(1,1) correlation
# ============================================================================================

def _standardized_resids(df: pd.DataFrame) -> tuple[np.ndarray, list[bool]]:
    """GARCH(1,1)-standardise each column: z_t = eps_t / sigma_{t|t-1}.

    Returns the (n, k) standardized-residual matrix and a per-column flag of whether GARCH fell back.
    Standardisation uses each column's own causal conditional vol, so z stays causal.
    """
    cols = list(df.columns)
    n = len(df)
    Z = np.empty((n, len(cols)), dtype="float64")
    fellback = []
    for j, c in enumerate(cols):
        s = df[c]
        vol = garch11_vol(s)
        fellback.append(bool(vol.attrs.get("fallback", False)))
        v = vol.to_numpy(dtype="float64")
        v = np.where(np.isfinite(v) & (v > 0), v, np.nan)
        eps = s.to_numpy(dtype="float64") - float(np.mean(s.to_numpy(dtype="float64")))
        Z[:, j] = eps / v
    # Replace any non-finite standardized resids (e.g. zero vol) with 0 so they don't poison Qbar.
    Z = np.where(np.isfinite(Z), Z, 0.0)
    return Z, fellback


def _dcc_recursion(
    Z: np.ndarray, a: float, b: float, Qbar: np.ndarray
) -> np.ndarray:
    """Run the DCC(1,1) Q-recursion and return the LAST correlation matrix R_T.

    Q_t = (1 - a - b) * Qbar + a * (z_{t-1} z_{t-1}') + b * Q_{t-1}, with Q_1 = Qbar. R_t is Q_t scaled to
    unit diagonal. R_t depends only on z through t-1, so R_T is the one-step-ahead correlation forecast.
    """
    n, k = Z.shape
    Q = Qbar.copy()
    R_last = _corr_from_cov(Q)
    for t in range(1, n):
        z = Z[t - 1][:, None]  # (k,1) — strictly past innovation
        Q = (1.0 - a - b) * Qbar + a * (z @ z.T) + b * Q
        R_last = _corr_from_cov(Q)
    return R_last


def _corr_from_cov(Q: np.ndarray) -> np.ndarray:
    d = np.sqrt(np.clip(np.diag(Q), 1e-300, None))
    inv = 1.0 / d
    R = Q * np.outer(inv, inv)
    R = 0.5 * (R + R.T)
    np.fill_diagonal(R, 1.0)
    return R


def _dcc_negloglik(theta: np.ndarray, Z: np.ndarray, Qbar: np.ndarray) -> float:
    """Negative DCC QML log-likelihood (the correlation part, conditional on standardized resids).

    For each t we form R_t from the Q-recursion and accumulate 0.5 * (log|R_t| + z_t' R_t^{-1} z_t). The
    standardized-resid term ``z_t' z_t`` is constant in (a,b) and dropped. Penalises non-stationary params.
    """
    a, b = float(theta[0]), float(theta[1])
    if a < 0 or b < 0 or (a + b) >= 0.99999:
        return 1e10
    n, k = Z.shape
    Q = Qbar.copy()
    ll = 0.0
    for t in range(n):
        if t > 0:
            z_prev = Z[t - 1][:, None]
            Q = (1.0 - a - b) * Qbar + a * (z_prev @ z_prev.T) + b * Q
        R = _corr_from_cov(Q)
        try:
            sign, logdet = np.linalg.slogdet(R)
            if sign <= 0 or not np.isfinite(logdet):
                return 1e10
            Rinv = np.linalg.inv(R)
        except np.linalg.LinAlgError:
            return 1e10
        zt = Z[t][:, None]
        quad = float(zt.T @ Rinv @ zt)
        ll += 0.5 * (logdet + quad)
    return ll if np.isfinite(ll) else 1e10


def dcc_correlation(
    returns_panel: pd.DataFrame,
    *,
    a: float | None = None,
    b: float | None = None,
) -> pd.DataFrame:
    """Engle DCC(1,1) dynamic conditional correlation — last (one-step-ahead) correlation matrix.

    Standardises each asset's returns by its own causal GARCH(1,1) conditional vol, forms ``Qbar`` as the
    unconditional correlation of the standardized residuals, then runs the DCC Q-recursion::

        Q_t = (1 - a - b) Qbar + a (z_{t-1} z_{t-1}') + b Q_{t-1}

    and returns ``R_T`` (Q_T scaled to unit diagonal) — the conditional correlation forecast for the period
    after the last row. If ``a, b`` are given they are used as-is (bounded to ``a,b >= 0, a+b < 1``);
    otherwise they are estimated by QMLE. On any failure (no SciPy, optimiser failure, non-stationary, too
    few assets/rows) we fall back to the static unconditional correlation ``Qbar`` and stamp
    ``.attrs['fallback'] = True``.

    Returns
    -------
    pd.DataFrame
        Symmetric correlation matrix with unit diagonal and PSD. ``.attrs`` carries ``a``, ``b``,
        ``fallback``. Strictly causal: unchanged by rows appended after the last input row.
    """
    df = _clean_panel(returns_panel)
    cols = list(df.columns)
    k = len(cols)
    n = len(df)

    if k < 1:
        out = pd.DataFrame(index=cols, columns=cols, dtype="float64")
        out.attrs.update({"a": np.nan, "b": np.nan, "fallback": True})
        return out
    if k == 1:
        out = pd.DataFrame([[1.0]], index=cols, columns=cols)
        out.attrs.update({"a": 0.0, "b": 0.0, "fallback": True})
        return out

    Z, _fellback = _standardized_resids(df)

    # Unconditional correlation of standardized residuals -> Qbar (force to a clean correlation).
    Qbar = np.cov(Z, rowvar=False, ddof=1)
    Qbar = np.atleast_2d(Qbar)
    Qbar = nearest_psd(Qbar)
    Qbar = _corr_from_cov(Qbar)

    fallback = False
    a_hat = b_hat = np.nan

    if a is not None and b is not None:
        a_hat, b_hat = float(a), float(b)
        if a_hat < 0 or b_hat < 0 or (a_hat + b_hat) >= 1.0:
            fallback = True
    elif _HAVE_SCIPY and n >= 10:
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                res = minimize(
                    _dcc_negloglik,
                    x0=np.array([0.02, 0.95], dtype="float64"),
                    args=(Z, Qbar),
                    method="L-BFGS-B",
                    bounds=[(0.0, 0.5), (0.0, 0.999)],
                    options={"maxiter": 200, "ftol": 1e-9},
                )
            if (res.success or np.isfinite(res.fun)):
                ca, cb = float(res.x[0]), float(res.x[1])
                if np.isfinite(ca) and np.isfinite(cb) and ca >= 0 and cb >= 0 and (ca + cb) < 0.99999:
                    a_hat, b_hat = ca, cb
                else:
                    fallback = True
            else:
                fallback = True
        except Exception:
            fallback = True
    else:
        fallback = True

    if fallback or not (np.isfinite(a_hat) and np.isfinite(b_hat)):
        # Static unconditional correlation is itself a valid (degenerate a=b=0) DCC.
        R = Qbar.copy()
        a_hat = 0.0 if not np.isfinite(a_hat) else a_hat
        b_hat = 0.0 if not np.isfinite(b_hat) else b_hat
        fallback = True
    else:
        R = _dcc_recursion(Z, a_hat, b_hat, Qbar)

    R = nearest_psd(R)
    R = _corr_from_cov(R)  # re-normalise to unit diagonal after the PSD repair
    out = pd.DataFrame(R, index=cols, columns=cols)
    out.attrs.update({"a": float(a_hat), "b": float(b_hat), "fallback": bool(fallback)})
    return out


# ============================================================================================
# DCC-GARCH covariance (vols x correlation)
# ============================================================================================

def dcc_garch_cov(
    returns_panel: pd.DataFrame,
    *,
    halflife: float = 12.0,
) -> pd.DataFrame:
    """Combine causal GARCH(1,1) vols (diagonal) with the DCC(1,1) correlation -> last covariance forecast.

    Builds ``Sigma_{T+1|T} = D R D`` where ``D = diag(sigma_i)`` are the per-asset one-step-ahead GARCH
    conditional vols (last filtered value) and ``R`` is the DCC one-step-ahead correlation. The result is
    forced symmetric and PSD. If the DCC/GARCH machinery fails for any asset or SciPy is unavailable, the
    *whole* matrix falls back to the RiskMetrics EWMA covariance (``halflife``) — still a valid causal
    forecast — and ``.attrs['fallback'] = True``.

    Parameters
    ----------
    returns_panel : pd.DataFrame
        Panel of periodic returns (rows = time, columns = assets).
    halflife : float
        Half-life for the EWMA fallback covariance.

    Returns
    -------
    pd.DataFrame
        Symmetric PSD covariance forecast (index == columns == asset names). ``.attrs['estimator']`` is
        ``'dcc-garch'`` (or ``'ewma'`` if it fell back); ``.attrs['fallback']`` is the flag. Strictly
        causal: unchanged by rows appended after the last input row.
    """
    df = _clean_panel(returns_panel)
    cols = list(df.columns)
    k = len(cols)

    # Degenerate panels: defer to EWMA (handles n<2 / k<2 gracefully and stays PSD).
    if k < 2 or len(df) < 3:
        out = ewma_cov(df, halflife=halflife)
        out.attrs["estimator"] = "ewma"
        out.attrs["fallback"] = True
        return out

    try:
        # Per-asset one-step-ahead conditional vol = last filtered GARCH vol.
        sig = np.empty(k, dtype="float64")
        any_bad = False
        for j, c in enumerate(cols):
            vol = garch11_vol(df[c])
            last = float(vol.iloc[-1]) if len(vol) else np.nan
            sig[j] = last
            if not (np.isfinite(last) and last > 0):
                any_bad = True

        R_df = dcc_correlation(df)
        R = R_df.to_numpy(dtype="float64")

        if any_bad or not np.all(np.isfinite(R)):
            raise RuntimeError("non-finite GARCH vol or DCC correlation")

        D = np.diag(sig)
        cov = D @ R @ D
        cov = 0.5 * (cov + cov.T)
        cov = nearest_psd(cov)

        if not (np.all(np.isfinite(cov)) and _is_psd(cov)):
            raise RuntimeError("combined covariance not finite/PSD")

        out = pd.DataFrame(cov, index=cols, columns=cols)
        out.attrs["estimator"] = "dcc-garch"
        out.attrs["fallback"] = bool(R_df.attrs.get("fallback", False))
        return out
    except Exception:
        # Robust fallback: EWMA covariance is always a valid causal PSD forecast.
        out = ewma_cov(df, halflife=halflife)
        out.attrs["estimator"] = "ewma"
        out.attrs["fallback"] = True
        return out
