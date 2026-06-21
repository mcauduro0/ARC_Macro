# Phase 4.5 (batch 2) — positioning gate, pb_momentum re-test, flows via IPEADATA, three-edge scoring

A second massively-parallel batch (a 4-agent authoring workflow on disjoint files, then engine runs +
adversarial integration). It answered the three open questions from the prior batch's "Still open" list,
honestly: **gate positioning** (CFTC + the now-collectable flows), **re-test `pb_momentum`** with the long
global-risk control v1 lacked, and make the paper loop **score all booked edges**. Net: one family ruled
out (positioning/flows), one candidate promoted to forward paper (`fiscal_hard`), and a 502-blocked data
source recovered via a provenance-verified mirror.

## (A) Flows recovered via a provenance-verified IPEADATA fallback — no fabrication

The BCB SGS API is still 502 (all four routes). Rather than leave the flows uncollected, a robust collector
tries SGS first and falls back to **IPEADATA**, but **only adopts a series whose metadata unambiguously
confirms it is the same BCB BPM6 series** — never a silent substitution:

| series | SGS (down) | IPEADATA code | confirmed | collected |
|---|---|---|---|---|
| `IDP_FLOW` | 22885 | `BPAG12_IDP12` | FONTE=Bacen/BP (BPM6), Mensal, US$ mn | **376 mo (1995-01 → 2026-04)** |
| `PORTFOLIO_FLOW` | 22924 | `BPAG12_ICP12` | FONTE=Bacen/BP (BPM6), Mensal, US$ mn | **376 mo (1995-01 → 2026-04)** |

`fetch_flow_ipeadata` (in `arc/data/adapters/bcb_flows.py`) verifies source = Bacen/BCB **and** the BPM6
framework **and** all required concept tokens (and rejects disqualifying tokens), accent-insensitively,
*before* fetching values; an unconfirmable or empty match raises rather than adopting a wrong series.
11 CI-native tests (mocked, no network) cover the parse + the rejection paths.
Collect with `python scripts/collect_flows.py` (auto-prefers SGS once BCB recovers).

## (B) Positioning & flows edge search (round 5) — NO SURVIVORS

`scripts/edge_search_positioning.py` gated CFTC BRL net-spec positioning (level z, fade-crowding,
3-month momentum, momentum-z) on `fx` (primary) and `hard`/`long` (risk channel), plus the four flow
signals on `fx`, through the same gate (carry-neutral IC + half-sample decay + refit-OOS CPCV), deflated
for the cumulative count (PRIOR 78 → **92** after this round's 14 hypotheses).

**14 of 14 fail.** The one tease was `fx/portfolio_flow_z` (IC +0.111, H1 +0.203) — but H2 collapses to
+0.053 with worst OOS fold −0.399: the textbook H1≫H2 non-stationary signature, not a stationary edge.
Positioning and external flows add **no deflation-surviving edge** beyond carry. Clean elimination.

## (C) `pb_momentum` re-test (v2) — clears the bar; the global-risk question is resolved

v1 (`scripts/verify_hard_pb.py`) left `hard/pb_momentum` (primary-balance fiscal momentum) "borderline"
for two reasons; v2 (`scripts/verify_hard_pb_v2.py`) settles the decisive one:

- **The global-risk control is now conclusive.** v1 used US-HY spread (history starts 2023-06 → n=35<40, so
  the partial-IC never ran). v2 uses a **long panel — VIX + NFCI + US 10y-2y term spread + Δcds_5y** —
  giving **n=172**. Result: `IC(carry)=+0.116 → IC(carry + full risk panel)=+0.115`. Neutralizing the
  entire global-risk complex barely moves it: **pb_momentum is not risk-on/off.**
- It clears the gate's bar the two booked edges cleared: **H2 +0.198** (top of the ~0.1–0.2 band),
  survives carry (cnIC +0.114), **orthogonal** to both edges (corr +0.10 / −0.00; partial IC +0.10 / +0.12),
  predictive lag structure (forward IC +0.128 > coincident), placebo fails.
- **Residual caveats (why it is booked as a CANDIDATE, not promoted):** (1) lookback band is narrow —
  diff(2,3,6) pass but **diff(9)/diff(12) collapse** (OOSmin −0.33/−0.21); (2) strength is concentrated in
  the middle third (thirds [+0.16, +0.30, +0.08]) — the 2015–2020 fiscal-crisis era — and is thin recently.
  Sign is consistent across every sub-window (halves and thirds), so it is not a single-period artifact, but
  the magnitude is era-dependent.

The verdict is **computed from the measured numbers, not hardcoded**. The disciplined response to the
residual doubt is not to assert the edge nor to discard a signal that cleared the bar — it is to commit it
to an honest out-of-time test.

## (D) `pb_momentum` promoted to the third candidate sleeve (forward paper)

`HARD_PB_SPEC` is now booked in `arc.autonomy.spec.SPECS` as `fiscal_hard` (instrument `hard`, kind
`fiscal_momentum`, signal `pb_mom6` = `primary_balance.diff(6)` oriented positive, hash `c1ea44037f12`),
deflated against **n_trials=69** (the cumulative count through its discovery round). The paper loop
(`scripts/paper_loop.py --strategy fiscal`), the readiness harness, and the Dagster factory all host it
for free (they iterate `SPECS`). Two new CI invariant tests lock the three-edge registry and prove the
fiscal sleeve runs through the loop on an external signal (the equivalence path).

This is a **candidate under forward paper, not a claimed edge** — the same status front/mom3 and the
nowcast hold. Booking commits it to a single-use forward holdout; promotion to the live book happens only
on a clean one-shot verdict.

## (E) The loop scores all booked edges — honestly blocked today

`scripts/score_both_edges.py` books (idempotent), catches up, and runs a **non-consuming** readiness check
across **all three** edges in one pass. Today (2026-06-20, `ret_df` ends 2026-06, `forward_start=2026-06-30`):

```
 strategy         | hash         | inst  | forward_start | fwd_n | eval_at_n | verdict status
 momentum_front   | 288c80331e8b | front | 2026-06-30    | 0     | 24        | REFUSED: HoldoutNotReadyError 0<24
 nowcast_long     | c9d995d2df32 | long  | 2026-06-30    | 0     | 24        | REFUSED: HoldoutNotReadyError 0<24
 fiscal_hard      | c1ea44037f12 | hard  | 2026-06-30    | 0     | 24        | REFUSED: HoldoutNotReadyError 0<24
```

Zero out-of-time months exist yet, so every verdict correctly **refuses** — proof the machinery is wired
for all three and honestly blocked. **No forward months were fabricated.** First eligible verdict ≈ 2028-06.
Full operator detail in [`PHASE7_2_SCORING_RUNBOOK_2026-06.md`](PHASE7_2_SCORING_RUNBOOK_2026-06.md).

## Honest bottom line

The promotable book is **two confirmed-gated edges** (front/mom3, nowcast) **plus one freshly-promoted
candidate** (`fiscal_hard`) now accruing its own forward holdout — three sleeves under out-of-time test,
none yet promoted to live. The batch eliminated the positioning/flow family with proper measurement,
recovered a 502-blocked dataset without fabricating or substituting, and resolved the one genuinely open
question about `pb_momentum` (it is not global risk-on/off). 204 pytest green.

## Delivered

- `arc/data/adapters/bcb_flows.py` — `fetch_flow_ipeadata` (provenance-verified mirror) + `scripts/collect_flows.py` + `tests/test_bcb_flows_ipea.py` (11 tests). Flows collected (376 mo each).
- `scripts/edge_search_positioning.py` — round-5 positioning/flows gate (no survivors).
- `scripts/verify_hard_pb_v2.py` — pb_momentum re-test with the long global-risk panel (clears the bar).
- `arc/autonomy/spec.py` (`HARD_PB_SPEC`, registry → 3) + `arc/autonomy/__init__.py` export; `scripts/paper_loop.py` (`--strategy fiscal`) + `scripts/score_both_edges.py` (all-edge readiness harness); `tests/test_autonomy.py` (+2 invariants).
- `docs/PHASE7_2_SCORING_RUNBOOK_2026-06.md` — operator runbook (three edges).
