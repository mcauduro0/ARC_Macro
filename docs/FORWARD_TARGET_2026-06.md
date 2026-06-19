# Forward-Target Alignment — Measured Impact (read skeptically)

**Date:** 2026-06-19
**Change:** the alpha models trained on a *contemporaneous* target (`features[t] → return[t]`)
but were deployed to predict the next period. Fixed to a **forward** target via
`arc.eval.forward_returns` (`features[t] → return over (t, t+1]`), toggleable with
`ARC_FORWARD_TARGET` (default 1). Measured with `scripts/measure_causal_impact.py`
(`ARC_MEASURE_VAR=ARC_FORWARD_TARGET`) on the same live data snapshot.

## Result

| metric | contemporaneous (OFF) | forward (ON) | delta |
|---|---:|---:|---:|
| overlay Sharpe | −0.30 | 3.91 | +4.21 |
| overlay total return | −5.74% | +270.3% | +276pp |
| overlay max drawdown | −5.47% | −1.29% | +4.18pp |
| overlay win rate | 47.8% | 86.6% | +38.8pp |
| mean IC | −0.076 | **+0.417** | +0.494 |

Per-instrument IC (forward): `front −0.013, belly +0.639, long +0.626`.

## ⚠️ Do NOT trust these numbers

A monthly macro IC of **0.6+** is not a credible signal edge — it is the same implausible
regime the audit flagged (the historical 0.74–0.76 IC trail that later collapsed to ~0). The
forward-target change is **methodologically correct** (the contemporaneous target was a real
bug), but the eye-popping result is almost certainly an artifact, for two reasons:

1. **Carry-dominance.** belly/long carry features mechanically predict fixed-income returns
   (carry *is* the expected return absent price moves). High IC there is not skill; it is
   carry-harvesting wearing a signal costume. front (little carry) stays ~0.
2. **Residual feature-construction leaks, now EXPOSED.** Only the winsorize look-ahead has
   been fixed so far. The equilibrium r\* full-history rebuild (eq-1/eq-3) and unbounded
   feature ffill (feat-3) are still present; with a contemporaneous target their leakage was
   partly masked, but a forward-aligned target lets any feature that peeks at t+1 inflate IC
   directly. The jump from −0.076 to +0.42 is suspiciously consistent with that.

## What has to happen before believing any of this

- Fix the remaining feature leaks (equilibrium rolling/point-in-time; bounded, lag-aware ffill).
- Run the honest gauntlet from `arc.eval`: **CPCV + embargo**, **Deflated Sharpe** (against the
  real trial count in the `GovernanceLedger`), **PBO**, and **carry-neutralized IC** (regress out
  carry before measuring signal IC). On a single 129-month sample, a Sharpe of 3.9 should
  deflate hard.
- Compare against a **carry-only benchmark**: if the overlay doesn't beat naive carry after
  costs, it's carry, not alpha.

## Verdict

The forward-target fix is kept (it is correct). Its measured uplift is treated as **unverified
and probably leakage/carry**, not as discovered alpha. This is the system working as designed:
the honest-measurement layer must now deflate this before it informs any sizing.
