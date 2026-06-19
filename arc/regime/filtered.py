"""Filtered (causal) HMM posteriors — fixes audit finding regime-1.

hmmlearn's ``predict_proba`` returns the *smoothed* posterior gamma_t(i) = P(s_t = i | o_1..o_T):
the forward-backward pass conditions every month's regime on the ENTIRE sequence, including months
*after* t. When that probability is stored as the regime feature at month t and fed to a model
that trains on history, it is a look-ahead — the regime label at t peeks at t+1..T.

The causal object is the *filtered* posterior:

    alpha_hat_t(i) = P(s_t = i | o_1..o_t)

i.e. conditioned only on observations up to and including t. This module computes it from a fitted
hmmlearn model via the log-domain forward recursion, with an emission-density fallback so it does
not depend on a single private hmmlearn API name across versions.

The defining property (verified in tests): ``filtered_posteriors(X[:k]) == filtered_posteriors(X)[:k]``
for every k — the past is invariant to the future. The smoothed posterior does NOT satisfy this.
"""

from __future__ import annotations

import numpy as np
from scipy.special import logsumexp


def _emission_log_prob(model, X: np.ndarray) -> np.ndarray:
    """Per-frame emission log-likelihood, shape (T, K).

    Prefers hmmlearn's internal hook (name has changed across versions), and falls back to an
    explicit full-covariance Gaussian density built from the fitted ``means_``/``covars_`` so the
    function works regardless of the installed hmmlearn version.
    """
    X = np.asarray(X, dtype="float64")
    for name in ("_compute_log_likelihood", "_compute_log_prob"):
        fn = getattr(model, name, None)
        if fn is None:
            continue
        try:
            fl = np.asarray(fn(X), dtype="float64")
            if fl.ndim == 2 and fl.shape[0] == X.shape[0] and np.isfinite(fl).any():
                return fl
        except Exception:
            pass
    # Fallback: Gaussian emissions from fitted parameters.
    from scipy.stats import multivariate_normal

    means = np.asarray(model.means_, dtype="float64")
    covars = np.asarray(model.covars_, dtype="float64")
    K, d = means.shape
    fl = np.empty((X.shape[0], K), dtype="float64")
    for k in range(K):
        cov = covars[k]
        if cov.ndim == 1:
            cov = np.diag(cov)
        elif cov.ndim == 0:
            cov = np.eye(d) * float(cov)
        cov = cov + 1e-9 * np.eye(d)
        fl[:, k] = multivariate_normal.logpdf(X, mean=means[k], cov=cov, allow_singular=True)
    return fl


def filtered_posteriors(model, X) -> np.ndarray:
    """Filtered posteriors P(s_t | o_1..o_t) for a fitted hmmlearn model. Returns (T, K), rows
    summing to 1.

    Log forward recursion:
        log a_0(j) = log pi_j + log b_j(o_0)
        log a_t(j) = logsumexp_i( log a_{t-1}(i) + log A_ij ) + log b_j(o_t)
        filtered_t = softmax_j( log a_t(j) )
    """
    X = np.asarray(X, dtype="float64")
    if X.ndim == 1:
        X = X.reshape(-1, 1)
    T = X.shape[0]
    if T == 0:
        return np.empty((0, int(getattr(model, "n_components", 0))), dtype="float64")

    framelogprob = _emission_log_prob(model, X)
    K = framelogprob.shape[1]
    log_start = np.log(np.clip(np.asarray(model.startprob_, dtype="float64"), 1e-300, None))
    log_trans = np.log(np.clip(np.asarray(model.transmat_, dtype="float64"), 1e-300, None))

    log_alpha = np.empty((T, K), dtype="float64")
    log_alpha[0] = log_start + framelogprob[0]
    for t in range(1, T):
        # work[i, j] = log_alpha[t-1, i] + log_trans[i, j]
        work = log_alpha[t - 1][:, None] + log_trans
        log_alpha[t] = logsumexp(work, axis=0) + framelogprob[t]

    return np.exp(log_alpha - logsumexp(log_alpha, axis=1, keepdims=True))
