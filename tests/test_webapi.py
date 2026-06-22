"""ARC 2.0 web API bridge — CI-native tests (FastAPI TestClient over a temp ledger; no engine, no network).

Proves the bridge serves the real autonomy state honestly (no forward Sharpe/DSR pre-verdict) and that the
co-pilot write path (decide) is recorded, immutable, and validated — without ever touching the holdout.
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from arc.autonomy import PaperLedger, book_trial, run_loop
from arc.autonomy.source import monthly_return_provider
from arc.webapi.app import app


def _ar1(n=45, phi=0.55, scale=0.02, seed=7):
    rng = np.random.default_rng(seed)
    x = np.zeros(n)
    for t in range(1, n):
        x[t] = phi * x[t - 1] + rng.normal(scale=scale)
    return pd.Series(x, index=pd.date_range("2008-01-31", periods=n, freq="ME"))


@pytest.fixture
def client(tmp_path, monkeypatch):
    """Point the API at a temp state root seeded with a booked, partially-accrued momentum sleeve."""
    monkeypatch.setenv("ARC_STATE_ROOT", str(tmp_path))
    monkeypatch.setenv("ARC_WEB_CACHE", str(tmp_path / "no_cache.json"))  # no engine cache
    led = PaperLedger(tmp_path / "momentum")
    book_trial(led, n_trials=45, sr_std=0.07, eval_at_n=24, dsr_min=0.50, issued_by="t")
    r = _ar1(45)
    prov = monthly_return_provider(r, pub_lag_days=1)
    for m in r.index[30:]:  # ~15 forward months -> ACCRUING (< 24), with a latest decidable month
        run_loop(m + pd.Timedelta(days=2), prov, led)
    return TestClient(app), led


def test_health(client):
    c, _ = client
    d = c.get("/api/health").json()
    assert d["ok"] is True and d["service"] == "arc-webapi"


def test_state_shape_and_honesty(client):
    c, _ = client
    d = c.get("/api/autonomy/state").json()
    assert len(d["sleeves"]) == 3 and d["pool"]["name"] == "pool"
    assert d["meta"]["n_promoted"] == 0
    mom = next(s for s in d["sleeves"] if s["name"] == "momentum_front")
    assert mom["contract"]["eval_at_n"] == 24 and mom["contract"]["booked"] is True
    assert mom["readiness"]["state"] in ("ACCRUING", "READY", "OVERSHOT")
    assert set(mom["streams"]) == {"frozen", "live", "operator"}
    # HONESTY: pre-verdict, NO risk-adjusted score is emitted. The verdict is null and the operational
    # stream summaries expose only counts/positions/returns/drawdown — never a Sharpe/DSR/IC. (The
    # committed `dsr_min` bar and the disclaimer text legitimately mention DSR; those are not scores.)
    for s in d["sleeves"]:
        assert s["verdict"] is None
        for stream in s["streams"].values():
            ks = set(stream)
            assert ks == {"n", "cum_return", "last_position", "max_drawdown"}
            assert not any(t in k for k in ks for t in ("sharpe", "dsr", "ic", "sr_ann", "psr"))
    assert json.dumps(d)  # serializable


def test_decide_records_and_is_immutable(client):
    c, led = client
    month = max(led.decisions())
    r1 = c.post("/api/autonomy/decide", json={"strategy": "momentum", "month": month,
                                              "action": "OVERRIDE", "position": 0.2, "rationale": "half",
                                              "decided_by": "t"})
    assert r1.status_code == 200 and r1.json()["ok"] is True
    assert r1.json()["decision"]["action"] == "OVERRIDE"
    assert abs(r1.json()["decision"]["operator_position"] - 0.2) < 1e-9
    # a DIFFERENT later choice for the same month -> 409 (immutable forward track record)
    r2 = c.post("/api/autonomy/decide", json={"strategy": "momentum", "month": month,
                                              "action": "OVERRIDE", "position": 0.5, "rationale": "x",
                                              "decided_by": "t"})
    assert r2.status_code == 409


def test_decide_no_decision_is_400(client):
    c, _ = client
    r = c.post("/api/autonomy/decide", json={"strategy": "momentum", "month": "2099-12-31",
                                             "action": "APPROVE", "decided_by": "t"})
    assert r.status_code == 400


def test_decide_override_without_position_is_400(client):
    c, led = client
    month = max(led.decisions())
    r = c.post("/api/autonomy/decide", json={"strategy": "momentum", "month": month,
                                             "action": "OVERRIDE", "decided_by": "t"})
    assert r.status_code == 400


def test_ledger_endpoint(client):
    c, _ = client
    d = c.get("/api/autonomy/ledger/momentum").json()
    assert d["strategy"] == "momentum_front" and len(d["decisions"]) > 0
    assert "operator_decisions" in d and set(d["realizations"]) == {"frozen", "live", "operator"}


def test_unknown_strategy_is_404(client):
    c, _ = client
    assert c.get("/api/autonomy/ledger/nope").status_code == 404
    assert c.post("/api/autonomy/decide", json={"strategy": "nope", "month": "2026-07-31",
                                                "action": "APPROVE"}).status_code == 404
