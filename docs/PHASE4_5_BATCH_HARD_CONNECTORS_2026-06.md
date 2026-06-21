# Phase 4.5 — parallel batch: multi-strategy scheduling, `hard` edge search, 3 connectors, real-curve gate

Executed as a massive parallel batch (a 5-agent build workflow on disjoint files, then integration +
engine runs + adversarial verification). Net: **zero new promotable edges**, but major infrastructure and
honest-measurement value — two whole signal families (`hard` sovereign spread, the NTN-B real curve) were
**properly tested and ruled out**, three new data connectors were built/tested, and two datasets collected.

## (a) Multi-strategy Dagster scheduling — done

`orchestration/dagster/paper_schedule.py` now factory-generates an asset + job + monthly schedule
(2nd of month, 06:00 BRT) **per booked strategy in `arc.autonomy.spec.SPECS`** — currently
`momentum_front` and `nowcast_long`, each with its own state dir and `signal_provider`. The engine import
stays guarded (lazy), so `defs` loads in CI without the monolith (verified). New strategies added to
`SPECS` get scheduling for free.

## (b) `hard` sovereign-spread edge search — the "0.33" was carry; no robust edge

The roadmap flagged `hard` refit-OOS ~0.33 as the most plausible residual. `scripts/edge_search_hard.py`
screened 17 pre-registered, economically-motivated hypotheses (sovereign credit, fiscal, external, global
risk, momentum, nowcast-on-hard), carry-neutralized against the **TRUE spread carry** (`embi/10000/12`;
corr with the legacy cupom carry = −0.12, confirming the old mismatch).

- **16 of 17 FAIL.** The sovereign-credit and momentum signals show the H1≫H2 decay signature; the
  headline 0.33 is **confirmed carry-in-disguise**, not alpha.
- **1 survivor: `hard/pb_momentum`** (primary-balance momentum) — cnIC +0.114, H2 +0.198 > H1, refit-OOS
  +0.157, but OOSmin +0.004 (razor-thin), and 1 of 69 cumulative hypotheses (~3 false positives expected).
- **Adversarial verification (`scripts/verify_hard_pb.py`): borderline, NOT promotable.** It is
  economically clean and **orthogonal to both existing edges** (corr +0.10 with front/mom3, −0.00 with the
  nowcast; partial IC +0.10/+0.12), with a predictive lag structure — but it is **not lookback-robust**
  (diff(3)/diff(6) pass; **diff(9)/diff(12) collapse**, OOSmin −0.33/−0.21), **period-concentrated**
  (thirds [+0.16, +0.30, +0.08]), and the global-risk control was inconclusive (n=35<40, US HY history too
  short). It does not clear the bar that front/mom3 and the nowcast cleared. **No third sleeve booked**;
  flagged as a fiscal hypothesis to re-test when more data exists.

## (c) Data connectors — built, tested, two collected live

Three new adapters (pure-parse + lazy-network, CI-native fixture tests; 21 tests green), wired into the
catalog (9→14 contracts) and the ingest registry:

| series | source | history collected | status |
|---|---|---|---|
| `NTNB_REAL_5Y` / `NTNB_REAL_10Y` | Tesouro Transparente CKAN | **259 mo (2004-12 → 2026-06)** | live OK |
| `CFTC_BRL_NET_SPEC` | CFTC COT (Socrata 6dca-aqww, code 102741) | **879 weekly (1995 → 2026)** | live OK |
| `IDP_FLOW` / `PORTFOLIO_FLOW` | BCB SGS (22885 / 22924) | — | built+tested; BCB API 502 (transient) |

`scripts/collect_connectors.py` fetches each and persists to the engine data dir. NTN-B real yields
(1.7%–10.9% real, economically sane) finally make the real-curve track gateable.

Side-finding (not fixed here): `server/model/data_collector.py` maps `BOP_CURRENT` to SGS 22707, which is
the **trade balance**, not the current account — worth a separate correction.

## (d) Real-curve gate (unlocked by (c)) — no edge

With the 259-month NTN-B history, `scripts/edge_search_realcurve.py` gated 9 real-rate / breakeven /
real-slope hypotheses (breakeven = nominal DI − NTN-B real). **NO SURVIVORS** — the real-rate levels show
the H1≫H2 decay (non-stationary), breakevens fail. The real curve adds no deflation-surviving edge beyond
carry. The value of collecting the data was to be able to say this **definitively**, not leave it untested.

## Honest bottom line

The book still has exactly **two** gate-passing edges (front/mom3 momentum + the activity nowcast), both
awaiting forward paper. This batch did not add a third — but it eliminated two plausible-looking families
with proper measurement, built durable connectors, and collected real datasets. Ruling things out cleanly
is the job. 191 pytest green.

## Delivered

- `orchestration/dagster/paper_schedule.py` — per-strategy assets/jobs/schedules from `SPECS`.
- `arc/data/adapters/{tesouro_ntnb,cftc_cot,bcb_flows}.py` + tests; catalog + ingest registry wiring.
- `scripts/{edge_search_hard,verify_hard_pb,collect_connectors,edge_search_realcurve}.py`.
