"""Monitoring, feedback and the single scored path (Phase 7).

Three tiers, deliberately separated so the operating machinery can never corrupt the holdout:
- ``detect_drift`` / ``signal_psi`` — operational warnings, NON-BINDING on any promotion decision.
- ``circuit_breaker`` — reads the LIVE stream only, returns state, never mutates a record. The caller
  applies a halt to FUTURE live positions; the frozen (scored) stream is untouched.
- ``promotion_verdict`` — the ONLY function that scores the forward holdout. It reads the frozen stream
  only, consumes a durable single-use lock BEFORE scoring (fail-closed), reproduces the gate's exact
  deflation from a persisted basis, evaluates at a pre-committed sample size, is NaN-fatal, and is
  deterministic-on-read (a second call returns the recorded verdict).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

import numpy as np
import pandas as pd

from arc.autonomy.ledger import (
    HoldoutConsumedError,
    HoldoutConsumedRecord,
    HoldoutNotReadyError,
    MissingDeflationBasisError,
    PaperLedger,
    VerdictRecord,
)
from arc.autonomy.spec import FROZEN_SPEC, strategy_hash
from arc.eval.gate import sharpe_stats


@dataclass
class MonitorConfig:
    """Operational thresholds (breaker + drift). These affect the LIVE stream only — never the verdict."""

    dd_halt: float = -0.03          # halt live trading if live drawdown breaches this
    neg_sharpe_months: int = 6      # window for the rolling-Sharpe halt
    psi_warn: float = 0.20          # signal-distribution drift warning level


@dataclass
class CircuitState:
    halted: bool
    reasons: list[str] = field(default_factory=list)
    live_drawdown: float = float("nan")
    rolling_sharpe: float = float("nan")


# ----------------------------------------------------------------- drift (non-binding)
def signal_psi(reference_z: pd.Series, forward_z: pd.Series, bins: int = 10) -> float:
    """Population Stability Index of the forward signal distribution vs a frozen reference. Operational
    drift only; never feeds the verdict. The reference should be an immutable, hashed research artifact."""
    ref = pd.Series(reference_z).dropna().values
    fwd = pd.Series(forward_z).dropna().values
    if len(ref) < bins or len(fwd) == 0:
        return float("nan")
    edges = np.quantile(ref, np.linspace(0, 1, bins + 1))
    edges[0], edges[-1] = -np.inf, np.inf
    eps = 1e-6
    pr = np.histogram(ref, bins=edges)[0] / len(ref) + eps
    pf = np.histogram(fwd, bins=edges)[0] / len(fwd) + eps
    return float(np.sum((pf - pr) * np.log(pf / pr)))


def detect_drift(telemetry, cfg: MonitorConfig, reference_z: pd.Series | None = None) -> dict:
    """Operational warnings only (explicitly non-binding on the promotion verdict)."""
    warnings: list[str] = []
    psi = float("nan")
    if reference_z is not None and len(getattr(telemetry, "signal_z", [])):
        psi = signal_psi(reference_z, telemetry.signal_z)
        if not np.isnan(psi) and psi > cfg.psi_warn:
            warnings.append(f"signal PSI {psi:.3f} > {cfg.psi_warn} (distribution drift)")
    if not np.isnan(telemetry.live_max_drawdown) and telemetry.live_max_drawdown <= cfg.dd_halt:
        warnings.append(f"live drawdown {telemetry.live_max_drawdown:.3f} <= {cfg.dd_halt}")
    return {"psi": psi, "warnings": warnings, "binding": False}


# ----------------------------------------------------------------- circuit breaker (live only)
def circuit_breaker(live_frame: pd.DataFrame, cfg: MonitorConfig) -> CircuitState:
    """Reads the LIVE frame only; returns state; mutates nothing. The caller flattens FUTURE live
    positions when halted — the frozen stream (and thus the verdict) is never affected."""
    if live_frame is None or len(live_frame) == 0:
        return CircuitState(halted=False)
    r = live_frame["sleeve_return"].astype("float64")
    eq = (1.0 + r).cumprod()
    dd = float((eq / eq.cummax() - 1.0).min())
    reasons: list[str] = []
    halted = False
    if dd <= cfg.dd_halt:
        halted = True
        reasons.append(f"live drawdown {dd:.3f} <= {cfg.dd_halt}")
    roll_sr = float("nan")
    if len(r) >= cfg.neg_sharpe_months:
        window = r.iloc[-cfg.neg_sharpe_months:]
        sd = window.std(ddof=1)
        if sd > 0:
            roll_sr = float(window.mean() / sd)
            if roll_sr < 0:
                halted = True
                reasons.append(f"rolling Sharpe {roll_sr:.2f} < 0 over last {cfg.neg_sharpe_months}m")
    return CircuitState(halted=halted, reasons=reasons, live_drawdown=dd, rolling_sharpe=roll_sr)


# ----------------------------------------------------------------- promotion verdict (the ONLY scored path)
def promotion_verdict(ledger: PaperLedger, token, *, asof, spec: dict = FROZEN_SPEC, run_id: str = "verdict") -> dict:
    """Score the forward holdout — exactly once, fail-closed, against the pre-committed bar.

    Order (fail-closed): if already consumed, return the RECORDED verdict (deterministic read); else
    require a persisted DeflationBasis, require the pre-committed sample size, durably record consumption
    BEFORE scoring, then score the FROZEN stream with the gate's exact ``(n_trials, sr_std)`` deflation.
    PASS iff ``dsr >= dsr_min`` and ``sr_annual > 0`` (both non-NaN). The IC-vs-carry-neutral-bar
    criterion is intentionally DROPPED: this is a single-instrument sleeve with no forward carry panel,
    and comparing a raw forward IC to a carry-neutral bar would be systematically optimistic."""
    h = strategy_hash(spec)

    # 1. Deterministic-on-read / fail-closed single-use (durable, ledger-anchored — not the in-memory token).
    if h in ledger.consumed_hashes():
        prior = ledger.verdict_for(h)
        if prior is not None:
            return asdict(prior)
        raise HoldoutConsumedError(
            f"holdout {h[:8]} was consumed but no verdict was rendered (prior crash); it is spent")

    # 2. Token must be a valid capability bound to this exact frozen spec.
    if getattr(token, "strategy_hash", None) != h:
        raise ValueError("holdout token is not bound to the frozen strategy hash")

    # 3. Pre-committed, immutable deflation basis is mandatory — never default to a weak bar.
    basis = ledger.basis_for(h)
    if basis is None:
        raise MissingDeflationBasisError(
            f"no deflation basis for {h[:8]}; a human must book (n_trials, sr_std, eval_at_n, dsr_min)")

    # 4. Pre-committed sample size — no optional stopping (evaluate at exactly eval_at_n months).
    fz = ledger.frozen_frame()
    n = int(len(fz))
    if n < basis.eval_at_n:
        raise HoldoutNotReadyError(f"forward holdout has {n} months; pre-committed eval_at_n={basis.eval_at_n}")
    if n > basis.eval_at_n:
        raise HoldoutNotReadyError(
            f"forward holdout overshot ({n} > eval_at_n={basis.eval_at_n}); the pre-committed evaluation "
            f"point was missed — re-book with an explicit new schedule rather than choosing when to look")

    # 5. Durably record consumption BEFORE any score is computed (crash => spent, never re-peekable).
    ledger.append_consumed(HoldoutConsumedRecord(
        strategy_hash=h, token_id=str(getattr(token, "issued_by", "")), eval_at_n=basis.eval_at_n,
        consumed_at=str(asof), run_id=run_id))
    try:
        token.consume(h)  # in-memory capability check (mismatch/reuse raises); ledger is the real lock
    except Exception:  # noqa: BLE001 — durable lock already set; the in-memory flag is secondary
        pass

    # 6. Score the FROZEN stream with the gate's EXACT deflation (sr_std from the persisted basis —
    #    sleeve_stats cannot pass sr_std, so we call sharpe_stats directly).
    s = sharpe_stats(fz["sleeve_return"].values, n_trials=basis.n_trials, sr_std=basis.sr_std)
    dsr, sr_ann = s["dsr"], s["sr_annual"]

    # 7. Degenerate-fatal criterion: a NaN OR a near-zero-variance forward stream (which yields an absurd,
    #    non-finite Sharpe from numerical noise) FAILS. A "too perfect" forward stream is a red flag, not a
    #    pass. (x == x) is False for NaN.
    sd = float(np.std(fz["sleeve_return"].values, ddof=1)) if n > 1 else 0.0
    degenerate = (dsr != dsr) or (sr_ann != sr_ann) or (not np.isfinite(sr_ann)) or (sd <= 1e-9)
    ok_dsr = (dsr == dsr) and dsr >= basis.dsr_min
    ok_sr = (sr_ann == sr_ann) and np.isfinite(sr_ann) and sr_ann > 0
    passed = bool(ok_dsr and ok_sr and not degenerate)
    if degenerate:
        reason = "FAIL: degenerate forward sample (near-zero variance or NaN DSR/Sharpe)"
    elif passed:
        reason = f"PASS: forward DSR {dsr:.3f} >= {basis.dsr_min} and Sharpe {sr_ann:.2f} > 0 over {n} months"
    else:
        reason = f"FAIL: forward DSR {dsr:.3f} (bar {basis.dsr_min}), Sharpe {sr_ann:.2f} over {n} months"

    v = VerdictRecord(
        strategy_hash=h, passed=passed, reason=reason,
        dsr=float(dsr) if dsr == dsr else float("nan"),
        sr_annual=float(sr_ann) if sr_ann == sr_ann else float("nan"),
        n=n, dsr_min=basis.dsr_min, n_trials=basis.n_trials,
        sr_std=float(s["sr_std"]),  # the EFFECTIVE SE used (Lo-2002 auto resolves to a concrete value)
        rendered_at=str(asof), run_id=run_id)
    ledger.append_verdict(v)
    return asdict(v)


__all__ = [
    "MonitorConfig", "CircuitState", "signal_psi", "detect_drift", "circuit_breaker",
    "promotion_verdict",
]
