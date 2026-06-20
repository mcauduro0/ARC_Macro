"""The paper loop: tick (record a decision), reconcile (record realized outcomes), and token-free
operational telemetry (Phase 7).

This is the bridge from "validated edge" to a system that operates, persists, and accumulates the
reserved single-use holdout. It is PURE (pandas/numpy + arc.research/arc.autonomy only) so it runs in
CI without the engine; the engine slice and its publication-lag boundary live in ``scripts/paper_loop.py``.

Equivalence guarantee (CI gate): accumulating one decision per month and reconciling each rebuilds a
sleeve return stream byte-equal to ``arc.research.momentum_sleeve_returns`` on the same data. That kills
the off-by-one and any recompute drift. The expanding z-score in ``causal_position`` is prefix-stable,
so a decision's position is computed ONCE and never recomputed — reconcile multiplies the *stored*
position by the realized return.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd

from arc.autonomy.ledger import (
    Decision,
    PaperLedger,
    Realization,
    UnbookedTrialError,
)
from arc.autonomy.spec import FROZEN_SPEC, canonical_json, strategy_hash
from arc.research.sleeve import causal_position, momentum_signal


# ----------------------------------------------------------------- month helpers
def month_end(ts) -> pd.Timestamp:
    return pd.Timestamp(ts) + pd.offsets.MonthEnd(0)


def next_month_end(ts) -> pd.Timestamp:
    return pd.Timestamp(ts) + pd.offsets.MonthEnd(1)


def prev_month_end(ts) -> pd.Timestamp:
    return month_end(ts) - pd.offsets.MonthEnd(1)


def _iso(ts) -> str:
    return pd.Timestamp(ts).strftime("%Y-%m-%d")


def _digest(series: pd.Series) -> str:
    """Stable digest of an as-of return slice — lets a re-tick detect a data revision."""
    body = {"idx": [_iso(i) for i in series.index], "val": [float(v) for v in series.values]}
    return hashlib.sha256(canonical_json(body).encode("ascii")).hexdigest()[:16]


def turnover_cost(held: float, prev_held: float, cost_bps: float) -> float:
    """Matches ``sleeve.momentum_sleeve_returns`` exactly: |held - prev_held| * bps/1e4."""
    return abs(float(held) - float(prev_held)) * (float(cost_bps) / 10000.0)


# ----------------------------------------------------------------- tick
def tick(
    asof,
    returns_through_K: pd.Series,
    ledger: PaperLedger,
    *,
    spec: dict = FROZEN_SPEC,
    run_id: str = "tick",
    halted: bool = False,
    forward_start: Optional[object] = None,
) -> Optional[Decision]:
    """Record the decision for the month AFTER the latest known return month.

    ``returns_through_K`` MUST be the caller's as-of slice (knowledge_time <= asof) — the only
    look-ahead boundary, owned by the caller. The position is ``causal_position(...).iloc[-1]`` (formed
    at the end of month K), keyed to the month it earns (K+1). Returns None during warm-up. Idempotent:
    a second tick for the same month is a no-op; a revised input raises ``DataRevisionError``.
    ``halted`` (from the breaker) zeroes only the LIVE position; the frozen position is untouched.
    ``forward_start`` is the holdout cutoff: a decision whose earned month is <= it is IN-SAMPLE and is
    NOT recorded (returns None) — so in-sample history never leaks into the forward holdout ledger. The
    full as-of history is still used to COMPUTE the position (the expanding window is legitimate)."""
    h = strategy_hash(spec)
    if h not in ledger.booked_hashes():
        raise UnbookedTrialError(
            f"strategy {h[:8]} has no booked governance trial; book a trial + deflation basis before ticking")

    r = pd.Series(returns_through_K).dropna()
    if len(r) < int(spec["z_window"]):
        return None  # not enough history to form an expanding z-score

    sig = momentum_signal(r, int(spec["lookback"]))
    pos = causal_position(sig, z_window=int(spec["z_window"]), clip_z=float(spec["clip_z"]))
    decision_pos = pos.iloc[-1]
    if pd.isna(decision_pos):
        return None  # still warming up (lookback + z_window not jointly satisfied)

    # pre-clip z, for drift monitoring
    mu = sig.expanding(min_periods=int(spec["z_window"])).mean()
    sd = sig.expanding(min_periods=int(spec["z_window"])).std()
    z = (sig - mu) / sd.replace(0.0, np.nan)

    K = month_end(r.index[-1])
    target = next_month_end(K)
    # target is BY CONSTRUCTION the month after the latest known return, so the decision never uses the
    # month it earns. The real publication-lag boundary (a month-M return is invisible until M+lag) is
    # owned by the caller's as-of provider — arc.autonomy.source.monthly_return_provider, CI-tested.
    assert target > K, f"internal: target {target} must be after latest return {K}"
    if forward_start is not None and target <= month_end(forward_start):
        return None  # in-sample month — used to compute the position, but NOT recorded as holdout

    frozen_pos = float(decision_pos)
    d = Decision(
        month=_iso(target),
        strategy_hash=h,
        frozen_position=frozen_pos,
        live_position=0.0 if halted else frozen_pos,
        signal=float(sig.iloc[-1]),
        signal_z=float(z.iloc[-1]) if not pd.isna(z.iloc[-1]) else float("nan"),
        data_max_knowledge_time=_iso(K),
        input_digest=_digest(r),
        run_id=run_id,
        created_at=_iso(asof),
    )
    ledger.append_decision(d)  # idempotent / revision-checked inside
    return d


# ----------------------------------------------------------------- reconcile
def reconcile(
    asof,
    realized_returns: pd.Series,
    ledger: PaperLedger,
    *,
    spec: dict = FROZEN_SPEC,
    run_id: str = "reconcile",
    settlement_lag: pd.Timedelta = pd.Timedelta(0),
) -> list[Realization]:
    """Append realized outcomes for decided-but-unreconciled months whose return is FINAL.

    Finality is gated on ``asof - month_end(month) >= settlement_lag`` (a still-provisional return is
    not baked in). For each month it uses the STORED decision position (never recomputed — the expanding
    z-score is non-idempotent under later early-vintage revisions) and the prior STORED decision for
    turnover, reproducing ``sleeve`` exactly. Writes BOTH a ``frozen`` (scored) and a ``live`` (operated)
    realization. Idempotent per ``(month, stream)``."""
    r = pd.Series(realized_returns).dropna()
    r.index = [month_end(i) for i in r.index]
    decs = ledger.decisions()
    done = ledger.realizations("frozen")
    out: list[Realization] = []

    for month_iso in sorted(decs):
        if month_iso in done:
            continue  # already reconciled (idempotent)
        m = pd.Timestamp(month_iso)
        if m not in r.index:
            continue  # return not yet known
        if (month_end(asof) - month_end(m)) < settlement_lag:
            continue  # not yet final — don't bake in a provisional return
        prev_iso = _iso(prev_month_end(m))
        if prev_iso not in decs:
            continue  # boundary first month (no prior position) — dropped, matching sleeve's dropna
        d = decs[month_iso]
        prev = decs[prev_iso]
        realized = float(r.loc[m])

        for stream, held, prev_held in (
            ("frozen", d.frozen_position, prev.frozen_position),
            ("live", d.live_position, prev.live_position),
        ):
            sret = held * realized - turnover_cost(held, prev_held, float(spec["cost_bps"]))
            rec = Realization(
                month=month_iso,
                strategy_hash=d.strategy_hash,
                stream=stream,
                held_position=float(held),
                prev_held=float(prev_held),
                realized_return=realized,
                sleeve_return=float(sret),
                realized_knowledge_time=_iso(asof),
                return_vintage_seq=0,
                reconciled_at=_iso(asof),
                run_id=run_id,
            )
            if ledger.append_realization(rec) and stream == "frozen":
                out.append(rec)
    return out


# ----------------------------------------------------------------- telemetry (token-free, NO scores)
@dataclass(frozen=True)
class ForwardTelemetry:
    """Operational state ONLY — no forward Sharpe/DSR/IC. Scoring is reachable solely through
    ``monitor.promotion_verdict`` (which consumes the single-use holdout). Counts and live-stream risk
    are operational; ``signal_z`` feeds the (non-binding) drift detector."""

    n_frozen: int
    n_live: int
    last_frozen_position: float
    last_live_position: float
    live_max_drawdown: float
    live_ann_vol: float
    signal_z: pd.Series


def forward_telemetry(ledger: PaperLedger) -> ForwardTelemetry:
    fz = ledger.frozen_frame()
    lv = ledger.live_frame()
    if len(lv):
        eq = (1.0 + lv["sleeve_return"]).cumprod()
        live_dd = float((eq / eq.cummax() - 1.0).min())
        live_vol = float(lv["sleeve_return"].std(ddof=1) * np.sqrt(12)) if len(lv) > 1 else float("nan")
    else:
        live_dd, live_vol = float("nan"), float("nan")
    return ForwardTelemetry(
        n_frozen=int(len(fz)),
        n_live=int(len(lv)),
        last_frozen_position=float(fz["held_position"].iloc[-1]) if len(fz) else float("nan"),
        last_live_position=float(lv["held_position"].iloc[-1]) if len(lv) else float("nan"),
        live_max_drawdown=live_dd,
        live_ann_vol=live_vol,
        signal_z=(fz["signal_z"] if "signal_z" in fz.columns else pd.Series(dtype="float64")),
    )


__all__ = [
    "tick", "reconcile", "forward_telemetry", "ForwardTelemetry", "turnover_cost",
    "month_end", "next_month_end", "prev_month_end",
]
