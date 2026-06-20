# Phase 4.3 — operationalize the front-momentum edge as a gated sleeve (2026-06)

The verified edge (`front/mom3`, Phase 4.2) is operationalized here. Two deliberate, honest design
calls — explained below — shape how:

## Design call 1: a standalone sleeve, not an ensemble feature

The intuitive "add it to the production overlay as a feature" is the wrong move for a *single verified*
edge: the overlay is the multi-feature ensemble whose feature selection overfits and fails the gate on
half-sample decay. Feeding the verified momentum signal into that black box would dilute and possibly
contaminate the very thing we proved. The correct operationalization — standard for multi-strategy
books — is a **rules-based, causal sleeve** combined into the book at the portfolio level.

`arc/research/sleeve.py` builds it fully causally: `position[t] = clip(expanding_zscore(trailing
momentum), ±2)/2 ∈ [−1,1]`, earning `r[t+1]` minus turnover cost. No look-ahead (CI test asserts the
position is invariant to future returns).

## Design call 2: the single-use holdout is reserved for FORWARD paper, not consumed now

A single-use holdout only means something if it was reserved *before* the research touched it. Phase 4
screened on the full sample (2012–2026), including the recent third, so there is **no untouched
in-sample holdout** for `mom3`. Evaluating a "holdout" on already-seen data would be self-deception —
exactly what this project exists to prevent. The genuine single-use holdout is **forward paper**: data
after the current end (~2026-06), which the signal has never seen. The token is reserved for that;
it must not be consumed until paper accumulates out-of-time months.

## Result — gated, net of 2bp costs, DSR deflated by the 45 hypotheses screened

| sleeve | n | annRet | annVol | Sharpe | DSR(45) | maxDD | hit | lev@10% |
|---|---|---|---|---|---|---|---|---|
| **front/mom3** | 159 | +0.44% | 0.68% | **+0.64** | **0.532** | −1.5% | 56% | 14.7× |
| front/mom6 | 156 | +0.29% | 0.67% | +0.43 | 0.254 | −1.5% | 56% | 14.9× |
| front/mom12 | 150 | +0.33% | 0.72% | +0.45 | 0.265 | −1.7% | 55% | 13.8× |
| belly/mom3 | 159 | +1.49% | 4.77% | +0.31 | 0.132 | −8.3% | 52% | 2.1× |
| long/mom3 | 159 | +2.11% | 7.10% | +0.30 | 0.120 | −11.8% | 51% | 1.4× |

**Only `front/mom3` clears the deflated bar (DSR > 0.5).** mom6/mom12 confirm 3 months is the sweet
spot; belly/long momentum have larger absolute returns (less leverage needed) but lower Sharpe and
fail deflation. The edge is specifically short-horizon momentum on the **1Y** rate — the part of the
curve most tied to the monetary-policy cycle.

## Honest assessment

- `front/mom3` is a **real, causal, cost-surviving, deflation-surviving** sleeve — the project's first.
- But it is **low-vol**: hitting a 10% vol contribution needs ~15× leverage (feasible for a 1Y DI
  receiver via futures/swaps, but it is a *small diversifying sleeve*, not a standalone book).
- DSR 0.53 clears the bar but **not by much**; the recent sub-period was the weakest (+0.108 IC). This
  is "promote to PAPER and watch," not "size up aggressively."

## Promotion protocol (next)

1. **Paper**: run `front/mom3` live as a small sleeve (modest leverage), accumulating genuinely
   out-of-time months — the reserved single-use holdout.
2. **Promote** only if the forward Sharpe stays positive and clears deflation on the unseen months.
3. **Book combination**: allocate to the sleeve at the portfolio level alongside the existing overlay,
   sized by its (low) standalone risk and its diversification vs the carry/macro book.

## Delivered

- `arc/research/sleeve.py` — `momentum_sleeve_returns`, `causal_position`, `momentum_signal`,
  `sleeve_stats` (gated/deflated/cost-aware).
- `tests/test_sleeve.py` (CI-native) — causality, profitable-on-momentum, flat-on-noise, cost impact.
- `scripts/momentum_sleeve.py` — the operationalization report above.

No engine behavior changed; no overfit-ensemble integration. The sleeve is a clean, reusable,
honestly-measured component awaiting forward-paper validation.
