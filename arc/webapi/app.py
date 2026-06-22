"""FastAPI bridge for the ARC 2.0 UI. Pure + fast: read endpoints serve ledger state (+ a cached
engine-heavy snapshot); the write endpoint records a co-pilot operator decision.

Run locally:  uvicorn arc.webapi.app:app --reload --port 8787
The Node/tRPC server proxies these under ``autonomy.*`` so the React app stays on tRPC + React Query.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from arc.autonomy import PaperLedger
from arc.autonomy.copilot import decide as copilot_decide
from arc.autonomy.ledger import RepaintError
from arc.webapi.state import SPEC_BY_NAME, STATE_KEY, build_web_state

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# short --strategy keys -> registry names (the UI / tRPC may send either)
_KEY_TO_NAME = {"momentum": "momentum_front", "nowcast": "nowcast_long", "fiscal": "fiscal_hard"}


def _state_root() -> str:
    return os.environ.get("ARC_STATE_ROOT", os.path.join(ROOT, "state", "paper"))


def _cache_path() -> str:
    return os.environ.get("ARC_WEB_CACHE", os.path.join(ROOT, "state", "web", "state.json"))


def _load_cache() -> dict:
    path = _cache_path()
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:  # noqa: BLE001 — a corrupt/partial cache must not take the API down
        return {}


def _resolve(strategy: str) -> tuple[str, dict]:
    """Accept either a registry name (momentum_front) or a short key (momentum); return (name, spec)."""
    name = _KEY_TO_NAME.get(strategy, strategy)
    if name not in SPEC_BY_NAME:
        raise HTTPException(status_code=404, detail=f"unknown strategy '{strategy}'")
    return name, SPEC_BY_NAME[name]


class DecideRequest(BaseModel):
    strategy: str = Field(..., description="registry name or short key (momentum/nowcast/fiscal)")
    month: str = Field(..., description="ISO month-end the decision earns, e.g. 2026-07-31")
    action: str = Field(..., description="APPROVE | OVERRIDE | SKIP")
    rationale: str = ""
    decided_by: str = "owner"
    position: Optional[float] = Field(None, description="required for OVERRIDE")
    decided_at: str = ""


def create_app() -> FastAPI:
    app = FastAPI(title="ARC Macro 2.0 API", version="2.0",
                  description="Bridge from the autonomy spine (ledgers + co-pilot) to the UI.")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=os.environ.get("ARC_CORS_ORIGINS", "http://localhost:5173,http://localhost:3000").split(","),
        allow_credentials=True, allow_methods=["*"], allow_headers=["*"],
    )

    @app.get("/api/health")
    def health() -> dict:
        return {"ok": True, "service": "arc-webapi", "version": "2.0",
                "state_root": _state_root(), "has_cache": os.path.exists(_cache_path())}

    @app.get("/api/autonomy/state")
    def state() -> dict:
        """Full web state: ledger-derived (live) + the cached engine-heavy proposals/macro snapshot."""
        return build_web_state(_state_root(), cached=_load_cache())

    @app.get("/api/autonomy/proposals")
    def proposals() -> dict:
        """Just the engine-computed current proposals (from the dump). Empty until the dump job runs."""
        return _load_cache().get("proposals", {})

    @app.get("/api/autonomy/ledger/{strategy}")
    def ledger(strategy: str) -> dict:
        """Raw immutable ledger records for one sleeve (decisions / realizations / operator / governance)."""
        name, _spec = _resolve(strategy)
        led = PaperLedger(os.path.join(_state_root(), STATE_KEY[name]))
        return {
            "strategy": name,
            "decisions": [asdict(d) for d in led.decisions().values()],
            "realizations": {s: [asdict(r) for r in led.realizations(s).values()]
                             for s in ("frozen", "live", "operator")},
            "operator_decisions": [asdict(o) for o in led.operator_decisions().values()],
        }

    @app.post("/api/autonomy/decide")
    def decide(req: DecideRequest) -> dict:
        """Record a co-pilot operator decision (APPROVE/OVERRIDE/SKIP) — immutable, ledger-only, fast.
        The frozen holdout is never touched. 400 on a bad request (e.g. no decision for the month yet,
        OVERRIDE without a position); 409 if the month was already committed with a different choice."""
        name, spec = _resolve(req.strategy)
        led = PaperLedger(os.path.join(_state_root(), STATE_KEY[name]))
        try:
            od = copilot_decide(led, spec=spec, month=req.month, action=req.action,
                                rationale=req.rationale, decided_by=req.decided_by,
                                position=req.position, decided_at=req.decided_at, run_id="webapi")
        except RepaintError as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        return {"ok": True, "decision": asdict(od)}

    return app


app = create_app()
