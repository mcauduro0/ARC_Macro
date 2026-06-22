"""Phase 5 (deferred item) — causal ONLINE / adaptive FEATURE selection (point-in-time, leakage-safe).

WHAT THIS IS (and is NOT):
    The engine does BATCH feature selection: it fits on the FULL sample and freezes the chosen feature set.
    That is convenient but it (a) cannot adapt as a regime turns a feature on/off and (b) is a subtle source
    of look-ahead if the "chosen" set is ever used to score the very rows that chose it. This module supplies
    the CAUSAL alternative: at every time ``t`` it re-derives a feature importance / selection set using ONLY
    rows strictly before ``t`` (a trailing or expanding train window), so the selected set at ``t`` is
    tradable at ``t`` without leakage and ADAPTS through time.

    It is NOT an alpha claim and NOT a forecast of profit. Whether online (rolling) selection actually beats
    batch (full-sample) selection — on a deflated, carry-neutral ruler — is an EMPIRICAL question answered
    downstream by ``scripts/measure_online_selection.py`` (the honest, likely-marginal/null verdict), never
    asserted here. The project's honesty law stands: no demonstrated alpha beyond carry.

CAUSALITY (non-negotiable — these get adversarial as-of tests):
    The importance/frequency ROW at time ``t`` is fit on the train slice ``{rows : index < t}`` (optionally
    only the trailing ``window`` of them), with the standardization (mean/std) ALSO estimated on that train
    slice only. No row with index >= t ever enters the fit for time ``t``. Consequently, appending later
    rows never changes an earlier output row (as-of-invariance). No centered windows, no full-sample fit, no
    peeking at the row being scored. Rows before ``min_train`` strictly-past complete observations are NaN.

API (consumed by scripts/measure_online_selection.py):
    rolling_elasticnet_importance(features, target, *, window=60, min_train=36, l1_ratio=0.5, refit_every=1)
        -> pd.DataFrame   # |standardized coef| per feature, aligned to t (strictly causal)
    rolling_stability_selection(features, target, *, window=60, min_train=36, n_bootstrap=50, threshold=0.6,
        seed=0) -> pd.DataFrame   # bootstrap SELECTION FREQUENCY per feature, aligned to t (causal)
    online_selected_mask(importance_or_freq, *, top_k=None, threshold=None) -> pd.DataFrame[bool]

Each importance/frequency function returns a DataFrame aligned to ``features`` (same index & columns); rows
before enough strictly-past history are all-NaN. ``online_selected_mask`` turns either matrix into a per-t
boolean selected set (top-k by row and/or threshold), preserving the NaN (undecided) rows as all-False with
the option to keep them undecided.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

__all__ = [
    "rolling_elasticnet_importance",
    "rolling_stability_selection",
    "online_selected_mask",
]

# sklearn is the preferred backend; a numpy fallback keeps the module importable/usable without it (the
# measurement script and tests run with sklearn present, but the contract must not hard-depend on it).
try:  # pragma: no cover - exercised indirectly
    from sklearn.linear_model import ElasticNet, ElasticNetCV, Lasso  # type: ignore

    _HAVE_SKLEARN = True
except Exception:  # pragma: no cover - fallback path
    _HAVE_SKLEARN = False


# --------------------------------------------------------------------------------------
# train-slice helpers (all standardization happens on the TRAIN slice only -> causal)
# --------------------------------------------------------------------------------------
def _standardize_train(X: np.ndarray, y: np.ndarray):
    """Standardize a train slice IN-SAMPLE (mean/std from the slice itself) -> (Xs, ys, x_mu, x_sd, keep).

    Columns with zero (or non-finite) train std are CONSTANT on this slice: they carry no information for a
    standardized linear fit, so we flag them ``keep=False`` and zero them out (their coefficient is forced
    to 0 / unselected for this ``t``). ``y`` is centered (intercept handled implicitly); its scale is left
    as-is because we only ever look at the RELATIVE magnitude of coefficients within a row."""
    x_mu = X.mean(axis=0)
    x_sd = X.std(axis=0, ddof=0)
    keep = np.isfinite(x_sd) & (x_sd > 1e-12)
    safe_sd = np.where(keep, x_sd, 1.0)
    Xs = (X - x_mu) / safe_sd
    Xs[:, ~keep] = 0.0
    ys = y - y.mean()
    return Xs, ys, x_mu, safe_sd, keep


def _coef_elasticnet(Xs: np.ndarray, ys: np.ndarray, *, l1_ratio: float, use_cv: bool) -> np.ndarray:
    """|coef| from a standardized ElasticNet fit on (Xs, ys). sklearn if available, numpy coord-descent else.

    Returns the absolute standardized coefficient vector (length = n_features). On any solver failure or a
    degenerate slice it returns all-zeros (nothing selected this row), never raises."""
    n, p = Xs.shape
    if n < 3 or p == 0 or not np.isfinite(Xs).all() or not np.isfinite(ys).all():
        return np.zeros(p, dtype="float64")

    if _HAVE_SKLEARN:
        try:
            if use_cv and n >= 10:
                # CV picks alpha from the train slice ONLY (causal); small n_alphas keeps it cheap & stable.
                model = ElasticNetCV(
                    l1_ratio=l1_ratio if l1_ratio > 0 else 0.01,
                    n_alphas=20, cv=3, max_iter=5000, fit_intercept=False, random_state=0,
                )
            else:
                model = ElasticNet(
                    alpha=0.01, l1_ratio=l1_ratio if l1_ratio > 0 else 0.01,
                    max_iter=5000, fit_intercept=False,
                )
            model.fit(Xs, ys)
            coef = np.asarray(model.coef_, dtype="float64").ravel()
            if coef.shape[0] != p or not np.isfinite(coef).all():
                return np.zeros(p, dtype="float64")
            return np.abs(coef)
        except Exception:  # pragma: no cover - solver hiccup
            return np.zeros(p, dtype="float64")

    # numpy fallback: elastic-net coordinate descent on standardized data (fixed alpha).
    return np.abs(_coord_descent_enet(Xs, ys, alpha=0.01, l1_ratio=l1_ratio))


def _coord_descent_enet(
    Xs: np.ndarray, ys: np.ndarray, *, alpha: float, l1_ratio: float, max_iter: int = 500, tol: float = 1e-6,
) -> np.ndarray:
    """Plain elastic-net coordinate descent (no intercept; inputs already standardized/centered).

    Minimizes (1/2n)||y - Xb||^2 + alpha*l1_ratio*||b||_1 + 0.5*alpha*(1-l1_ratio)*||b||^2 — the standard
    sklearn ElasticNet objective. Used only when sklearn is unavailable; deterministic, no randomness."""
    n, p = Xs.shape
    b = np.zeros(p, dtype="float64")
    l1 = alpha * l1_ratio
    l2 = alpha * (1.0 - l1_ratio)
    col_sq = (Xs ** 2).sum(axis=0) / n  # == 1 for standardized cols, 0 for the zeroed constants
    r = ys - Xs @ b
    for _ in range(max_iter):
        max_step = 0.0
        for j in range(p):
            if col_sq[j] <= 0.0:
                continue
            rho = (Xs[:, j] @ (r + Xs[:, j] * b[j])) / n  # partial residual correlation
            # soft-threshold / elastic-net coordinate update
            new_bj = np.sign(rho) * max(abs(rho) - l1, 0.0) / (col_sq[j] + l2)
            if new_bj != b[j]:
                r += Xs[:, j] * (b[j] - new_bj)
                max_step = max(max_step, abs(new_bj - b[j]))
                b[j] = new_bj
        if max_step < tol:
            break
    return b


def _lasso_support(Xs: np.ndarray, ys: np.ndarray, *, alpha: float) -> np.ndarray:
    """Boolean support (|coef| > 0) of a Lasso fit on a (bootstrap) standardized slice.

    sklearn Lasso if present, else the numpy elastic-net with l1_ratio=1 (pure L1). Returns a length-p bool
    vector; all-False on any failure/degenerate slice (selects nothing for that bootstrap)."""
    n, p = Xs.shape
    if n < 3 or p == 0 or not np.isfinite(Xs).all() or not np.isfinite(ys).all():
        return np.zeros(p, dtype=bool)
    if _HAVE_SKLEARN:
        try:
            model = Lasso(alpha=alpha, max_iter=5000, fit_intercept=False)
            model.fit(Xs, ys)
            coef = np.asarray(model.coef_, dtype="float64").ravel()
            if coef.shape[0] != p or not np.isfinite(coef).all():
                return np.zeros(p, dtype=bool)
            return np.abs(coef) > 1e-10
        except Exception:  # pragma: no cover
            return np.zeros(p, dtype=bool)
    coef = _coord_descent_enet(Xs, ys, alpha=alpha, l1_ratio=1.0)
    return np.abs(coef) > 1e-10


def _aligned_train_slice(
    Xf: np.ndarray, yf: np.ndarray, present: np.ndarray, i: int, *, window: int, min_train: int,
):
    """Collect the strictly-past, complete (X & y finite) rows for prediction time ``i``.

    Returns ``(Xtr, ytr)`` or ``None`` if fewer than ``min_train`` such rows exist. Only rows with index
    ``< i`` are eligible (STRICT), optionally limited to the most recent ``window`` of them. ``present`` is
    the precomputed boolean "row i has finite y and at least one finite X" mask used only to bound work."""
    lo = 0 if window is None else max(0, i - window)
    # Strictly-past candidate rows [lo, i): require finite target AND a fully-finite feature row.
    rows = []
    for s in range(i - 1, lo - 1, -1):  # walk back from i-1 so the trailing `window` is the most recent rows
        if not present[s]:
            continue
        if np.isfinite(yf[s]) and np.isfinite(Xf[s]).all():
            rows.append(s)
        if window is not None and len(rows) >= window:
            break
    if len(rows) < min_train:
        return None
    rows = np.array(sorted(rows), dtype=int)
    return Xf[rows], yf[rows]


# --------------------------------------------------------------------------------------
# rolling ElasticNet importance (causal)
# --------------------------------------------------------------------------------------
def rolling_elasticnet_importance(
    features: pd.DataFrame,
    target: pd.Series,
    *,
    window: int = 60,
    min_train: int = 36,
    l1_ratio: float = 0.5,
    refit_every: int = 1,
) -> pd.DataFrame:
    """Causal rolling ElasticNet feature importance: |standardized coef| per feature, aligned to ``t``.

    At every row ``t`` with at least ``min_train`` strictly-past complete observations, fit an ElasticNet
    (``ElasticNetCV`` when the slice is large enough, else a fixed-alpha ``ElasticNet``) on the TRAILING
    ``window`` of rows with index ``< t``. Features and target are standardized USING THAT TRAIN SLICE ONLY
    (mean/std from rows ``< t``), so no information from row ``t`` or later enters the fit. The row recorded
    at ``t`` is the vector of ``|coef|`` (absolute standardized coefficients) — a larger value means the
    feature carried more weight in predicting the (already-causal) target over the recent past.

    Strict causality: row ``t`` depends only on rows with index ``< t``; appending later rows leaves every
    earlier row unchanged (as-of-invariance — asserted adversarially in the tests).

    Parameters
    ----------
    features : pd.DataFrame
        Causal feature panel (one column per feature), index sorted ascending. NaN feature cells make that
        row ineligible as a TRAIN row (a fully-finite feature row is required to train on it).
    target : pd.Series
        Causal target aligned to ``features`` (e.g. a FORWARD return aligned to the decision date). The last
        rows are typically NaN (their future is unknown) and are simply never used as train rows.
    window : int or None
        Trailing train-window length (rows). ``None`` => expanding (all strictly-past complete rows).
    min_train : int
        Minimum strictly-past complete observations before an importance row is produced; earlier rows NaN.
    l1_ratio : float
        ElasticNet mixing (1.0 = Lasso, 0.0 -> ridge; clamped to a tiny positive for the L1/L2 blend).
    refit_every : int
        Refit cadence: refit the model every ``refit_every`` rows and CARRY FORWARD the most recent fitted
        importances on the in-between rows (still causal — a carried row only reuses a fit from rows < t).
        ``1`` = refit every row.

    Returns
    -------
    pd.DataFrame
        Same index & columns as ``features``; ``|coef|`` per feature. Rows before ``min_train`` strictly-past
        complete observations (and any row where the fit is degenerate) are all-NaN.
    """
    if window is not None and window <= 0:
        raise ValueError(f"window must be > 0 or None, got {window}")
    if min_train < 2:
        raise ValueError(f"min_train must be >= 2, got {min_train}")
    if refit_every < 1:
        raise ValueError(f"refit_every must be >= 1, got {refit_every}")
    l1_ratio = float(np.clip(l1_ratio, 0.0, 1.0))

    feats = features.astype("float64")
    y = pd.Series(target, dtype="float64").reindex(feats.index)
    cols = list(feats.columns)
    Xf = feats.to_numpy()
    yf = y.to_numpy()
    n, p = Xf.shape

    present = np.array([np.isfinite(yf[s]) and np.isfinite(Xf[s]).any() for s in range(n)])
    out = np.full((n, p), np.nan, dtype="float64")

    last_imp = None
    rows_since_fit = refit_every  # force a fit on the first eligible row
    for i in range(n):
        sl = _aligned_train_slice(Xf, yf, present, i, window=window, min_train=min_train)
        if sl is None:
            last_imp = None
            rows_since_fit = refit_every
            continue
        if rows_since_fit >= refit_every or last_imp is None:
            Xtr, ytr = sl
            Xs, ys, _mu, _sd, keep = _standardize_train(Xtr, ytr)
            imp = _coef_elasticnet(Xs, ys, l1_ratio=l1_ratio, use_cv=True)
            imp = np.where(keep, imp, 0.0)  # constant-on-train columns -> 0 importance
            last_imp = imp
            rows_since_fit = 1
        else:
            rows_since_fit += 1
        out[i, :] = last_imp

    return pd.DataFrame(out, index=feats.index, columns=cols)


# --------------------------------------------------------------------------------------
# rolling stability selection (causal)
# --------------------------------------------------------------------------------------
def rolling_stability_selection(
    features: pd.DataFrame,
    target: pd.Series,
    *,
    window: int = 60,
    min_train: int = 36,
    n_bootstrap: int = 50,
    threshold: float = 0.6,
    seed: int = 0,
) -> pd.DataFrame:
    """Causal rolling STABILITY SELECTION: bootstrap selection FREQUENCY per feature, aligned to ``t``.

    Stability selection (Meinshausen & Buhlmann): a feature is trustworthy if it is selected by a sparse
    model across MANY resamples of the data, not just one lucky fit. Here, causally: at every row ``t`` with
    enough strictly-past complete rows, take the trailing ``window`` train slice (index ``< t``), and for
    ``n_bootstrap`` bootstrap resamples of THAT slice, standardize on the resample and fit a Lasso; the
    recorded value for feature ``c`` at ``t`` is the FRACTION of bootstraps in which ``c`` had a non-zero
    coefficient. A frequency near 1 means "selected almost every resample" (stable); near 0 means "noise".

    The Lasso penalty ``alpha`` is set per-slice from the data scale (``alpha = lambda * std(y)`` with a
    fixed ``lambda``), estimated on the TRAIN slice only, so the whole row is strictly causal: row ``t`` uses
    only rows with index ``< t``; appending later rows leaves earlier rows unchanged. The RNG is seeded
    deterministically per row (``seed`` combined with ``t``'s position) so results are fully reproducible.

    Parameters
    ----------
    features, target : as in :func:`rolling_elasticnet_importance`.
    window : int or None
        Trailing train-window length; ``None`` => expanding.
    min_train : int
        Minimum strictly-past complete observations before a frequency row is produced.
    n_bootstrap : int
        Number of bootstrap resamples per row.
    threshold : float
        Convenience attribute stored on the result (``.attrs['threshold']``) for a downstream selection cut;
        the returned matrix is the raw FREQUENCY (apply the cut via :func:`online_selected_mask`).
    seed : int
        Base RNG seed (combined with each row position for per-row reproducibility).

    Returns
    -------
    pd.DataFrame
        Same index & columns as ``features``; selection frequency in [0, 1] per feature. Rows before
        ``min_train`` strictly-past complete observations are all-NaN. ``.attrs['threshold']`` carries the
        suggested cut.
    """
    if window is not None and window <= 0:
        raise ValueError(f"window must be > 0 or None, got {window}")
    if min_train < 2:
        raise ValueError(f"min_train must be >= 2, got {min_train}")
    if n_bootstrap < 1:
        raise ValueError(f"n_bootstrap must be >= 1, got {n_bootstrap}")
    if not (0.0 <= threshold <= 1.0):
        raise ValueError(f"threshold must be in [0, 1], got {threshold}")

    feats = features.astype("float64")
    y = pd.Series(target, dtype="float64").reindex(feats.index)
    cols = list(feats.columns)
    Xf = feats.to_numpy()
    yf = y.to_numpy()
    n, p = Xf.shape

    present = np.array([np.isfinite(yf[s]) and np.isfinite(Xf[s]).any() for s in range(n)])
    out = np.full((n, p), np.nan, dtype="float64")

    LAMBDA = 0.1  # Lasso strength relative to target scale (fixed; only the per-slice y-scale is data-driven)
    for i in range(n):
        sl = _aligned_train_slice(Xf, yf, present, i, window=window, min_train=min_train)
        if sl is None:
            continue
        Xtr, ytr = sl
        m = Xtr.shape[0]
        # Per-row deterministic RNG: same row position -> same bootstraps, regardless of later data.
        rng = np.random.default_rng(int(seed) * 1_000_003 + i)
        y_scale = float(np.std(ytr, ddof=0))
        alpha = LAMBDA * (y_scale if np.isfinite(y_scale) and y_scale > 0 else 1.0)

        sel_counts = np.zeros(p, dtype="float64")
        for _b in range(n_bootstrap):
            idx = rng.integers(0, m, size=m)  # bootstrap rows of the TRAIN slice (with replacement)
            Xb, yb = Xtr[idx], ytr[idx]
            Xs, ys, _mu, _sd, keep = _standardize_train(Xb, yb)
            sup = _lasso_support(Xs, ys, alpha=alpha)
            sup = sup & keep  # a constant-on-resample column is never "selected"
            sel_counts += sup.astype("float64")
        out[i, :] = sel_counts / float(n_bootstrap)

    res = pd.DataFrame(out, index=feats.index, columns=cols)
    res.attrs["threshold"] = float(threshold)
    return res


# --------------------------------------------------------------------------------------
# per-t selected mask
# --------------------------------------------------------------------------------------
def online_selected_mask(
    importance_or_freq: pd.DataFrame,
    *,
    top_k: int | None = None,
    threshold: float | None = None,
) -> pd.DataFrame:
    """Turn a per-t importance/frequency matrix into a per-t boolean SELECTED set.

    For each defined row (a row with at least one finite value) a feature is selected when it satisfies the
    requested rule(s):
      * ``threshold`` : value > threshold (e.g. stability frequency > 0.6, or |coef| > some cut);
      * ``top_k``     : among the finite values in the row, the ``top_k`` LARGEST (ties broken by column
                        order — pandas ``nlargest`` semantics) are selected.
    If BOTH are given, a feature must satisfy BOTH (top-k AND above threshold) — the conservative AND. If
    NEITHER is given, the default rule is "value > 0" (any strictly-positive importance/frequency is in).

    Rows that are all-NaN in the input (undecided — before ``min_train``) are returned all-False (no
    selection is defined there). The result has the same index & columns as the input and dtype ``bool``.

    Parameters
    ----------
    importance_or_freq : pd.DataFrame
        Output of :func:`rolling_elasticnet_importance` or :func:`rolling_stability_selection` (or any
        per-t score matrix), aligned index & columns.
    top_k : int or None
        Keep at most this many top-scoring features per row. ``None`` => no count cap.
    threshold : float or None
        Keep features strictly above this score per row. ``None`` => no threshold (uses ``> 0`` if ``top_k``
        is also None).

    Returns
    -------
    pd.DataFrame[bool]
        Same index & columns; True where selected. All-NaN input rows -> all-False output rows.
    """
    if top_k is not None and top_k < 0:
        raise ValueError(f"top_k must be >= 0 or None, got {top_k}")

    df = importance_or_freq
    vals = df.to_numpy(dtype="float64")
    n, p = vals.shape
    mask = np.zeros((n, p), dtype=bool)

    use_default = (top_k is None) and (threshold is None)
    for i in range(n):
        row = vals[i, :]
        finite = np.isfinite(row)
        if not finite.any():
            continue  # undecided row -> all-False

        sel = finite.copy()
        if use_default:
            sel = finite & (row > 0.0)
        else:
            if threshold is not None:
                sel = sel & (row > threshold)
            if top_k is not None:
                k = min(top_k, int(finite.sum()))
                if k <= 0:
                    sel = np.zeros(p, dtype=bool)
                else:
                    # indices of the k largest FINITE values (descending; stable by column order on ties).
                    order = np.argsort(np.where(finite, -row, np.inf), kind="stable")
                    topk_idx = order[:k]
                    topk_mask = np.zeros(p, dtype=bool)
                    topk_mask[topk_idx] = True
                    sel = sel & topk_mask
        mask[i, :] = sel

    return pd.DataFrame(mask, index=df.index, columns=df.columns)
