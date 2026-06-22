"""The co-pilot: the loop PROPOSES, a human DECIDES, and each decision feeds a durable forward stream.

This is the human-in-the-loop front-end over the Phase 7 spine. It NEVER touches the scored ``frozen``
holdout (which accrues deterministically toward the one-shot verdict) — the human's choices live in a
THIRD, strictly separate ``operator`` stream:

  frozen   — deterministic, scored holdout (the verdict's ONLY input; the human can never touch it).
  live     — deterministic auto-operate baseline (breaker-controlled); what a no-human system would do.
  operator — the co-pilot's human-in-the-loop track record (THIS module).

Each month the co-pilot computes the deterministic proposal (via ``run_loop``, which also advances the
frozen + live streams), shows it to the human with operational context, and records the human's
APPROVE / OVERRIDE / SKIP as an IMMUTABLE ``OperatorDecision``. ``paper.reconcile_operator`` then
realizes the operator stream as returns land. Nothing here can promote, score, or repaint: the operator
overlay is purely additive, so the human can build a real forward decision record alongside — but never
inside — the holdout. Promotion remains a separate, token-gated, human-issued call.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass, field
from typing import Callable, Optional

import numpy as np
import pandas as pd

from arc.autonomy.ledger import Decision, OperatorDecision, PaperLedger
from arc.autonomy.loop import run_loop
from arc.autonomy.monitor import MonitorConfig
from arc.autonomy.risk_gate import RiskLimits, pretrade_leverage_gate
from arc.autonomy.spec import FROZEN_SPEC, canonical_json, strategy_hash

VALID_ACTIONS = ("APPROVE", "OVERRIDE", "SKIP")


@dataclass(frozen=True)
class OperatorProposal:
    """What the co-pilot shows the human for one month. The human acts on THIS, and the resulting
    ``OperatorDecision`` is bound to it by ``proposal_digest``. ``frozen_position`` is informational —
    the human cannot change the scored stream; only ``operator`` (what APPROVE/OVERRIDE/SKIP sets)."""

    asof: str
    strategy: str
    strategy_hash: str
    month: str                      # the month this decision earns ("" during warm-up)
    action_suggestion: str          # OPERATE | HALT | HOLD(warmup) (from the deterministic loop)
    frozen_position: float          # deterministic scored position (informational; immutable)
    proposed_position: float        # the suggested operator position (what APPROVE would take)
    target_vol_ann: float
    leverage_for_vol_target: float
    sized_exposure: float
    circuit_halted: bool
    circuit_reasons: list = field(default_factory=list)
    drift_warnings: list = field(default_factory=list)
    n_frozen_months: int = 0
    operator_decided: bool = False  # has the human already committed for this month?
    operator_pnl: dict = field(default_factory=dict)
    proposal_digest: str = ""
    note: str = ""
    var_forecast: float = float("nan")   # sized-book monthly VaR at the applied (gated) leverage
    es_forecast: float = float("nan")    # sized-book monthly ES
    risk_gate_binding: str = ""          # which limit bound the size (vol_target/var_limit/es_limit/inactive)
    risk_gate_active: bool = False


# ----------------------------------------------------------------- helpers
def _proposal_digest(d: Decision) -> str:
    """Stable 16-hex digest of the proposal the human acted on — binds an OperatorDecision to the exact
    deterministic decision it overlays (provenance; detects acting on a stale proposal)."""
    z = d.signal_z
    body = {
        "month": d.month, "hash": d.strategy_hash,
        "frozen": round(float(d.frozen_position), 10),
        "live": round(float(d.live_position), 10),
        "z": (round(float(z), 10) if z == z else "nan"),  # (z == z) is False for NaN
    }
    return hashlib.sha256(canonical_json(body).encode("ascii")).hexdigest()[:16]


def _stream_summary(df: pd.DataFrame) -> dict:
    """Operational P&L ONLY (n, cumulative return, last position, max drawdown) — no Sharpe/DSR/IC, so
    the co-pilot's status can never become a back door to peek at a risk-adjusted forward score."""
    if df is None or len(df) == 0:
        return {"n": 0, "cum_return": float("nan"), "last_position": float("nan"),
                "max_drawdown": float("nan")}
    sret = df["sleeve_return"].astype("float64")
    eq = (1.0 + sret).cumprod()
    return {
        "n": int(len(df)),
        "cum_return": float(eq.iloc[-1] - 1.0),
        "last_position": float(df["held_position"].iloc[-1]),
        "max_drawdown": float((eq / eq.cummax() - 1.0).min()),
    }


# ----------------------------------------------------------------- propose
def _operational_context(ledger: PaperLedger, cfg: MonitorConfig, vol_target: float):
    """Circuit state + telemetry + vol-target leverage derived purely from the ledger. Used when the
    loop cannot be re-run because the latest month's decision is already LOCKED under a data revision
    (the anti-repaint guard fired) — we never repaint the holdout, we read what is already committed."""
    from arc.autonomy.monitor import circuit_breaker
    from arc.autonomy.paper import forward_telemetry
    circuit = circuit_breaker(ledger.live_frame(), cfg)
    tel = forward_telemetry(ledger)
    live_vol = tel.live_ann_vol
    leverage = (float(vol_target / live_vol)
                if (live_vol and not np.isnan(live_vol) and live_vol > 0) else float("nan"))
    return circuit, tel, leverage


def propose(
    asof,
    returns_provider: Callable[[pd.Timestamp], pd.Series],
    ledger: PaperLedger,
    *,
    spec: dict = FROZEN_SPEC,
    signal_provider: Optional[Callable[[pd.Timestamp], pd.Series]] = None,
    vol_target: float = 0.10,
    cfg: Optional[MonitorConfig] = None,
    reference_z: Optional[pd.Series] = None,
    risk_limits: Optional[RiskLimits] = None,
    strategy: str = "",
    run_id: str = "copilot-propose",
) -> OperatorProposal:
    """Advance the deterministic loop to ``asof`` and return the human-facing proposal for the latest
    decidable month. Advancing the loop accrues the frozen + live streams (the holdout grows whether or
    not the human acts — that is the design); the human only influences the SEPARATE operator stream,
    via ``decide``. Idempotent on identical data. ``risk_limits`` (optional) turns on the live pre-trade
    VaR/ES gate that caps the proposed sized exposure to the loss budget (operational only).

    Revision-robust: if the latest forward month is ALREADY recorded and live data has since revised,
    the anti-repaint guard (``DataRevisionError``) fires — that is correct (a booked holdout decision is
    immutable). We catch it, keep the recorded decision untouched, and build the proposal from it plus a
    fresh operational context, surfacing a loud warning. The holdout is never repainted."""
    from arc.autonomy.ledger import DataRevisionError

    cfg = cfg or MonitorConfig()
    out = None
    warnings: list[str] = []
    try:
        out = run_loop(asof, returns_provider, ledger, spec=spec, cfg=cfg, vol_target=vol_target,
                       signal_provider=signal_provider, reference_z=reference_z, risk_limits=risk_limits,
                       run_id=run_id)
    except DataRevisionError as exc:
        warnings.append(f"DATA REVISED since the recorded decision -- holdout is LOCKED, not repainted ({exc})")

    h = strategy_hash(spec)
    decs = ledger.decisions()

    if not decs:  # still warming up — no decision recorded yet (only reachable on the success path)
        prop = out["proposal"] if out else {}
        return OperatorProposal(
            asof=str(pd.Timestamp(asof).date()), strategy=strategy, strategy_hash=h, month="",
            action_suggestion="HOLD(warmup)", frozen_position=float("nan"),
            proposed_position=float("nan"), target_vol_ann=float(vol_target),
            leverage_for_vol_target=float("nan"), sized_exposure=float("nan"),
            circuit_halted=bool(prop.get("circuit_halted", False)),
            circuit_reasons=list(prop.get("circuit_reasons", [])),
            drift_warnings=list(prop.get("drift_warnings", [])) + warnings,
            n_frozen_months=int(prop.get("n_forward_months", 0)),
            operator_decided=False, operator_pnl=_stream_summary(ledger.operator_frame()),
            note="Warming up: not enough history to form a position yet.")

    month = max(decs)            # the latest decidable month
    d = decs[month]
    proposed = float(d.live_position)   # the deterministic suggestion (0.0 if the breaker halted at tick)

    if out is not None:
        prop = out["proposal"]
        action_suggestion = str(prop["action"])
        leverage = float(prop["leverage_for_vol_target"])
        sized = float(prop["sized_exposure"])
        halted = bool(prop["circuit_halted"])
        reasons = list(prop["circuit_reasons"])
        drift = list(prop["drift_warnings"])
        n_frozen = int(prop["n_forward_months"])
        var_fc = float(prop.get("var_forecast", float("nan")))
        es_fc = float(prop.get("es_forecast", float("nan")))
        gate_binding = str(prop.get("risk_gate_binding", ""))
        gate_active = bool(prop.get("risk_gate_active", False))
    else:  # revision fallback — build from the locked decision + a fresh operational context
        circuit, tel, leverage = _operational_context(ledger, cfg, vol_target)
        var_fc, es_fc, gate_binding, gate_active = float("nan"), float("nan"), "", False
        if risk_limits is not None:  # re-apply the live gate on the locked decision (operational only)
            fz = ledger.frozen_frame()
            rr = (fz["sleeve_return"] if "sleeve_return" in getattr(fz, "columns", [])
                  else pd.Series(dtype="float64"))
            gstate = pretrade_leverage_gate(rr, requested_leverage=leverage, limits=risk_limits)
            leverage = gstate.applied_leverage
            var_fc, es_fc = gstate.var_at_applied, gstate.es_at_applied
            gate_binding, gate_active = gstate.binding, bool(gstate.active)
        halted = bool(circuit.halted)
        reasons = list(circuit.reasons)
        action_suggestion = "HALT" if halted else "OPERATE"
        sized = float(proposed * leverage) if (leverage == leverage) else float("nan")
        drift = []
        n_frozen = int(tel.n_frozen)

    return OperatorProposal(
        asof=str(pd.Timestamp(asof).date()), strategy=strategy, strategy_hash=h, month=month,
        action_suggestion=action_suggestion, frozen_position=float(d.frozen_position),
        proposed_position=proposed, target_vol_ann=float(vol_target),
        leverage_for_vol_target=leverage, sized_exposure=sized, circuit_halted=halted,
        circuit_reasons=reasons, drift_warnings=drift + warnings, n_frozen_months=n_frozen,
        operator_decided=(month in ledger.operator_decisions()),
        operator_pnl=_stream_summary(ledger.operator_frame()),
        proposal_digest=_proposal_digest(d),
        note="Proposal only — APPROVE/OVERRIDE/SKIP feeds the operator stream; the frozen holdout is "
             "untouchable and accrues deterministically toward the one-shot verdict.",
        var_forecast=float(var_fc) if var_fc == var_fc else float("nan"),
        es_forecast=float(es_fc) if es_fc == es_fc else float("nan"),
        risk_gate_binding=gate_binding, risk_gate_active=gate_active)


# ----------------------------------------------------------------- decide
def decide(
    ledger: PaperLedger,
    *,
    spec: dict = FROZEN_SPEC,
    month: str,
    action: str,
    rationale: str,
    decided_by: str,
    position: Optional[float] = None,
    max_abs_position: float = 5.0,
    decided_at: str = "",
    run_id: str = "copilot-decide",
) -> OperatorDecision:
    """Commit the human's operating decision for ``month`` (the operator stream). The deterministic
    decision for that month MUST already exist (run ``propose`` first). ``action``:

      APPROVE  -> take the loop's proposed (live) position.
      SKIP     -> stay flat (operator position 0.0).
      OVERRIDE -> take ``position`` (finite; |position| <= ``max_abs_position`` fat-finger guard).

    The result is IMMUTABLE per ``(month, hash)`` — a different later choice raises ``RepaintError``
    (you cannot repaint your own forward track record). NEVER touches the frozen/live streams."""
    act = str(action).upper()
    if act not in VALID_ACTIONS:
        raise ValueError(f"action must be one of {VALID_ACTIONS}, got {action!r}")
    h = strategy_hash(spec)
    decs = ledger.decisions()
    if month not in decs:
        raise ValueError(
            f"no deterministic decision recorded for {month}; run propose/advance the loop first")
    d = decs[month]
    if d.strategy_hash != h:
        raise ValueError(f"decision {month} is for hash {d.strategy_hash[:8]}, not {h[:8]}")

    proposed = float(d.live_position)
    if act == "APPROVE":
        op = proposed
    elif act == "SKIP":
        op = 0.0
    else:  # OVERRIDE
        if position is None:
            raise ValueError("OVERRIDE requires an explicit position")
        op = float(position)
        if not math.isfinite(op):
            raise ValueError("override position must be finite")
        if abs(op) > float(max_abs_position):
            raise ValueError(f"override |{op}| exceeds max_abs_position={max_abs_position} (fat-finger guard)")

    od = OperatorDecision(
        month=month, strategy_hash=h, action=act, proposed_position=proposed, operator_position=float(op),
        rationale=str(rationale), decided_by=str(decided_by), proposal_digest=_proposal_digest(d),
        run_id=run_id, decided_at=str(decided_at))
    ledger.append_operator_decision(od)  # idempotent / immutable inside
    return od


# ----------------------------------------------------------------- status
def copilot_status(ledger: PaperLedger, *, strategy: str = "") -> dict:
    """Operational snapshot of all three streams (no scores). The verdict is reached only via
    ``monitor.promotion_verdict`` on the frozen stream — never from here."""
    ops = ledger.operator_decisions()
    last_action = ""
    if ops:
        last_action = ops[max(ops)].action
    return {
        "strategy": strategy,
        "strategy_hash": (ops[max(ops)].strategy_hash if ops else ""),
        "n_operator_decisions": len(ops),
        "last_operator_action": last_action,
        "frozen": _stream_summary(ledger.frozen_frame()),
        "live": _stream_summary(ledger.live_frame()),
        "operator": _stream_summary(ledger.operator_frame()),
    }


__all__ = ["OperatorProposal", "propose", "decide", "copilot_status", "VALID_ACTIONS"]
