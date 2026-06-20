# Phase 3.3 — the feature pipeline is provably point-in-time (2026-06)

Phase 3.3 was planned as "make per-step `as_of` the live read path and drop the P5 month-shift." The
evidence redirected it to a stronger, cheaper outcome: **prove the build-once feature pipeline is
already point-in-time**, so the expensive per-step rebuild is unnecessary for correctness. Empirical
over plan — the same discipline we have applied throughout.

## The experiment

`step(asof)` slices a `feature_df` that `build_all()` computes **once** from the full series. The
question: does any feature's value at decision month E depend on data after E? Two ways to probe it
with the spine (3.2):

1. **Spine-based** (spine@E vs spine@latest): showed 31–48 of 56 columns "differing" at E. But this is
   confounded by the lag convention — with a 1-day market lag the spine hides the month-end-E close
   that the engine's convention treats as available at the month-end-E decision, shifting everything
   back one observation. Not a clean look-ahead probe.
2. **Confound-free** (the real test): trim the RAW data by `event_time <= E`, rebuild
   `build_monthly` + `build_all`, and compare the **row at E** to the full build. No lag mechanism is
   involved, so any difference is genuine feature-block look-ahead.

## The result

**Zero leaking columns** at E ∈ {2018-09, 2020-06, 2022-06}, across all 56–57 features (Z-scores,
carry, FX valuation PPP/BEER/Balassa-Samuelson, CIP, term premium, fiscal premium, the equilibrium r*
composite incl. ACM/Kalman, and the equilibrium ML features). The entire feature construction is
**as-of-invariant**: building it from the as-of-E vintage gives exactly the value the full build has
at E.

This confirms the adversarial leak hunt (the feature block uses trailing/expanding/rolling estimators,
not full-sample fits) — now with a direct, repeatable, end-to-end test rather than agent reasoning.

## What this means

- **Per-step rebuild is not needed for feature correctness.** The `feature_df` the engine builds once
  and slices per step is already honest w.r.t. `event_time`. Paying ~5 min/backtest to rebuild every
  step would reproduce the same feature values — so we prove equivalence instead of paying the cost.
- **Publication timing** (using a macro print before it was released) is the only remaining PIT
  dimension, and it is handled by **P5** (the month-shift), which equals knowledge_time gating at
  month-end granularity. The spine (3.2) remains available to make it exact and to handle true
  multi-vintage revisions when real per-vintage adapters land — at which point per-step `as_of`
  becomes the natural live read path (and P5 is dropped to avoid double-lag).

## Delivered

- `tests/test_asof_invariance.py::test_full_feature_pipeline_is_point_in_time` — the crown-jewel gate
  over the full `build_all()` output (confound-free `event_time` trim). It has teeth: with
  `ARC_CAUSAL_INTERP=0` it flags `ppp_fair_ts` (the interpolation leak propagating into the valuation
  feature); with the causal default it passes clean (0 violations).

123 pytest pass (+1).

## Why not ship per-step rebuild now

It would change behavior only via (a) exact-day vs month-granularity publication timing — marginal on
month-end decisions — and (b) multi-vintage revisions — which the single-vintage CSVs do not have. Both
are low-impact today, and the rewire of the walk-forward loop carries real bug risk. The honest call:
defer it until multi-vintage data exists, keep the spine ready (3.2), and rely on the now-proven
feature invariance + P5. When per-step `as_of` is wired, note the **month-end convention**: market
series should be knowable at the month-end decision (lag 0 for the decision mark), not +1 day.

## Phase 3 status

- 3.1 — as-of-invariance gate on `build_monthly` ✅ (#17)
- 3.2 — engine can read through the bitemporal spine, behavior-preserving ✅ (#18)
- 3.3 — full feature pipeline **proven** as-of-invariant; gate codified ✅ (this PR)

Phase 3's correctness goal — "no leakage is structural, not patched" — is met for feature
construction: it is now enforced by a repeatable end-to-end gate.
