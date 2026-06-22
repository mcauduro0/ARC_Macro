# Phase F0b — "Mesa" design system + nav shell + autonomy data wiring + Command screen

The second frontend increment: the fresh ARC Macro 2.0 visual identity (**"Mesa"** — a trading-desk
terminal aesthetic, chosen by the owner), the autonomy-first nav shell, the tRPC `autonomy.*` proxy to
the FastAPI bridge, and the first real screen — **Command** — wired end-to-end to the live autonomy state.
A full vertical slice (FastAPI → tRPC → React → Mesa UI) proven by `tsc` (green), vitest (389 green, +4
proxy tests), and a real proxy→bridge smoke. Full pivot: the autonomy console is now `/`; the legacy v4.6
dashboard moves to `/legacy`.

## What was built

**Data wiring (typed, tested):**
- `shared/autonomy.ts` — the TypeScript contract mirroring `arc/webapi/state.py` exactly (WebState,
  Sleeve, Pool, Proposal, Readiness, …). One source of truth, shared by the server proxy and the client.
- `server/autonomyRouter.ts` — the tRPC `autonomy` router: `state` / `proposals` / `ledger` (GET proxy)
  + `decide` (POST proxy) → the FastAPI bridge (`ARC_API_URL`, default `:8787`). Surfaces the bridge's
  409 (immutable) / 400 (invalid) as readable errors. Wired into `appRouter`.
- `server/autonomyRouter.test.ts` (4) — mocked-fetch proxy tests (GET parse, non-2xx throws, decide ok,
  409 detail passthrough).
- `client/src/arc/useAutonomy.ts` — typed React Query hooks (`useAutonomyState`, `useDecide` with
  invalidation).

**Mesa design system (fresh identity):**
- `client/src/arc/mesa.css` — near-black canvas, monospace numerics (Geist Mono, tabular), one sharp
  amber accent + green/red for long/short & operate/halt, zero decoration, stark NOT-READY. Scoped under
  `.arc-mesa` so it never fights the legacy theme.
- `client/src/arc/components.tsx` — the dense primitives: `Panel`, `AccrualBar` (the progress ring/bar),
  `Dot`, `Tag`, `Pos` (sign-coloured number), `Pct`, `ReadinessTag`, `actionTag`.
- `client/src/arc/Shell.tsx` — top bar (ARC · Risk OS · 2.0, as-of, LIVE) + the 7-area left nav
  (Command / Co-pilot / Holdout / Risk / Macro / Research / Ledger).

**Command screen (the honest at-a-glance):**
- `client/src/arc/pages/Command.tsx` — the prime directive banner ("NOTHING PROMOTED — the forward
  holdout is the only promoter; pre-verdict, no track record is shown"), the data/as-of strip, and the
  Forward-paper table: each sleeve's proposal (action tag), proposed position, VaR95 (when the gate is
  active), the accrual bar (`n_forward / eval_at_n`), readiness tag, and months-to-verdict — plus the
  pool row. Honest empty/offline states (a bridge-offline panel with the exact commands to run).
- `client/src/arc/ArcApp.tsx` + `pages/Placeholder.tsx` — the shell + routes; the other six areas are
  frank "coming in a later phase" stubs on the same bridge.
- `client/src/App.tsx` — full pivot: `/` → ArcApp; `/legacy` → the old dashboard; `/portfolio` kept.

## Verified
- `pnpm check` (tsc --noEmit) — **green** (all new TS compiles: wouter, tRPC autonomy typing, shared
  types, React components).
- `pnpm test` (vitest) — **389 passed** including the 4 new proxy tests; lockfile unchanged (no new deps,
  so CI's `--frozen-lockfile` install is safe).
- **Real end-to-end smoke:** started `uvicorn arc.webapi.app:app` and the tRPC proxy helper fetched the
  live state — `n_promoted 0`, momentum/nowcast OPERATE, fiscal warmup, all ACCRUING, pool 0/12. React →
  tRPC → FastAPI → arc.autonomy → real ledgers.

## Run the platform
```
# 1. the Python bridge + proposals
python scripts/dump_web_state.py            # engine-heavy proposals -> state/web/state.json
uvicorn arc.webapi.app:app --port 8787      # the FastAPI bridge
# 2. the web app (proxies autonomy.* to :8787)
pnpm dev                                     # Node/tRPC + Vite -> http://localhost:5173
```

## Next
F1 deepens Command + builds Holdout/Governance (eval_at_n countdowns, pre-registration provenance,
pooled verdict). Then F2 Co-pilot (propose→decide, operator ledger, 3-stream), F3 Risk + Macro context,
F4 Research/Ledger, F5 mobile + RTL/Playwright tests. See [[arc-macro-frontend-plan]].

## Delivered
- `shared/autonomy.ts`; `server/autonomyRouter.ts` (+ test, wired into `routers.ts`);
  `client/src/arc/{mesa.css,components.tsx,useAutonomy.ts,Shell.tsx,ArcApp.tsx,pages/Command.tsx,pages/Placeholder.tsx}`;
  `client/src/App.tsx` pivot.
