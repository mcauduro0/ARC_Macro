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
- Nowcast / Dynamic Factor (mixed-frequency Kalman) to kill the IBC-Br 2-month blindspot.
- Regime-*conditional* alpha (separate models/weights per regime) — only if it passes out-of-sample.
- Investigate `hard` (sovereign-spread) — its refit-OOS IC (~0.33) is the most plausible genuine residual.

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
- **Persistence:** Postgres for the governance ledger (every trial), run manifests, model inventory,
  realized PnL — state that survives restarts and accumulates learning.
- **Scheduling/sensors (Dagster/Temporal):** daily ingest, regime-change sensor, freshness gates;
  `research_daily` (recompute IC, log trials, propose refit on decay) and `portfolio_monthly` workflows.
- **Agent/skill layer (`arc-agents`):** a Research→Signal→Risk→Portfolio→Execution loop (Claude-driven)
  that proposes signals/allocations as **gated, human-approved** promotions — never auto-trading
  un-gated alpha. Skills = reusable, audited tools the agent composes.
- **Monitoring & feedback:** drift detectors (PSI/KS, IC decay), circuit breakers, PnL reconciliation
  feeding back into the learning loop.

### Phase 8 — Live/paper trading & governance
Paper-trade the gated book end-to-end; reconcile fills/slippage; single-use holdout token for the one
honest live test; promotion only through the ledger with human sign-off.

## Immediate next actions
1. **(done this round)** Fix the interpolation look-ahead (`causal_annual_to_monthly`) + as-of-invariance tests.
2. Measure the interpolation fix's IC impact (expected small, FX-valuation features) on the next full gate run.
3. **Start Phase 3** — wire `DataLayer` to `arc.data.as_of` behind a toggle and stand up the as-of-invariance CI gate. This is the highest-leverage move and makes the whole "no leakage" claim structural.
