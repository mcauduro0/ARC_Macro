# Causal-Winsorize Leakage Fix — Measured Backtest Impact

**Date:** 2026-06-19
**How:** `scripts/measure_causal_impact.py` ran the v2 backtest twice on freshly collected
live data (91 series) — once with the **legacy full-sample winsorize** (look-ahead) and once
with the **causal/point-in-time winsorize** (the fix in PRs #6/#8), toggled via
`ARC_CAUSAL_WINSORIZE`. Same data, same config, only the winsorize differs.

## Result

| metric | legacy (look-ahead) | causal (fix) | delta |
|---|---:|---:|---:|
| overlay Sharpe | 0.25 | **−0.30** | −0.55 |
| overlay total return | +9.40% | −5.74% | −15.14pp |
| overlay max drawdown | −4.98% | −5.47% | −0.49pp |
| overlay win rate | 57.3% | 47.8% | −9.5pp |
| mean IC | +0.0018 | **−0.0762** | −0.078 |

Per-instrument IC — legacy: `front −0.023, belly −0.065, long +0.093`; causal: `front −0.108, belly −0.196, long +0.076`.

## Interpretation (honest)

Removing the full-sample winsorize look-ahead **flips the overlay from marginally positive
(Sharpe 0.25) to negative (Sharpe −0.30)** and turns mean IC negative. A material part of the
previously-reported "edge" was a **leakage artifact**: clipping each feature/return to
quantiles computed over the *whole* sample (including the future) quietly stabilized the
signals in-sample.

This empirically confirms the audit (`DIAGNOSTIC_2026-06.md`): **the current signal stack has
no demonstrable out-of-sample edge once look-ahead is removed.** The positive carry/beta of
the CDI overlay is a separate matter; the *signal alpha* is not there in this configuration.

## Caveats

- Single backtest on one freshly-collected data snapshot; absolute numbers differ from the
  committed `output_final.json` (different vintage/config). The robust takeaway is the
  **direction and magnitude of the leakage impact**, not the exact levels.
- This isolates ONLY the winsorize fix. The bigger statistical bug — training on a
  contemporaneous target instead of a forward return — is addressed separately (arc.eval
  forward labels + CPCV + Deflated Sharpe gating).

## Implication for the roadmap

Treat the system as **carry-harvesting, not signal-alpha**, until signals are rebuilt and
validated honestly: forward-aligned targets, purged/embargoed CPCV, Deflated Sharpe / PBO
gating, and a locked holdout (the `arc.eval` library). Do not size to the legacy track record.
