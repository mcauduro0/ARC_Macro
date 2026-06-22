# Phase F3-Macro — the Macro Engine screen + an honest, defensive macro extractor

The fourth frontend increment fills the last data-bearing nav area: **Macro Engine** — the point-in-time macro
context behind the sleeves (composite r*, regime probabilities, the state-variable vector, FX fair value, the
DI curve). The hard part was the backend: surfacing real engine internals **without fabricating anything**.

## The honesty trap (and how it was handled)
`ProductionEngine.initialize()` builds features but **does not fit the regime model** (that happens lazily in
`step()`), and `RegimeModel.get_probs_at` returns a constant **1/3 placeholder** when unfit. Naively reading it
would have shown a fabricated "regime" dressed as data. `_extract_macro` therefore:
- **explicitly fits** the regime model (`regime_model.fit()`), then
- **refuses the degenerate placeholder** — a regime panel with ~zero variation across states is omitted, with a
  note, never emitted as if real;
- extracts every other field **defensively** (`getattr`/presence checks, dict-or-DataFrame aware for
  `data_layer.monthly`), emitting a field **only when genuinely populated** and recording every omission in
  `notes`. Nothing is invented; absence is reported as absence.

Verified by running the real engine end-to-end — the dump produced **all six fields real, `notes: []`**:
r* 6.57% (36-mo history, climbing from 3.4%), regime carry-dominant (P_carry 0.86 / P_riskoff 0.09 /
P_stress 0.05, filtered posterior with genuine month-to-month variation), 11 state-variable z-scores, BRL
~5% rich vs BEER fair (5.14 spot / 5.42 fair), and a full DI curve (3M 13.9% → 10Y 14.8%).

## What was built
- `scripts/dump_web_state.py` — `_extract_macro(e)` (defensive, fits regime, real-only) + dict/DataFrame-aware
  `monthly` accessors; wired into the dump's `macro` field (was hard-coded `None`).
- `shared/autonomy.ts` — the `MacroContext` contract (`rstar` / `regime` / `state_vars` / `fx_fair` /
  `di_curve` / `notes`), each nullable; `WebState.macro` is now typed `MacroContext | null` (was `unknown`).
  `state.py` already forwards the cached `macro` verbatim — no change needed.
- `client/src/arc/pages/Macro.tsx` — the Mesa Macro screen: r* card with a dependency-free SVG sparkline,
  regime probability bars (filtered-posterior caption), a z-score state-vector panel (centered ±3σ bars), FX
  fair-value vs spot with an over/undervalued read, and a DI-curve sparkline + tenor table. Every section is
  null-safe; absent fields surface via the honest `notes` panel; the whole-macro-null state tells the operator
  to run the dump. No forward Sharpe/DSR (macro context, not strategy performance).
- `ArcApp.tsx` — `/macro` now renders the real screen (was a Placeholder).
- `tests/test_macro_extract.py` (6) — CI-native honesty guards (stub engine, no heavy import): never crashes on
  an empty engine, populates only real fields, **refuses the 1/3 placeholder**, **fits an unfit regime model**,
  and the `build_web_state` macro passthrough.

## Verified
- `pytest tests/test_macro_extract.py tests/test_webapi.py` — **green** (12).
- `pnpm check` (tsc) — green; `pnpm test` (vitest) — **389 passed**.
- **Live engine dump** — real macro, `notes: []`. **Live bridge smoke** — `GET /api/autonomy/state` returns the
  full `MacroContext` (6 fields, real values) through React → tRPC → FastAPI → `_extract_macro` → engine.

## Next
PR3 — F5: mobile/responsive Shell (collapsible nav, scrollable tables) + RTL/jsdom component tests + Playwright
config. After that, every nav area is a real screen. See [[arc-macro-frontend-plan]].
