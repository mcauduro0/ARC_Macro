"""Phase 5 — meta-labeling (López de Prado), causal & leakage-safe.

Meta-labeling sits ON TOP of a primary signal. The primary model decides the SIDE of the bet
(long/short); the meta-model only predicts *whether that bet will be right* and is used to SIZE it
(a confidence in (0,1] feeding ``arc.intelligence.sizing``), never to flip the side and never as a
standalone alpha. This is measured infrastructure, not an edge claim: the project's ruler still says
there is no demonstrated alpha beyond carry, and whether sizing by P(correct) actually improves a
candidate's deflated out-of-sample risk-adjusted return is decided by the measurement script and the
forward holdout — never asserted here.

Strict point-in-time discipline (these functions get adversarial as-of tests):
- ``meta_labels`` is a pure, row-local target: 1.0 if the primary bet's sign matched the realized
  forward return, 0.0 if it was wrong, NaN if the position is zero/NaN or the return is NaN.
- ``meta_label_proba`` is a CAUSAL expanding-window classifier: the probability emitted at time t is
  produced by a model FIT ONLY on rows with index < t (features and labels both present), standardized
  on that train slice alone. No row with index >= t can influence the prediction at t. An expanding
  refit *cadence* (refit every K rows) is allowed purely for speed, but the model used to predict t is
  always one fit on a prefix strictly before t.

Pure module: pandas/numpy (+ optional sklearn). No network, no engine import, deterministic.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

try:  # sklearn is available in this project; guard anyway so the module stays pure/importable.
    from sklearn.linear_model import LogisticRegression  # type: ignore

    _HAS_SKLEARN = True
except Exception:  # pragma: no cover - exercised only when sklearn is absent
    _HAS_SKLEARN = False


__all__ = ["meta_labels", "meta_label_proba"]


def meta_labels(primary_position: pd.Series, fwd_returns: pd.Series) -> pd.Series:
    """López de Prado meta-labeling target: was the primary bet right?

    Returns 1.0 where ``sign(primary_position[t]) == sign(fwd_returns[t])`` (the primary side was
    correct), 0.0 where the sides disagree (the primary bet was wrong), and NaN where the label is
    undefined: either input NaN, or ``primary_position == 0`` (no bet was placed). A zero forward
    return counts as the bet being wrong (sign 0 != sign of a non-zero position), which is the
    conservative choice for "did this directional bet make money".

    Row-local and causal by construction (uses only the aligned values at t).
    """
    pos = pd.Series(primary_position, dtype="float64")
    ret = pd.Series(fwd_returns, dtype="float64").reindex(pos.index)

    out = pd.Series(np.nan, index=pos.index, dtype="float64")
    defined = pos.notna() & ret.notna() & (pos != 0.0)
    if defined.any():
        correct = np.sign(pos[defined].to_numpy()) == np.sign(ret[defined].to_numpy())
        out.loc[defined] = correct.astype("float64")
    return out


def _fit_predict_logistic(
    x_train: np.ndarray,
    y_train: np.ndarray,
    x_pred: np.ndarray,
    *,
    l2: float,
) -> float:
    """Standardize on the TRAIN slice only, fit logistic, return P(label=1) for one row.

    Falls back to a small numpy IRLS logistic regression (with L2) if sklearn is unavailable.
    Degenerate-train guards (single class / no usable rows) return that class's degenerate prob.
    """
    mu = x_train.mean(axis=0)
    sd = x_train.std(axis=0)
    sd = np.where(sd < 1e-12, 1.0, sd)  # constant feature -> no scaling, contributes nothing
    xs = (x_train - mu) / sd
    xp = (x_pred - mu) / sd

    classes = np.unique(y_train)
    if classes.size < 2:  # only one class observed -> emit that class's probability
        return float(classes[0]) if classes.size == 1 else 0.5

    if _HAS_SKLEARN:
        clf = LogisticRegression(C=1.0 / float(l2), solver="lbfgs", max_iter=1000)
        clf.fit(xs, y_train)
        # column index of the positive class (label == 1.0)
        pos_idx = int(np.where(clf.classes_ == 1.0)[0][0])
        return float(clf.predict_proba(xp.reshape(1, -1))[0, pos_idx])

    return _irls_logistic_predict(xs, y_train, xp, l2=l2)  # pragma: no cover - sklearn present here


def _irls_logistic_predict(
    xs: np.ndarray, y: np.ndarray, xp: np.ndarray, *, l2: float, max_iter: int = 100
) -> float:  # pragma: no cover - only used when sklearn is missing
    """L2-penalized logistic regression via Newton/IRLS; returns P(y=1) for ``xp``.

    Mirrors sklearn's convention: penalize the slope coefficients (C = 1/l2), not the intercept.
    """
    n, d = xs.shape
    xb = np.hstack([np.ones((n, 1)), xs])  # design with intercept column 0
    w = np.zeros(d + 1)
    reg = np.full(d + 1, float(l2))
    reg[0] = 0.0  # do not penalize the intercept
    for _ in range(max_iter):
        eta = xb @ w
        p = 1.0 / (1.0 + np.exp(-np.clip(eta, -35, 35)))
        wgt = np.clip(p * (1.0 - p), 1e-9, None)
        grad = xb.T @ (p - y) + reg * w
        h = xb.T @ (xb * wgt[:, None]) + np.diag(reg)
        try:
            step = np.linalg.solve(h, grad)
        except np.linalg.LinAlgError:
            step = np.linalg.lstsq(h, grad, rcond=None)[0]
        w_new = w - step
        if np.max(np.abs(w_new - w)) < 1e-8:
            w = w_new
            break
        w = w_new
    eta_p = float(np.r_[1.0, xp] @ w)
    return float(1.0 / (1.0 + np.exp(-np.clip(eta_p, -35, 35))))


def meta_label_proba(
    features: pd.DataFrame,
    labels: pd.Series,
    *,
    min_train: int = 36,
    l2: float = 1.0,
    refit_every: int = 1,
) -> pd.Series:
    """Causal expanding-window meta-classifier: P(primary signal is right) for sizing.

    At each evaluated row t, FIT a logistic classifier on every row with index STRICTLY < t for which
    both the features and the label are present, requiring at least ``min_train`` such labeled rows,
    standardize on that train slice only, and PREDICT P(label == 1) for ``features.loc[t]``. No row at
    index >= t ever enters the fit, so the value at an interior t is invariant to whatever later data
    exists — the leakage-safety property the tests assert.

    Speed: an expanding refit *cadence* is supported via ``refit_every`` (refit the coefficients only
    every K eligible rows, reusing them for the rows in between). This NEVER breaks causality because a
    cached model was fit on a prefix strictly before every row that uses it; ``refit_every=1`` refits
    each step. Rows whose features are NaN, or that occur before ``min_train`` labeled history exists,
    are NaN in the output. Output is aligned to ``features.index``.

    The probability is a confidence to feed ``arc.intelligence.sizing`` (size the primary bet), not a
    side and not a standalone signal.
    """
    if not isinstance(features, pd.DataFrame):
        features = pd.DataFrame(features)
    idx = features.index
    y = pd.Series(labels, dtype="float64").reindex(idx)

    feat_ok = features.notna().all(axis=1)          # all feature columns present at this row
    label_ok = y.notna()                            # label observed (so usable for TRAINING)
    train_ok = (feat_ok & label_ok).to_numpy()      # row is eligible as a TRAIN example
    feat_vals = features.to_numpy(dtype="float64")
    y_vals = y.to_numpy(dtype="float64")

    refit_every = max(1, int(refit_every))
    out = np.full(len(idx), np.nan, dtype="float64")

    cached = None              # (mu, sd, coef-bundle) is re-derived inside _fit_predict each refit
    last_fit_count = -1        # number of train rows the cached model was fit on
    for t in range(len(idx)):
        if not feat_ok.iat[t]:
            continue  # cannot predict a row with missing features
        train_mask = train_ok[:t]  # STRICTLY before t -> the causal prefix
        n_train = int(train_mask.sum())
        if n_train < min_train:
            continue
        # Refit cadence: refit when we've never fit, or enough new train rows have accrued.
        need_refit = cached is None or (n_train - last_fit_count) >= refit_every
        if need_refit:
            sel = np.flatnonzero(train_mask)
            x_train = feat_vals[sel]
            y_train = y_vals[sel]
            cached = (x_train, y_train)
            last_fit_count = n_train
        x_train, y_train = cached
        out[t] = _fit_predict_logistic(x_train, y_train, feat_vals[t], l2=l2)

    return pd.Series(out, index=idx, dtype="float64")
