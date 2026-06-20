# Phase 3.1 — as-of-invariance gate on the real pipeline (2026-06)

Phase 3's goal is a single point-in-time spine. The correct first move is **not** the risky
data-layer rewire — it is the **safety net** that will protect that rewire: a repeatable gate that
proves the engine's feature construction is point-in-time. Build the ruler before you move the wall.

## What the gate asserts

`tests/test_asof_invariance.py` exercises the **real** `DataLayer.build_monthly` at several historical
decision months E (2016, 2018, 2020, 2022 — far from the data frontier so legitimate frontier
ffill/extension cannot confound the comparison). For each E it builds the monthly frame two ways:

- **as-of-E vintage:** raw series trimmed to `event_time <= E`, then `build_monthly`.
- **full series:** the same build from all data.

and asserts the value **at month E** is identical. If any column at E differs, that column used
post-E data to decide at E — a look-ahead. Two tests:

1. `test_interpolated_fundamentals_are_point_in_time` — hard regression test for the fixed columns
   (`ppp_factor`, `gdppc_ratio`, `ca_pct_gdp`, `trade_openness`).
2. `test_no_column_uses_future_data_at_decision_date` — the strong, general gate over **every**
   monthly column.

## It has teeth (proven, not assumed)

Re-running with the leak re-enabled (`ARC_CAUSAL_INTERP=0`, legacy linear interpolation) **fails** the
gate, flagging `ppp_factor` at every decision date (relative differences up to ~2%):

```
ppp_factor@2016-06-30: as-of=2.16299 full=2.18232 (rel diff 8.86e-03)
ppp_factor@2020-06-30: as-of=2.26496 full=2.31206 (rel diff 2.04e-02)
```

With the causal fix (default `ARC_CAUSAL_INTERP=1`) the gate passes. So the gate would have caught the
interpolation look-ahead and now blocks any regression or new pipeline leak.

## Why this design (and its limits)

- It tests the **value at the decision date**, not a prefix of two large as-of windows. That is the
  formulation that actually isolates look-ahead: a future annual anchor is in the past relative to a
  large as-of cutoff, so a coarse "trim two big windows" test would miss it. Comparing as-of-E vs full
  **at E** is the honest probe (same logic as `tests/test_interpolation.py`).
- Guarded: importing the engine needs xgboost/hmmlearn and the comparison needs the collected CSVs, so
  it runs locally and **skips in CI** (like `test_publication_lag`). The CI-runnable as-of-invariance
  coverage lives at the transform layer (`test_interpolation`, `test_regime_pointintime`,
  `test_asof`). Making this gate CI-native is part of Phase 3.2 (engine reads from the in-memory
  bitemporal store, no heavy deps).
- It covers `build_monthly` (where the interpolation, publication-lag and ffill leaks lived). Extending
  the same as-of-E vs full probe to the full `FeatureEngine.build_all` output is the natural next
  increment.

## Next — Phase 3.2

Wire `DataLayer` to the `arc.data` bitemporal store behind a toggle: migrate `server/model/data/*.csv`
into the store (`csv_bridge` + a per-series publication-lag registry / expanded catalog covering the
~44 engine series), replace `load_series` + manual `shift()` with `store.as_of(t)`, and add a freshness
gate. This gate is the safety net that makes that rewire safe — and turns "no leakage" from a patched
property into a structural one.
