# ARC Macro — Development Roadmap (state-of-the-art Brazil macro trading OS)

_Last updated 2026-06-20. Grounded in a full-codebase audit (8 subsystem maps + adversarial
leak hunt, 36 agents). Every "where we are" claim below was read from code, not assumed._

## North star

An **autonomous, persistent, self-learning** Brazil macro trading overlay where data, signals, risk,
portfolio and research all run on **one point-in-time spine**; every signal is **gated before it
trades** (CPCV + Deflated Sharpe + carry-neutralized IC + half-sample decay); and an **agent loop**
continuously ingests, researches, monitors, and proposes — with a human approving promotions.

The discipline that must never be sacrificed: **honest measurement first.** We already proved the
historical track record was inflated by leakage; the apparent edge is carry + period-concentrated
regime-timing, not demonstrated stationary alpha. SOTA infrastructure is necessary but does not by
itself create edge — the edge has to be found and must survive the gate.

## Where we are (honest scorecard)

| Dimension | Maturity | One-line state | The gap that matters most |
|---|---|---|---|
| **Measurement / gate** | hardened | The trustworthy ruler: forward labels, Purged/CPCV, PSR/DSR/PBO, carry-neutralized IC, carry-only benchmark, refit-OOS CPCV, half-sample decay. Catches false PASS. | Not wired into the engine as a CI gate; governance ledger + PBO sweep not run in the backtest loop. |
| **Data — point-in-time** | functional | A correct bitemporal store (`arc/data`, append-only, `as_of()`, vintages, publication lag, DuckDB parity) **exists and is tested**. | **The production engine doesn't use it.** `macro_risk_os_v2.DataLayer` reads flat CSVs and shifts by lag; zero `as_of()` calls. Two disconnected worlds. |
| **Connectors / sources** | functional | ~50 series collected (DI/swaps, PTAX/cupom, CDS/EMBI, IPCA/Focus, fiscal, IBC-Br, commodities, US rates/breakevens). | Catalog has only 8 contracts vs ~50 collected; no reusable ANBIMA/B3 adapters; ALFRED vintages unused; no NTN-B real curve / DI1 futures / microstructure. |
| **Features** | functional | Rich set: Z-scores, carry, FX valuation (PPP/BEER/Balassa-Samuelson), CIP, term premium, breakeven decomposition, fiscal premium, equilibrium-r* ML features. | No nowcast/DFM (IBC-Br lags 2m); fixed/ad-hoc betas; no confidence gating. **One real look-ahead found & fixed** (annual→monthly interpolation). |
| **Models / intelligence** | functional | 4-model ensemble (ridge + GBM…) with ElasticNet/Boruta/Stability selection; 5-model composite r*. | Point estimates only (no uncertainty); no regime-conditional weights; no meta-labeling for sizing; batch-only (no online learning). |
| **Regime** | functional | Two-level HMM, expanding window, **filtered** (causal) posteriors, point-in-time a-priori labels, append-only probs. | 12-month refit cadence (no online change-point/BOCPD); the regime-timing edge is non-stationary post-2020. |
| **Portfolio / risk / execution** | functional | Vol-target sizing, score demeaning, gross/net limits, transaction costs, turnover, drawdown overlay; backtest MTM. | No VaR/ES hard limits; backward-looking covariance only; no Black-Litterman; **no execution/paper-fill path**. |
| **Autonomy / persistence / learning / skills** | **prototype** | Dagster assets wrap ingestion. | **No schedules/sensors, no persisted state, no PnL feedback loop, no monitoring/drift/circuit-breakers, no agent/skill layer.** This is the biggest distance from the north star. |

**Summary:** most subsystems are *functional* (they run and are individually reasonable), the measurement
layer is *hardened* (our strongest asset), and **autonomy is a prototype**. The two highest-leverage
structural gaps are (1) the engine ⟂ point-in-time spine disconnect and (2) the absence of an autonomy
layer.

## The edge truth (leak hunt result, 2026-06)

An adversarial as-of-invariance audit of the entire feature/valuation block (PPP, BEER, Balassa-Samuelson,
the 5 r* models incl. ACM PCA + VAR + Kalman/RegimeSwitching, winsorize, HMM standardization, selection/
training) returned a clean and important verdict:

- **The block is far more causal than feared.** The big suspects are all already point-in-time /
  expanding / trailing-window and were **refuted as leaks** by independent skeptics (e.g. ACM PCA &
  VAR run on strictly trailing `[i-60, i]` windows; r* composite uses `compute_causal` by default;
  winsorize defaults to causal; HMM standardizes only `obs.loc[:asof]`).
- **One real residual look-ahead, now fixed:** annual→monthly **linear interpolation** of
  fundamentals (`ppp_factor`, `gdppc_ratio`, `ca_pct_gdp`, `trade_openness`) pulled the *next* (future)
  annual anchor into intermediate months. Replaced with a causal step-hold (`causal_annual_to_monthly`,
  toggle `ARC_CAUSAL_INTERP`). It mostly affects FX-valuation features, so it is **not** the driver of
  the rates-book H1≫H2 decay.
- **Conclusion:** the H1≫H2 IC decay is **genuine non-stationarity / period-concentrated regime-timing**
  (2015–2020 Brazil crisis era vs post-2021), not a hidden feature leak. **Honest forward IC ≈ the
  second-half level (~0.10–0.20; `hard` best ~0.34).** There is still **no deflation-surviving stationary
  edge beyond carry.** That is the problem the strategy work must solve.

## Roadmap — phased, dependency-ordered

Phases 0–2 (foundations, bitemporal `as_of` library, honest measurement) are **done**. The track below
takes us from "honest ruler + disconnected parts" to the autonomous SOTA system.

### Phase 3 — Single point-in-time spine *(critical path; unlocks everything)*
Wire the engine to `arc.data`. Until this is done, every backtest uses static snapshots and the as_of
infra is dead weight.
- Migrate `server/model/data/*.csv` into the bitemporal store via `csv_bridge` with real `knowledge_time`.
- Replace `DataLayer.load_series` CSV reads + manual `shift()` with `store.as_of(t)`; rebuild features
  per step from the as-of vintage.
- Add an **as-of-invariance CI gate**: build features twice (trimmed at each `asof(t)` vs full) and
  assert past values are byte-identical — leakage becomes structurally impossible, not patched.
- Freshness gating in `step()`; revision handling via append-only vintages.

### Phase 4 — Honest edge search *(the actual alpha problem)*
With the spine + gate, hunt **orthogonal-to-carry, stationary** signals, each promoted only if it
survives CPCV + DSR + half-sample decay. Treat H2 (~0.1–0.2) as the bar to beat, not the inflated H1.
- **Round 1 (done):** 45 pre-registered macro + momentum hypotheses → only `front/mom3` survived
  (operationalized as a gated sleeve, Phase 4.3; awaiting forward paper).
- **Round 2 (done, 4.4):** Nowcast / Dynamic Factor (mixed-frequency, strictly PIT) → **a 2nd gated
  candidate** (activity nowcast on belly/long; cnIC ~0.19–0.23, H2>H1, survives carry+market
  neutralization). Caveats: ~one bet, fragile to inputs, orthogonality-to-momentum unmeasured →
  candidate, not promotion. Real-curve track has **no historical data** (single 2024 snapshot) → deferred
  pending NTN-B/breakeven collection. See `docs/PHASE4_4_NOWCAST_EDGE_2026-06.md`.
- **Round 3 (done, 4.5):** `hard` sovereign-spread search (17 hypotheses, true spread carry) → the
  headline refit-OOS ~0.33 was **carry-in-disguise** (confirmed dead); lone survivor `pb_momentum`
  (fiscal) is borderline + lookback-fragile → **no new sleeve**. See `docs/PHASE4_5_BATCH_HARD_CONNECTORS_2026-06.md`.
- **Round 4 (done, 4.5):** NTN-B **real curve** — now gateable (connector collected 259mo of real yields)
  → **no survivors** (real-rate levels decay H1≫H2; breakevens fail).
- **Connectors (done, 4.5):** new tested adapters for NTN-B (Tesouro), CFTC COT (BRL positioning), BCB
  flows (IDP/portfolio); NTN-B (259mo) + CFTC (879 weekly) collected live; flows pending (BCB API 502).
- Still open: regime-*conditional* alpha (only if OOS); collect BCB flows when the API recovers, then gate
  positioning; re-test `pb_momentum` with more data + a longer global-risk control.

### Phase 5 — Intelligence upgrades
- Probabilistic forecasts (credible intervals) → confidence-scaled sizing.
- Meta-labeling (conviction classifier) for position sizing.
- Online/adaptive selection & weights (warm-start, rolling refit) instead of batch.
- r* credible intervals from the Kalman covariance.

### Phase 6 — Portfolio & risk SOTA
- VaR/ES hard pre-trade gates; DCC-GARCH / factor covariance (forward-looking correlation).
- Black-Litterman blend of risk-parity + macro priors (r*, carry, real-rate guidance).
- Pre-trade liquidity gate (days-to-liquidate under stress); order FSM + paper-fill simulator.

### Phase 7 — Autonomy, persistence, learning & skills *(the "autonomous self-learning" ask)*
**7.1–7.4 DONE** (`arc/autonomy/`, `docs/PHASE7_AUTONOMY_SPINE_2026-06.md`): the persistent, honest
**paper loop** for the one gated edge (`front/mom3`) — the bridge from "validated edge" to a system that
operates, persists, accrues the reserved single-use holdout, and feeds back. Built adversarial-first (a
governance/look-ahead workflow caught real bugs — expanding-z recompute leak, `sleeve_stats` can't pass
`sr_std`, in-memory governance resets — before any code). Delivered:
- **Persistence:** append-only, checksummed, idempotent JSONL ledger (mirrors the bitemporal store's
  discipline; durable governance: trial bookings, deflation basis, holdout consumption, verdicts).
- **Two-stream architecture:** the breaker flattens only `live`; the verdict scores only the unbreakered
  `frozen` stream (no left-tail truncation, no under-deflation, no re-peeking).
- **Scheduling:** `scripts/paper_loop.py` (`--book`/`--catch-up`/`--verdict`) + a Dagster monthly schedule.
- **Monitoring & feedback:** drift (PSI, non-binding), circuit breaker (live-only), and a one-shot,
  pre-committed (`forward_start`/`eval_at_n`), NaN-fatal, deterministic-on-read **promotion verdict** that
  reproduces the gate's exact deflation. Human-gated; agents cannot self-issue the holdout token.
- 24 CI-native invariant tests (159 pytest green); proven end-to-end against the engine (honest 0-holdout
  state today — no out-of-time data exists yet).

**Still deferred (Phase 8 institutional wrap):** Postgres/Temporal/LangGraph; Claude-driven agents (the
loop is the deterministic skeleton with clean skill seams); model inventory/MLflow.

### Phase 8 — Live/paper trading & governance
Paper-trade the gated book end-to-end; reconcile fills/slippage; single-use holdout token for the one
honest live test; promotion only through the ledger with human sign-off.

## Immediate next actions
1. **(done this round)** Fix the interpolation look-ahead (`causal_annual_to_monthly`) + as-of-invariance tests.
2. Measure the interpolation fix's IC impact (expected small, FX-valuation features) on the next full gate run.
3. **Start Phase 3** — wire `DataLayer` to `arc.data.as_of` behind a toggle and stand up the as-of-invariance CI gate. This is the highest-leverage move and makes the whole "no leakage" claim structural.
