# Phase 3.2 — engine reads through the bitemporal as-of spine (2026-06)

3.1 built the safety net (the as-of-invariance gate). 3.2 does the actual wiring: the engine can now
load its raw series from the `arc.data` **bitemporal store**, gated by `knowledge_time`, instead of
flat CSVs — behind a toggle, behavior-preserving by default.

## The single choke point

Every CSV read in `DataLayer.load_all` goes through one function: `load_series(name)`. So we route the
**whole** engine through `as_of(t)` by flipping that one function — none of the bespoke load logic
(ANBIMA/Tesouro overrides, DI-tenor merge, cupom blending) changes.

- `arc/data/engine_catalog.py` — per-CSV-basename publication-lag registry (calendar days): market/
  price 1d; IPCA 10d, fiscal/BoP/ToT 30d, IBC-Br 45d, REER 35d; annual fundamentals 365d. Synthesizes
  a `SeriesContract` per series.
- `arc/data/migrate.py` — `build_store_from_csv_dir(data_dir)` ingests every `{name}.csv` into a
  `BitemporalStore`, stamping `knowledge_time = event_time + lag`. Its parser mirrors `load_series`
  exactly, so `store.as_of_series(latest, name)` reproduces what `load_series(name)` read.
- `macro_risk_os_v2.load_series` is now spine-aware: when `enable_asof_spine(store, asof)` is active it
  returns `store.as_of_series(asof, name)` (only data with `knowledge_time <= asof`); otherwise the
  legacy CSV read. `DataLayer.load_all` builds + enables the store when `ARC_AS_OF_SPINE=1`
  (`ARC_AS_OF_DATE` sets the cutoff; default `latest`).

## Behavior-preserving (proven)

Full `load_all` with the spine on at the latest as-of reproduces the CSV path **exactly**: all 51
loaded series identical (0 mismatches), store built in ~7s. The CSVs are single-vintage, so the
latest as-of returns the full series. The toggle defaults OFF; the default backtest is untouched.

## Point-in-time gating (proven)

At a historical as-of the store hides unreleased prints. E.g. `IPCA_MONTHLY` (lag 10d) at
`asof=2020-06-30` exposes only reference months with `event_time <= 2020-06-20` — the June print
(knowable ~2020-07-10) is correctly invisible. Tests: `tests/test_migrate.py` (CI-native) and
`tests/test_asof_spine_engine.py` (guarded).

## What this is NOT yet (Phase 3.3)

- The walk-forward loop still builds features once from the latest vintage; it does not yet call the
  spine with a **per-step** as-of. Wiring `step(asof)` → `enable_asof_spine(store, asof)` per period is
  3.3, and lets us **drop the P5 month-shift** (knowledge_time gating replaces it; running both would
  double-count, so 3.3 must turn off the P5 shift when the spine drives a real per-step as-of).
- Three annual fundamentals (`GDP_PER_CAPITA`, `CURRENT_ACCOUNT`, `TRADE_OPENNESS`) are read directly,
  not via `load_series`, so they bypass the swap; their interpolation look-ahead is already fixed and
  covered by the as-of-invariance gate.
- The store is in-memory per run (built in ~7s). Persisting it to Parquet (the lake) is a later step.

Net: the spine is populated and the engine can read point-in-time through it, with the default path
proven identical. The remaining work is making per-step as-of the live read path — at which point "no
leakage" is structural, not patched.
