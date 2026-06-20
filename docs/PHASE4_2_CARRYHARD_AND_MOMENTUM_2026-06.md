# Phase 4 follow-up — carry_hard fix + the first gated edge (front momentum), 2026-06

Two things: (1) fix the `carry_hard` mismatch at the source (the engine feature, not just the gate's
measurement layer), and (2) extend the honest edge search with a momentum/trend family — which turned
up the **first signal to pass the gate**.

## (1) carry_hard = spread carry (source fix)

Phase 4 found the `hard` sovereign-spread instrument was carry-neutralized against the wrong carry: its
return earns the **spread carry** (`embi/10000/12`) but the engine feature `carry_hard` was the **cupom
cambial (FX)**. PR #20 corrected this in the gate's measurement layer; this fixes it at the source —
`build_carry_features` now sets `carry_hard = embi/10000/12` (toggle `ARC_CARRY_HARD_SPREAD`, default
on; `0` restores the legacy cupom for before/after measurement). This corrects the feature the alpha
model consumes for `hard`, not just the gate.

Guarded test `tests/test_carry_hard.py` asserts `carry_hard == embi/10000/12` by default and that the
legacy toggle differs.

**Overlay impact (gate backtest with the fix).** The gate still correctly **FAILs** (median half-sample
decay 0.456, H1 0.657 → H2 0.187). Overlay Sharpe(ann) moved 1.31 → 1.53 (DSR 0.999) — the spread-carry
feature changed `hard`'s alpha and lifted the nominal Sharpe, but the decay gate rejects it as
non-stationary (the "beautiful backtest" the gate exists to catch). `hard` carry-only IC flipped
+0.065 → −0.096, confirming the gate now neutralizes against the true spread carry. The ensemble's
`hard` carry-neutral IC stays high (+0.459, H2 +0.328) — but that is the multi-feature, feature-selected
ensemble (overfitting), not the single `Z_cds_br` (which collapsed to −0.045 against spread carry). The
fix corrects the carry the alpha model and gate use for `hard`; it neither manufactures nor removes
edge — the honest verdict remains **FAIL**.

## (2) Momentum / trend family — the first gated edge

The macro-fundamental screen found no edge (Phase 4). We added a fresh family carrying NEW information
(price history, not a recombination of the failing macro features): time-series momentum
(Moskowitz–Ooi–Pedersen) at 3/6/12 months + 1-month reversal, per instrument, computed causally from
the return history. 45 hypotheses total (deflated accordingly).

**One survivor: `front/mom3_front`** — 3-month momentum on the 1Y rate receiver:

| metric | value |
|---|---|
| carry-neutral IC | **+0.194** |
| half-sample H1 / H2 | +0.171 / **+0.180** (decay −0.009 — stationary) |
| refit-OOS CPCV mean / worst fold | **+0.179** / −0.094 |

### Adversarial verification (it survives all of it)

- **Lookback robustness** — IC positive at every horizon: mom2 +0.18, mom3 +0.22, mom4 +0.14,
  mom6 +0.17, mom9 +0.21, mom12 +0.14. Not a single-parameter fluke.
- **Sub-period thirds** — +0.231, +0.188, +0.108 — positive in all three (2012–16, 2016–21, 2021–26),
  declining but never flipping (unlike the contamination signals that decayed to ~0/negative).
- **Net of costs + deflation** — standalone strategy (causal expanding z-score position, 2bp turnover
  cost, 0.27 monthly turnover): net **SR(ann) 0.64**, **DSR(45 trials) 0.532**, PSR 0.988.

Economically sensible: 1Y rate momentum captures the persistent **monetary-policy cycle** (Selic moves
in long runs of hikes/cuts), which is orthogonal to carry.

### Honest caveats

- **Tiny absolute return** (net +0.44%/yr, vol 0.68%) — the front's vol is small, so this is a
  diversifying **sleeve** in a vol-targeted overlay, not a standalone money-maker.
- **DSR 0.53** clears deflation but not by a wide margin; the recent third (+0.108) is the weakest.
- **Multiple testing** — 45 hypotheses, ~2 expected false positives. The lookback + sub-period
  robustness strongly argue this is real, not the false positive, but the status is **promising,
  gate-passing candidate — NOT a promotion.** The next gate is a single-use holdout, then paper.

## Why this matters

After exhaustively removing leakage (Phases 1–3) and proving no macro-fundamental signal beats the gate
(Phase 4), a simple, economically-grounded **price-momentum** signal on the front rate **does** pass —
robust to lookback, positive across sub-periods, carry-neutral, and surviving costs and 45-trial
deflation. It is the first defensible alpha candidate the honest pipeline has produced. The discipline
holds: it is a candidate to validate further (holdout → paper), not an asserted track record.

## Delivered

- `server/model/macro_risk_os_v2.py` — `carry_hard` = spread carry (toggle `ARC_CARRY_HARD_SPREAD`).
- `scripts/signal_research.py` — momentum/trend family added to the pre-registered screen.
- `tests/test_carry_hard.py` (guarded) — carry_hard is the spread carry.
- `tests/test_signal_research.py` (CI-native, from Phase 4) covers the evaluator.

## Next

- **Operationalize the edge (Phase 4.3)**: add the momentum sleeve to the production overlay as a gated
  feature and measure the full backtest impact (then a single-use holdout). It must keep clearing the
  gate net of costs in the live config.
- Continue genuine candidates (nowcast/DFM for the IBC-Br blindspot; richer data: ANBIMA real curve,
  positioning/flows), each gated.
- Phase 7 autonomy remains the biggest structural gap.
