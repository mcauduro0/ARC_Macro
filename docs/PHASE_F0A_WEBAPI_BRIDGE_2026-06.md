# Phase F0a — the ARC 2.0 web API bridge (frontend foundation)

The first increment of the ARC Macro 2.0 frontend redesign: the **data bridge** from the pure autonomy
spine to the UI. Decided with the owner: a FastAPI service exposing `arc.autonomy` (read state + write
co-pilot decisions), proxied later by the Node/tRPC server; engine-heavy proposals precomputed by a job.
7 new tests, 403 green. The UI talks to the SAME functions the CLI does — no second source of truth.

## What was built

| piece | what it is |
|---|---|
| `arc/webapi/state.py` | Pure builders for the web state — read the durable `state/paper/<key>/*.jsonl` ledgers via `PaperLedger`. Per-sleeve contract (n_trials/eval_at_n/dsr_min/forward_start), readiness (ACCRUING/READY/OVERSHOT/SPENT/UNBOOKED — mirrors `score_both_edges`), the 3 streams (frozen/live/operator, operational only), last operator decision, pooled-holdout state. **No engine, no network.** |
| `arc/webapi/app.py` | FastAPI app. `GET /api/health`, `GET /api/autonomy/state` (ledger-live + cached snapshot), `GET /api/autonomy/proposals`, `GET /api/autonomy/ledger/{strategy}` (raw immutable records), `POST /api/autonomy/decide` (records a co-pilot decision via `arc.autonomy.copilot.decide`). CORS for the Vite dev server. |
| `scripts/dump_web_state.py` | The engine-heavy producer: runs the co-pilot `propose()` for every booked sleeve (~30-60s, needs the macro engine) with the live VaR/ES gate on, and writes `state/web/state.json` (proposals + meta). The API merges this cache with the fast live ledger reads. |
| `tests/test_webapi.py` | 7 CI-native tests (FastAPI TestClient over a temp ledger). |

## The honesty contract, enforced at the API layer

- `GET /state` never emits a forward Sharpe/DSR pre-verdict. Each sleeve exposes operational stream
  summaries only (`n`, `cum_return`, `last_position`, `max_drawdown`) and a `verdict` that is `null`
  until the one-shot holdout fires. `meta.n_promoted` is computed from real passed verdicts (0 today).
  Readiness is surfaced verbatim ("Refuses: 0 of 24 forward months (24 to go)").
- `POST /decide` is the co-pilot write path: immutable per `(month, hash)` (a different later choice →
  **409**), validated (no decision for the month → **400**; OVERRIDE without a position → **400**), and
  it records ONLY the `operator` stream — the scored `frozen` holdout is never touched.

## Verified end-to-end (real ledgers)

`dump_web_state.py` → real proposals (momentum **-0.61**, nowcast **+0.25**, fiscal warmup; VaR/gate
inactive today = 0 forward months). The API then serves the merged truth:

```
meta: as_of 2026-07-01, data_through 2026-06-30, n_promoted 0, has_proposals true
momentum_front  ACCRUING  0/24 forward months   proposal OPERATE
nowcast_long    ACCRUING  0/24 forward months   proposal OPERATE
fiscal_hard     ACCRUING  0/24 forward months   proposal HOLD(warmup)
POOL  booked, eval_at_n 12, 0/12 common months  Refuses: 0 of 12 (12 to go)
```

This is the ARC 2.0 truth the new UI will render: nothing promoted, everything accruing, the verdict
refuses — by design, not omission.

## Run it
```
pip install -e ".[webapi]"                 # fastapi + uvicorn + httpx (added to ci.yml + pyproject)
python scripts/dump_web_state.py           # produce state/web/state.json (engine-heavy; from the cron/accrual)
uvicorn arc.webapi.app:app --port 8787     # serve; the Node/tRPC server will proxy autonomy.*
```

## Next (frontend phases)
F0b design system (fresh ARC 2.0 identity + nav shell) → F1 Command + Holdout/Governance → F2 Co-pilot →
F3 Risk + Macro Engine context → F4 Research/Diagnostics + Ledger → F5 mobile/polish/tests. See
[[arc-macro-frontend-plan]].

## Delivered
- `arc/webapi/{__init__,state,app}.py`, `scripts/dump_web_state.py`, `tests/test_webapi.py` (7);
  `fastapi`/`httpx` added to CI + `pyproject` (`webapi` extra). `state/web/` is gitignored runtime state.
