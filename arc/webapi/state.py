"""Pure builders for the ARC 2.0 web state — read the durable ledgers, expose operational state only.

No engine, no network: everything here is a read over ``state/paper/<key>/*.jsonl`` via ``PaperLedger``
(+ an optional engine-heavy ``cached`` snapshot for proposals/macro). The verdict-readiness logic mirrors
``scripts/score_both_edges.py`` exactly (REFUSED/READY/SPENT). Pre-verdict NO forward Sharpe/DSR is ever
emitted — only counts, positions, drawdown, cum return (the honesty contract).
"""

from __future__ import annotations

import os
from typing import Optional

from arc.autonomy import (
    PaperLedger,
    copilot_status,
    pooled_forward_returns,
)
from arc.autonomy.spec import (
    FROZEN_SPEC,
    HARD_PB_SPEC,
    NOWCAST_SPEC,
    POOL_HASH,
    SPECS,
    strategy_hash,
)

# registry name -> on-disk state dir key (shared with paper_loop.py / score_both_edges.py / copilot.py)
STATE_KEY = {"momentum_front": "momentum", "nowcast_long": "nowcast", "fiscal_hard": "fiscal"}
POOL_KEY = "pool"
SPEC_BY_NAME = {"momentum_front": FROZEN_SPEC, "nowcast_long": NOWCAST_SPEC, "fiscal_hard": HARD_PB_SPEC}

EVAL_AT_N = 24            # single-sleeve pre-committed forward sample
POOL_EVAL_AT_N = 12       # pooled (K_eff-derived) pre-committed forward sample
DSR_MIN = 0.50
N_TRIALS = {"momentum": 45, "nowcast": 55, "fiscal_momentum": 69}
INSTRUMENT_LABEL = {"front": "DI 1Y receiver", "long": "DI 10Y receiver", "hard": "sovereign spread"}


def _readiness(n: int, eval_at_n: int, basis, consumed: bool, verdict) -> dict:
    """The honest verdict status, computed by READING the ledger only (never consumes the holdout)."""
    if basis is None:
        return {"ready": False, "state": "UNBOOKED",
                "message": "Not booked — no deflation basis yet."}
    if consumed:
        if verdict is not None:
            return {"ready": False, "state": "SPENT",
                    "message": f"Verdict spent: {'PASS' if verdict.passed else 'FAIL'} "
                               f"(DSR {verdict.dsr:.3f} vs {verdict.dsr_min}, Sharpe {verdict.sr_annual:.2f}, "
                               f"n={verdict.n})"}
        return {"ready": False, "state": "SPENT",
                "message": "Holdout consumed but no verdict rendered (prior crash) — spent."}
    if n < eval_at_n:
        return {"ready": False, "state": "ACCRUING",
                "message": f"Refuses: {n} of {eval_at_n} forward months "
                           f"({eval_at_n - n} to go)."}
    if n > eval_at_n:
        return {"ready": False, "state": "OVERSHOT",
                "message": f"Refuses: overshot ({n} > {eval_at_n}) — re-book a new schedule."}
    return {"ready": True, "state": "READY",
            "message": f"Ready: exactly {n} == {eval_at_n} forward months; a verdict would fire."}


def _verdict_dict(v) -> Optional[dict]:
    if v is None:
        return None
    return {"passed": bool(v.passed), "reason": v.reason, "dsr": v.dsr, "sr_annual": v.sr_annual,
            "n": v.n, "dsr_min": v.dsr_min, "n_trials": v.n_trials}


def build_sleeve_state(name: str, spec: dict, ledger: PaperLedger,
                       *, cached_proposal: Optional[dict] = None) -> dict:
    """One sleeve's full web state: contract, streams (operational only), readiness, last decision, and the
    (cached, engine-computed) current proposal."""
    h = strategy_hash(spec)
    basis = ledger.basis_for(h)
    fz = ledger.frozen_frame()
    n_forward = int(fz.shape[0])
    eval_at_n = int(basis.eval_at_n) if basis is not None else EVAL_AT_N
    consumed = h in ledger.consumed_hashes()
    verdict = ledger.verdict_for(h) if consumed else None
    status = copilot_status(ledger, strategy=name)
    ops = ledger.operator_decisions()
    last_op = ops[max(ops)] if ops else None

    return {
        "name": name,
        "instrument": spec["instrument"],
        "instrument_label": INSTRUMENT_LABEL.get(spec["instrument"], spec["instrument"]),
        "kind": spec["kind"],
        "hash": h,
        "contract": {
            "n_trials": int(basis.n_trials) if basis else N_TRIALS.get(spec["kind"]),
            "eval_at_n": eval_at_n,
            "dsr_min": float(basis.dsr_min) if basis else DSR_MIN,
            "forward_start": (basis.forward_start if basis else None),
            "booked": basis is not None,
        },
        "n_forward_months": n_forward,
        "months_to_verdict": max(0, eval_at_n - n_forward),
        "readiness": _readiness(n_forward, eval_at_n, basis, consumed, verdict),
        "verdict": _verdict_dict(verdict),
        "streams": {"frozen": status["frozen"], "live": status["live"], "operator": status["operator"]},
        "n_operator_decisions": status["n_operator_decisions"],
        "last_operator_decision": (None if last_op is None else {
            "month": last_op.month, "action": last_op.action,
            "operator_position": last_op.operator_position, "proposed_position": last_op.proposed_position,
            "rationale": last_op.rationale, "decided_by": last_op.decided_by,
        }),
        "proposal": cached_proposal,  # engine-computed (dump job); None if not yet dumped
    }


def build_pool_state(pool_ledger: PaperLedger, member_ledgers: dict) -> dict:
    """The pooled holdout's web state: members, pre-committed contract, common-support count, readiness."""
    basis = pool_ledger.basis_for(POOL_HASH)
    eval_at_n = int(basis.eval_at_n) if basis is not None else POOL_EVAL_AT_N
    frames = {name: led.frozen_frame() for name, led in member_ledgers.items()}
    pooled = pooled_forward_returns(frames)
    n_common = int(len(pooled))
    consumed = POOL_HASH in pool_ledger.consumed_hashes()
    verdict = pool_ledger.verdict_for(POOL_HASH) if consumed else None
    return {
        "name": "pool",
        "hash": POOL_HASH,
        "members": list(STATE_KEY.keys()),
        "contract": {
            "n_trials": int(basis.n_trials) if basis else 72,
            "eval_at_n": eval_at_n,
            "dsr_min": float(basis.dsr_min) if basis else DSR_MIN,
            "forward_start": (basis.forward_start if basis else None),
            "booked": basis is not None,
        },
        "n_common_forward_months": n_common,
        "months_to_verdict": max(0, eval_at_n - n_common),
        "readiness": _readiness(n_common, eval_at_n, basis, consumed, verdict),
        "verdict": _verdict_dict(verdict),
        "rationale": "Equal-weight panel of the 3 sleeves; K_eff≈2.92 → a verdict ~1y sooner than a "
                     "single sleeve IF several sleeves carry real edge (else pooling dilutes).",
    }


def build_web_state(state_root: str, *, cached: Optional[dict] = None) -> dict:
    """Assemble the full web state for the UI. ``cached`` is the engine-heavy snapshot (proposals + macro)
    from ``scripts/dump_web_state.py``; when absent, the ledger-derived state is still fully served."""
    cached = cached or {}
    cached_proposals = cached.get("proposals", {})
    member_ledgers = {}
    sleeves = []
    n_promoted = 0
    for name, spec in SPECS.items():
        led = PaperLedger(os.path.join(state_root, STATE_KEY[name]))
        member_ledgers[name] = led
        s = build_sleeve_state(name, spec, led, cached_proposal=cached_proposals.get(name))
        if s["verdict"] and s["verdict"]["passed"]:
            n_promoted += 1
        sleeves.append(s)

    pool_led = PaperLedger(os.path.join(state_root, POOL_KEY))
    pool = build_pool_state(pool_led, member_ledgers)

    return {
        "meta": {
            "as_of": cached.get("as_of"),
            "dumped_at": cached.get("dumped_at"),
            "data_through": cached.get("data_through"),
            "n_promoted": n_promoted,
            "honesty": "Nothing is promoted until a candidate survives its one-shot forward holdout. "
                       "Pre-verdict, only operational state is shown — never a forward Sharpe/DSR.",
            "has_proposals": bool(cached_proposals),
        },
        "sleeves": sleeves,
        "pool": pool,
        "macro": cached.get("macro"),   # engine context (r* CI, regime, ...) from the dump; may be None
    }
