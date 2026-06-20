# Phase 4.4 — edge search round 2: activity nowcast (a second gated candidate) + real-curve (no data)

Round 1 (`docs/PHASE4_EDGE_SEARCH_2026-06.md`) screened 45 pre-registered hypotheses; only `front/mom3`
survived. This round adds two fresh, economically-motivated families that carry information **not** in the
round-1 set: a point-in-time **activity nowcast** (closing the documented IBC-Br blindspot) and the
**NTN-B real curve**. Same gate (carry-neutralized IC + half-sample H1/H2 decay + refit-OOS CPCV), same
discipline (H2 ≈ 0.1–0.2 is the bar, deflate for the cumulative hypothesis count, survivors are
candidates to verify — never promotions).

## Real curve — NO HISTORICAL DATA (honest dead end, deferred)

`NTNB_5Y`, `ANBIMA_NTNB_5Y`, `ANBIMA_BREAKEVEN_5Y`, `BREAKEVEN_5Y` (and the 10Y variants) each contain a
**single 2024 snapshot** (2 CSV lines), not a time series. The engine's `monthly["ntnb_5y"]` has `n=1`. So
the real-curve / breakeven track cannot be gated at all — it needs historical collection first
(ANBIMA/Tesouro history), a data-layer task. **Deferred, not failed.**

## Activity nowcast — a genuine SECOND gated candidate

`arc/features/nowcast.py` builds a strictly point-in-time mixed-frequency dynamic factor: it combines the
laggy official activity series (IBC-Br, ~45-day lag) with timelier monthly series (Brazil equity `EWZ`,
commodities `iron_ore`/`bcom`, terms of trade `tot`) and fills the ragged edge with first-PC loadings
re-estimated each month on data ≤ t. **As-of-invariant by construction** — `pit_dynamic_factor(panel)[E]
== pit_dynamic_factor(panel.loc[:E])[E]`, proven in `tests/test_nowcast.py` (the crown-jewel leak gate).
Sign is oriented to IBC-Br so higher = more activity. Economic prior: weakening activity ⇒ policy cuts ⇒
rate-receiver gains, so each signal is the **negated** factor / surprise / momentum.

### Gate result (carry-neutral, refit-OOS; cumulative ≈ 48 hypotheses screened rounds 1+2)

| signal | cnIC | H1 | H2 | decay | refit-OOS | OOSmin | verdict |
|---|---|---|---|---|---|---|---|
| front/neg_nowcast_surprise | +0.204 | +0.022 | **+0.329** | −0.307 | +0.253 | +0.006 | PASS |
| belly/neg_nowcast | +0.187 | +0.229 | **+0.298** | −0.069 | +0.217 | +0.060 | PASS |
| long/neg_nowcast_mom3 | +0.228 | +0.187 | **+0.282** | −0.095 | +0.239 | +0.120 | PASS |

H2 > H1 (decay negative) — the **opposite** of the H1≫H2 contamination signature that killed the old
regime-timing edge. The nowcast tracks IBC-Br (corr of m/m changes +0.35).

### Adversarial verification (`scripts/verify_nowcast.py`) — RED-FLAG discipline

cnIC ≈ 0.2 with H2>H1 from a freshly-built feature is exactly the "too good" pattern this project treats
as leakage until disproven. The break-tests:

- **Neutralize vs carry + market (EWZ return, VIX):** IC essentially unchanged (0.165→0.168, 0.174→0.173,
  0.175→0.174). **The strongest result — the edge is NOT carry and NOT risk-on/off in disguise.**
- **Leave-one-out:** dropping **IBC-Br kills it** (refit-OOS → −0.06/−0.02/+0.07) — it genuinely uses
  activity data; dropping **EWZ keeps it** (still PASS) — not pure equity beta. But it is **fragile**:
  dropping `bcom` or `iron_ore` flips front/long to fail. An activity-ONLY factor (no market prices) is
  weak. So the PASS depends on the full mixed-input set.
- **Lag scan (predictive vs coincident):** `long/neg_nowcast_mom3` is cleanly predictive (L−1 ≈ −0.02,
  L0 +0.05, **L+1 +0.23**); `belly/neg_nowcast` predictive (L0 ≈ L+1 ≈ 0.18); **`front/neg_nowcast_surprise`
  is largely COINCIDENT** (L−1 +0.26, L0 +0.28 ≈ L+1 +0.24) — benign co-movement (the surprise mirrors
  recent market-priced moves), not look-ahead, but a weaker tradeable case.
- **Sub-period thirds:** belly [+0.20, +0.18, +0.31] and long [+0.19, +0.34, +0.19] positive in all three;
  **front [+0.005, +0.28, +0.39] is period-concentrated** (dead in the first third).
- **Placebo:** a random signal fails (cnIC +0.008, refit-OOS −0.049) — the gate still has teeth.
- **No look-ahead:** as-of-invariance test passes; lag scan shows no implausible anti-causal spike for
  the clean signals; inputs are PIT (P5 publication lag + Phase 3 PIT proof).

### Honest verdict

A **defensible second candidate** from the honest pipeline — found exactly where the roadmap pointed
(close the IBC-Br blindspot). The robust expressions are **`belly/neg_nowcast`** and
**`long/neg_nowcast_mom3`** (stable across thirds, predictive lag structure, survive carry+market
neutralization). **`front/neg_nowcast_surprise` is NOT confirmed** (coincident + period-concentrated).

Caveats (must not be glossed):
1. The three signals are **~one bet** — front/belly/long rate returns are ~0.9 correlated; this is one
   economic idea (activity nowcast → policy → rate level) expressed three ways.
2. **Fragile to the input set** (leave-one-out flips front/long), so it is one mixed factor, not a robust
   ensemble of independent activity reads.
3. **Orthogonality to rate-price momentum not yet measured** — `front/mom3` already trades rate momentum;
   before combining sleeves, confirm `neg_nowcast_mom3` adds IC beyond the rate's own momentum.
4. Per project rule, a gate pass is **necessary, not sufficient** — the real test is the forward single-use
   holdout (paper), which it has never seen.

### Promotion protocol (next, if pursued)

1. Confirm orthogonality to `front/mom3` (rate-price momentum); keep only the incremental part.
2. Operationalize `belly`/`long` nowcast-momentum as a causal sleeve (like `arc/research/sleeve.py`).
3. Book it as a **new trial** in the Phase 7 paper loop (new `strategy_hash` ⇒ deflation bar rises) and
   accrue a forward holdout; promote only on a clean one-shot verdict.

## Delivered

- `arc/features/nowcast.py` — `pit_dynamic_factor`, `nowcast_surprise`, `activity_nowcast` (pure, PIT).
- `tests/test_nowcast.py` — 5 CI-native tests (as-of-invariance leak gate, tracks-factor, ragged-edge,
  sign-orientation, causal surprise). 165 pytest green.
- `scripts/edge_search_nowcast.py` — the gated round-2 search (cumulative-deflated).
- `scripts/verify_nowcast.py` — the adversarial break-test battery above.

No engine behavior changed; the nowcast is a clean, tested, honestly-measured feature awaiting an
orthogonality check and forward-paper validation.
