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
  (fiscal) was borderline + lookback-fragile → no sleeve at the time. See `docs/PHASE4_5_BATCH_HARD_CONNECTORS_2026-06.md`.
- **Round 4 (done, 4.5):** NTN-B **real curve** — now gateable (connector collected 259mo of real yields)
  → **no survivors** (real-rate levels decay H1≫H2; breakevens fail).
- **Round 5 (done, 4.5b):** **positioning & flows** (CFTC BRL net-spec + IDP/portfolio flows) on fx + the
  rates risk-channel, 14 hypotheses → **no survivors** (the one tease, `fx/portfolio_flow_z`, is H1≫H2
  non-stationary). See `docs/PHASE4_5_PB_RETEST_POSITIONING_2026-06.md`.
- **`pb_momentum` RE-TEST (done, 4.5b) → promoted to a 3rd candidate sleeve.** v1's only blocker was an
  inconclusive global-risk control (US-HY too short, n=35). The v2 re-test with a LONG panel
  (VIX+NFCI+US-term+Δcds, n=172) shows it is **not** risk-on/off (IC 0.116→0.115 after neutralization),
  H2 +0.198, orthogonal to both edges, predictive. Caveats remain (diff 9/12 collapse; mid-sample
  concentration), so it is **booked as a forward-paper candidate (`fiscal_hard`), not promoted to live.**
- **Connectors (done, 4.5/4.5b):** tested adapters for NTN-B (Tesouro), CFTC COT (BRL positioning), BCB
  flows (IDP/portfolio); NTN-B (259mo) + CFTC (879 weekly) collected; **BCB flows (376mo each) recovered
  via a provenance-verified IPEADATA fallback while the SGS API is 502** (never a silent substitution).
- Still open: regime-*conditional* alpha (only if OOS); the three booked edges accrue forward paper toward
  the one-shot verdict (~2028-06) — now via an **autonomous monthly Task Scheduler job** (Phase 7.3). BCB SGS
  has recovered, so `collect_flows.py` auto-uses the canonical source again; `BOP_CURRENT` corrected to the
  current account (SGS 22701).

### Phase 5 — Intelligence upgrades
**First increment done (`docs/PHASE5_INTELLIGENCE_2026-06.md`):** `arc/intelligence/` — causal, leakage-safe
(36 CI tests) **uncertainty** (split-conformal credible intervals + predictive vol), **confidence-scaled
sizing**, and **meta-labeling** (López de Prado P(correct) for sizing). Built as *measured* infrastructure,
not an alpha claim. `scripts/measure_intelligence.py` (deflated, leverage-invariant FLAT-vs-intelligence):
**no broad sizing edge** — momentum_front & fiscal_hard show no improvement; `nowcast_long` +
conformal-width confidence scaling is a **tentative in-sample** gain (deflated DSR 0.549→0.609) to confirm
on forward paper, not a result. Also fixed `BOP_CURRENT` (SGS 22707 trade balance → **22701** current
account, IPEADATA+live-value verified).
**Second increment done (`docs/PHASE5B_FORWARD_SIZING_RSTAR_2026-06.md`):** (i) **r\* credible intervals** —
`StateSpaceRStar` now exposes the Kalman filtered posterior variance → `credible_intervals()` (latest r\* 8.69%
± 0.50, 95% CI [7.72, 9.67]); (ii) **online/adaptive weights** (`arc/intelligence/online_weights.py`, EWMA-Sharpe
+ inverse-variance, causal) — **measured: NO improvement**, EQUAL weight wins (deflated DSR 0.986 vs −0.095/−0.150),
equal-weight stays baseline; (iii) **nowcast confidence-sizing PRE-REGISTERED** for forward confirmation
(`arc/autonomy/forward_experiments.py` + `scripts/confirm_sizing_forward.py`) — deterministic rule + criterion
committed to git, harness reports `NOT READY 0<24` today (nothing judged in-sample, spine untouched); (iv)
**BOP_CURRENT rebuilt** (re-collected as the current account, SGS 22701) — impact measured: `Z_bop` corr 0.80 but
21% sign-flips vs the old trade-balance mapping (meaning corrected).
- **Online *feature* selection done (`docs/PHASE6_PORTFOLIO_RISK_2026-06.md`):** `arc/intelligence/online_selection.py`
  (rolling ElasticNet importance + stability selection, causal) — **measured: NO improvement** over BATCH
  (Δ deflated-IC +0.000; ONLINE churns the set, H1≫H2 non-stationary). BATCH stays baseline.
- Still open: confirm the nowcast confidence-sizing hypothesis when 24 forward months accrue (~2028-06).

### Phase 6 — Portfolio & risk SOTA — **DONE (`docs/PHASE6_PORTFOLIO_RISK_2026-06.md`)**
Built pure, causal, CI-tested (84 tests) + measured: `arc/risk/var_es.py` (VaR/ES + `pretrade_var_gate`),
`arc/risk/covariance.py` (EWMA + GARCH(1,1) + Engle DCC(1,1), PSD, forward-looking), `arc/portfolio/black_litterman.py`,
`arc/execution/paper_fill.py` (order FSM + paper-fill sim w/ slippage/liquidity/cost). Honest measurement
(`scripts/measure_portfolio_risk.py`): **no weighting scheme beats EQUAL on deflated DSR** (best Black-Litterman-EWMA
lifts Sharpe 0.78→0.94 + cuts maxDD but Δ deflated DSR only +0.006 < 0.05) → risk/portfolio tools are construction
tooling, not demonstrated edge; EQUAL stays baseline. VaR/ES gate + execution drag (~0.08%/yr @ 2bp) verified.
- Still open: pre-trade *liquidity*/days-to-liquidate stress gate (the fill sim has the liquidity cap; a stress
  scenario layer is the natural extension); wiring VaR/ES + cov as live pre-trade gates in the paper loop.

### Phase 7 — Autonomy, persistence, learning & skills *(the "autonomous self-learning" ask)*
**7.1–7.4 DONE** (`arc/autonomy/`, `docs/PHASE7_AUTONOMY_SPINE_2026-06.md`): the persistent, honest
**paper loop**, now multi-strategy — it hosts **three booked candidate sleeves** (`front/mom3`,
`nowcast long`, `fiscal_hard`/pb_momentum), each a distinct trial with its own hash, deflation basis, and
single-use forward holdout. **7.2 (done, `docs/PHASE7_2_SCORING_RUNBOOK_2026-06.md`):** the loop scores
ALL booked edges in one pass via `scripts/score_both_edges.py` (non-consuming readiness by default); today
all three correctly REFUSE (`HoldoutNotReadyError 0<24`) — 0 out-of-time months exist, no fabrication.
**7.3 (done, `docs/PHASE7_3_AUTONOMOUS_ACCRUAL_2026-06.md`):** an always-on monthly accrual cycle
(`scripts/monthly_accrual.py`: best-effort data refresh → flows → catch-up all 3 → durable
`state/paper/accrual_log.jsonl`), installable via Windows Task Scheduler or the Dagster schedule; signal
construction consolidated into one shared `arc.autonomy.build_signal` (a per-file copy had drifted and
would have run `fiscal_hard` with price momentum). A `fiscal_hard` recency re-examination
(`scripts/reexamine_fiscal_hard.py`) is an **orange flag** — last-36m carry-neutral IC negative (−0.170),
`recency_ok=False`; kept as a forward-paper candidate (the OOS verdict will adjudicate), watched.
This is the bridge from "validated edge" to a system that operates, persists, accrues the reserved
single-use holdout, and feeds back. Built adversarial-first (a
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
- CI-native invariant tests incl. the three-edge registry + fiscal-sleeve equivalence + shared build_signal
  + SGS-recovery routing (211 pytest green); proven end-to-end against the engine (honest 0-holdout today).

**Still deferred (Phase 8 institutional wrap):** see the concrete plan in
`docs/PHASE8_INSTITUTIONAL_WRAP_PLAN_2026-06.md` (Postgres-backed ledger + bitemporal store; Temporal durable
workflows wrapping `run_loop`; Claude-driven agents at the existing skill seams; MLflow). Deferred **by design**:
needs external services (Postgres/Temporal) not provisioned here; the spine already exposes the clean seams so
it is a backend swap, not a rewrite.

### Phase 8 — Institutional wrap & live/paper governance *(deferred, planned)*
`docs/PHASE8_INSTITUTIONAL_WRAP_PLAN_2026-06.md`. Postgres ledger/store (dual-backend parametrized invariant
tests as the acceptance net); Temporal durable orchestration; Claude agents (propose-only → human-approve)
that can promote ONLY through the existing gate + single-use forward holdout; MLflow registry. Plumbing +
autonomy ergonomics — must not manufacture alpha.

### Phase 7.4 — co-pilot (human-in-the-loop) + statistical-power audit & pooled holdout *(done)*
`docs/PHASE7_4_COPILOT_AND_POWER_2026-06.md`. **(b) Co-pilot:** a third `operator` stream
(`arc/autonomy/copilot.py`, `scripts/copilot.py`) — the loop PROPOSES, the human APPROVES/OVERRIDEs/SKIPs
(immutable `OperatorDecision`), feeding a durable forward track record — while the scored `frozen` holdout
stays **byte-identical** (CI-proven). Revision-robust (catches the anti-repaint `DataRevisionError`, never
repaints); verified on the engine (proposes momentum -0.61, nowcast +0.25 for 2026-07). **(a) Power:**
`scripts/measure_statistical_power.py` — the 3 sleeves are nearly independent (avg|corr| 0.11, **K_eff 2.92**),
so a pre-registered equal-weight **pooled forward holdout** (`POOL_SPEC`, `arc/autonomy/pool.py`,
`scripts/pre_register_pool.py`) reaches a verdict at **eval_at_n=12** common forward months — **~1 year sooner**
than a single sleeve — IF several sleeves carry real edge (booked `bfe8ee59`, blocked 0<12 today). Honest
nulls: more in-sample/macro history does NOT accelerate the forward verdict; the DI_5Y 2010–2012 gap is
backtest-quality only (documented, NOT patched with synthetic data). Verdicts hardened to FAIL degenerate
(near-zero-variance) forward streams. 22 new tests, 387 green.

## Immediate next actions
1. **Accrual is LIVE** — the 3 sleeves accrue monthly (Task Scheduler, next run 2026-07-02). The owner can now
   operate as a **co-pilot**: `python scripts/copilot.py --propose` then `--decide`. As forward months land:
   re-run `reexamine_fiscal_hard.py` + `confirm_sizing_forward.py`; the **pooled** holdout can verdict at 12
   common months (~2027-07, ~1y before the singles).
2. **Phases 5–6 complete** (intelligence + portfolio/risk/execution, all measured; baselines not beaten — honest).
   Optional: wire VaR/ES + covariance as live pre-trade gates in the paper loop; add a liquidity-stress gate.
3. **Phase 8** when Postgres/Temporal are provisioned — follow the plan doc; keep the invariant suite green.
