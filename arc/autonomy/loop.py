"""The deterministic Research -> Signal -> Risk -> Portfolio loop (Phase 7).

This is the autonomy skeleton: an ordered pipeline of composable "skills" over a shared context that,
each invocation, reconciles realized months, runs the circuit breaker on the LIVE stream, records the
new month's decision (frozen + live), and emits a human-approval Proposal. It NEVER promotes or sizes
up autonomously and NEVER scores the holdout — the promotion verdict is a separate, human-gated,
token-bearing call (``monitor.promotion_verdict``).

Determinism: same ledger state + same asof + same returns => same Proposal. Each skill is a clean seam
where a Claude-driven agent can later replace the deterministic implementation without rewiring — a
research agent proposes a new hypothesis (which must go through booking, never mutating the frozen
window); a signal agent swaps the generator behind a NEW hash; a risk agent affects only the live
stream; a portfolio agent shapes the proposal.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Callable, Optional, Protocol

import numpy as np
import pandas as pd

from arc.autonomy.ledger import Decision, PaperLedger, RunManifest
from arc.autonomy.monitor import CircuitState, MonitorConfig, circuit_breaker, detect_drift
from arc.autonomy.paper import ForwardTelemetry, forward_telemetry, reconcile, tick
from arc.autonomy.spec import FROZEN_SPEC, strategy_hash


@dataclass
class LoopContext:
    """The bus passed between skills. Skills read/populate fields; ``run_loop`` assembles the Proposal."""

    asof: pd.Timestamp
    ledger: PaperLedger
    spec: dict
    cfg: MonitorConfig
    vol_target: float
    run_id: str
    returns: Optional[pd.Series] = None
    signal: Optional[pd.Series] = None   # external oriented signal (None => momentum from returns)
    circuit: Optional[CircuitState] = None
    decision: Optional[Decision] = None
    telemetry: Optional[ForwardTelemetry] = None
    drift: dict = field(default_factory=dict)
    forward_start: Optional[str] = None  # holdout cutoff, read from the deflation basis
    logs: list[str] = field(default_factory=list)


class Skill(Protocol):
    name: str

    def run(self, ctx: LoopContext) -> LoopContext: ...


class ResearchSkill:
    """Pull the causal as-of return slice (and external signal, if any) and freeze the spec.
    (Agent seam: hypothesis proposal.)"""

    name = "research"

    def __init__(self, returns_provider: Callable[[pd.Timestamp], pd.Series],
                 signal_provider: Optional[Callable[[pd.Timestamp], pd.Series]] = None):
        self.returns_provider = returns_provider
        self.signal_provider = signal_provider

    def run(self, ctx: LoopContext) -> LoopContext:
        ctx.returns = pd.Series(self.returns_provider(ctx.asof)).dropna()
        if self.signal_provider is not None:
            ctx.signal = pd.Series(self.signal_provider(ctx.asof))
        ctx.logs.append(f"research: {len(ctx.returns)} return months as-of {ctx.asof.date()}"
                        + ("" if ctx.signal is None else f"; signal n={len(ctx.signal.dropna())}"))
        return ctx


class RiskSkill:
    """Reconcile finalized months, then run the breaker on the LIVE stream. (Agent seam: risk policy.)"""

    name = "risk"

    def run(self, ctx: LoopContext) -> LoopContext:
        recs = reconcile(ctx.asof, ctx.returns, ctx.ledger, spec=ctx.spec, run_id=ctx.run_id)
        ctx.circuit = circuit_breaker(ctx.ledger.live_frame(), ctx.cfg)
        ctx.logs.append(f"risk: reconciled {len(recs)} month(s); halted={ctx.circuit.halted}")
        return ctx


class SignalSkill:
    """Record the new month's decision (frozen always; live zeroed if halted). (Agent seam: generator.)"""

    name = "signal"

    def run(self, ctx: LoopContext) -> LoopContext:
        halted = bool(ctx.circuit.halted) if ctx.circuit else False
        ctx.decision = tick(ctx.asof, ctx.returns, ctx.ledger, spec=ctx.spec, run_id=ctx.run_id,
                            halted=halted, forward_start=ctx.forward_start, signal_through_K=ctx.signal)
        ctx.logs.append(
            f"signal: decision={'none(warmup)' if ctx.decision is None else round(ctx.decision.frozen_position, 3)}")
        return ctx


class PortfolioSkill:
    """Size by vol target from live-stream risk and assemble telemetry/drift. (Agent seam: allocation.)"""

    name = "portfolio"

    def __init__(self, reference_z: pd.Series | None = None):
        self.reference_z = reference_z

    def run(self, ctx: LoopContext) -> LoopContext:
        ctx.telemetry = forward_telemetry(ctx.ledger)
        ctx.drift = detect_drift(ctx.telemetry, ctx.cfg, self.reference_z)
        return ctx


@dataclass(frozen=True)
class Proposal:
    """The human-approval artifact. The loop proposes; a human approves. No auto-promotion, no scoring."""

    asof: str
    strategy_hash: str
    action: str                     # "OPERATE" | "HALT" | "HOLD(warmup)"
    frozen_position: float
    live_position: float
    target_vol_ann: float
    leverage_for_vol_target: float
    sized_exposure: float
    circuit_halted: bool
    circuit_reasons: list
    drift_warnings: list
    n_forward_months: int
    human_approval_required: bool
    note: str


def run_loop(
    asof,
    returns_provider: Callable[[pd.Timestamp], pd.Series],
    ledger: PaperLedger,
    *,
    spec: dict = FROZEN_SPEC,
    cfg: MonitorConfig = MonitorConfig(),
    vol_target: float = 0.10,
    reference_z: pd.Series | None = None,
    signal_provider: Optional[Callable[[pd.Timestamp], pd.Series]] = None,
    run_id: str = "loop",
    code_version: str = "",
) -> dict:
    """Run one deterministic loop tick and emit a Proposal (does NOT score the holdout). ``signal_provider``
    supplies an external oriented point-in-time signal for non-momentum strategies (e.g. the nowcast); when
    omitted the strategy is price momentum computed from the returns."""
    asof = pd.Timestamp(asof)
    basis = ledger.basis_for(strategy_hash(spec))
    ctx = LoopContext(asof=asof, ledger=ledger, spec=spec, cfg=cfg, vol_target=vol_target, run_id=run_id,
                      forward_start=(basis.forward_start if basis else None))
    skills: list[Skill] = [ResearchSkill(returns_provider, signal_provider), RiskSkill(), SignalSkill(),
                           PortfolioSkill(reference_z)]
    for sk in skills:
        ctx = sk.run(ctx)

    tel = ctx.telemetry
    halted = bool(ctx.circuit.halted) if ctx.circuit else False
    live_vol = tel.live_ann_vol if tel else float("nan")
    leverage = float(vol_target / live_vol) if (live_vol and not np.isnan(live_vol) and live_vol > 0) else float("nan")
    if ctx.decision is None:
        action, frozen_pos, live_pos = "HOLD(warmup)", float("nan"), float("nan")
    elif halted:
        action, frozen_pos, live_pos = "HALT", ctx.decision.frozen_position, 0.0
    else:
        action, frozen_pos, live_pos = "OPERATE", ctx.decision.frozen_position, ctx.decision.live_position
    sized = float(live_pos * leverage) if (not np.isnan(leverage) and not np.isnan(live_pos)) else float("nan")

    proposal = Proposal(
        asof=str(asof.date()),
        strategy_hash=strategy_hash(spec),
        action=action,
        frozen_position=float(frozen_pos) if frozen_pos == frozen_pos else float("nan"),
        live_position=float(live_pos) if live_pos == live_pos else float("nan"),
        target_vol_ann=float(vol_target),
        leverage_for_vol_target=leverage,
        sized_exposure=sized,
        circuit_halted=halted,
        circuit_reasons=list(ctx.circuit.reasons) if ctx.circuit else [],
        drift_warnings=list(ctx.drift.get("warnings", [])),
        n_forward_months=int(tel.n_frozen) if tel else 0,
        human_approval_required=True,
        note="Proposal only — a human approves operation; promotion is a separate token-gated verdict.",
    )

    appended = [] if ctx.decision is None else [[PaperLedger.DECISIONS, "decision"]]
    ledger.append_manifest(RunManifest(
        run_id=run_id, action="loop", asof=str(asof.date()), strategy_hash=strategy_hash(spec),
        code_version=code_version, appended=appended, created_at=str(asof.date())))

    return {"proposal": asdict(proposal), "logs": ctx.logs,
            "circuit": asdict(ctx.circuit) if ctx.circuit else None, "drift": ctx.drift}


__all__ = ["run_loop", "Proposal", "LoopContext", "Skill",
           "ResearchSkill", "SignalSkill", "RiskSkill", "PortfolioSkill"]
