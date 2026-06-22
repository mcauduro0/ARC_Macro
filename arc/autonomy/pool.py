"""The POOLED forward holdout (Phase 7.4 / track-a): an equal-weight panel of the three booked sleeves,
pre-registered to reach a verdict in fewer forward calendar months than any single sleeve.

Why this exists: the single-sleeve forward verdict is bound by forward calendar months — no amount of
in-sample or macro history accelerates it. The ONLY honest accelerator is cross-sectional breadth. The
three booked sleeves are nearly independent (measured K_eff ~2.92 of 3), so an equal-weight pooled stream
carries the same t-content in ~24/K_eff months. We pre-commit a pooled ``eval_at_n`` from that (stable)
correlation breadth and score the pool forward, deflated for the cumulative trial count.

Discipline (identical to ``monitor.promotion_verdict``): one-shot, fail-closed (consumption recorded
BEFORE scoring), pre-committed sample size (no optional stopping), NaN-fatal, deterministic-on-read. The
pooled stream is the equal-weight average of the members' FROZEN (scored, unbreakered) sleeve returns on
their COMMON forward months only — no in-sample weight tuning, so no extra deflation from fitting. This is
NOT a claim of edge: pooling pays off only if several members carry real, similarly-signed edge; if one is
noise it dilutes. The forward holdout remains the sole judge.
"""

from __future__ import annotations

from dataclasses import asdict

import numpy as np
import pandas as pd

from arc.autonomy.governance import book_trial
from arc.autonomy.ledger import (
    HoldoutConsumedError,
    HoldoutConsumedRecord,
    HoldoutNotReadyError,
    MissingDeflationBasisError,
    PaperLedger,
    VerdictRecord,
)
from arc.autonomy.spec import POOL_HASH, POOL_SPEC
from arc.eval.gate import sharpe_stats
from arc.eval.governance import HoldoutToken


def pooled_forward_returns(member_frozen_frames: dict) -> pd.Series:
    """Equal-weight average of the members' frozen sleeve returns on the months ALL members share.

    A month is a pooled observation only if EVERY member has a realized forward return for it (inner
    join) — so the pooled n is the common-support count, never an optimistic union. No weights are tuned
    in-sample (equal weight is fixed in ``POOL_SPEC``)."""
    cols = {}
    for name, fz in member_frozen_frames.items():
        if fz is None or len(fz) == 0:
            return pd.Series(dtype="float64")
        cols[name] = pd.Series(fz["sleeve_return"]).astype("float64")
    panel = pd.DataFrame(cols).dropna()
    if len(panel) == 0:
        return pd.Series(dtype="float64")
    return panel.mean(axis=1)


def book_pool(
    pool_ledger: PaperLedger,
    *,
    n_trials: int,
    eval_at_n: int,
    dsr_min: float,
    forward_start: str,
    issued_by: str,
    sr_std=None,
) -> str:
    """Human pre-registration of the pool: book the trial + freeze the immutable deflation basis on the
    pool's OWN ledger. ``eval_at_n`` (< 24 by design) is allowed via ``min_forward_n=eval_at_n`` — the
    pooled breadth is what justifies the shorter sample, and it is committed here before any forward
    data. Idempotent (re-booking keeps the original frozen basis)."""
    return book_trial(pool_ledger, spec=POOL_SPEC, n_trials=int(n_trials), sr_std=sr_std,
                      eval_at_n=int(eval_at_n), dsr_min=float(dsr_min), forward_start=forward_start,
                      issued_by=issued_by, min_forward_n=int(eval_at_n))


def issue_pool_token(*, issued_by: str) -> HoldoutToken:
    """Mint the single-use capability bound to the pool hash. The ledger is the durable lock."""
    return HoldoutToken(strategy_hash=POOL_HASH, issued_by=issued_by)


def pooled_verdict(
    pool_ledger: PaperLedger,
    member_frozen_frames: dict,
    token,
    *,
    asof,
    run_id: str = "pool-verdict",
) -> dict:
    """Score the POOLED forward holdout exactly once, fail-closed, against the pre-committed bar.

    Mirrors ``monitor.promotion_verdict`` but the scored stream is the equal-weight pooled stream built
    from the members' frozen frames. Order: deterministic-on-read if already consumed; token must bind to
    the pool hash; a persisted basis is mandatory; the pooled common-support n must equal the pre-committed
    ``eval_at_n`` (no optional stopping); consumption is recorded BEFORE scoring; PASS iff DSR >= dsr_min
    and Sharpe > 0 (NaN-fatal)."""
    h = POOL_HASH

    if h in pool_ledger.consumed_hashes():
        prior = pool_ledger.verdict_for(h)
        if prior is not None:
            return asdict(prior)
        raise HoldoutConsumedError(
            f"pool holdout {h[:8]} was consumed but no verdict was rendered (prior crash); it is spent")

    if getattr(token, "strategy_hash", None) != h:
        raise ValueError("holdout token is not bound to the pool hash")

    basis = pool_ledger.basis_for(h)
    if basis is None:
        raise MissingDeflationBasisError(
            f"no deflation basis for pool {h[:8]}; a human must book (n_trials, eval_at_n, dsr_min)")

    pooled = pooled_forward_returns(member_frozen_frames)
    n = int(len(pooled))
    if n < basis.eval_at_n:
        raise HoldoutNotReadyError(
            f"pooled holdout has {n} common forward months; pre-committed eval_at_n={basis.eval_at_n}")
    if n > basis.eval_at_n:
        raise HoldoutNotReadyError(
            f"pooled holdout overshot ({n} > eval_at_n={basis.eval_at_n}); the pre-committed evaluation "
            f"point was missed — re-book with an explicit new schedule rather than choosing when to look")

    pool_ledger.append_consumed(HoldoutConsumedRecord(
        strategy_hash=h, token_id=str(getattr(token, "issued_by", "")), eval_at_n=basis.eval_at_n,
        consumed_at=str(asof), run_id=run_id))
    try:
        token.consume(h)
    except Exception:  # noqa: BLE001 — durable lock already set; in-memory flag is secondary
        pass

    s = sharpe_stats(pooled.values, n_trials=basis.n_trials, sr_std=basis.sr_std)
    dsr, sr_ann = s["dsr"], s["sr_annual"]
    # Degenerate-fatal: a NaN OR a near-zero-variance stream (an absurd, non-finite Sharpe from numerical
    # noise) FAILS — a "too perfect" forward stream is a red flag, never a pass.
    sd = float(np.std(pooled.values, ddof=1)) if n > 1 else 0.0
    degenerate = (dsr != dsr) or (sr_ann != sr_ann) or (not np.isfinite(sr_ann)) or (sd <= 1e-9)
    ok_dsr = (dsr == dsr) and dsr >= basis.dsr_min
    ok_sr = (sr_ann == sr_ann) and np.isfinite(sr_ann) and sr_ann > 0
    passed = bool(ok_dsr and ok_sr and not degenerate)
    if degenerate:
        reason = "FAIL: degenerate pooled sample (near-zero variance or NaN DSR/Sharpe)"
    elif passed:
        reason = (f"PASS: pooled forward DSR {dsr:.3f} >= {basis.dsr_min} and Sharpe {sr_ann:.2f} > 0 "
                  f"over {n} common months")
    else:
        reason = (f"FAIL: pooled forward DSR {dsr:.3f} (bar {basis.dsr_min}), Sharpe {sr_ann:.2f} over "
                  f"{n} common months")

    v = VerdictRecord(
        strategy_hash=h, passed=passed, reason=reason,
        dsr=float(dsr) if dsr == dsr else float("nan"),
        sr_annual=float(sr_ann) if sr_ann == sr_ann else float("nan"),
        n=n, dsr_min=basis.dsr_min, n_trials=basis.n_trials, sr_std=float(s["sr_std"]),
        rendered_at=str(asof), run_id=run_id)
    pool_ledger.append_verdict(v)
    return asdict(v)


__all__ = ["pooled_forward_returns", "book_pool", "issue_pool_token", "pooled_verdict",
           "POOL_SPEC", "POOL_HASH"]
