"""Phase 7 — run a gated edge's paper loop against the production engine (local-only CLI, multi-strategy).

Engine-touching entrypoint (imports the heavy monolith, so NOT run in CI; the pure ``arc.autonomy`` +
``tests/test_autonomy.py`` carry the CI guarantees). It hosts EITHER booked edge:

  --strategy momentum  -> front/mom3 (FROZEN_SPEC): price momentum on the 1Y receiver (Phase 4.3).
  --strategy nowcast   -> long/neg_nowcast_mom3 (NOWCAST_SPEC): the activity nowcast on the 10Y (Phase 4.4).
  --strategy fiscal    -> hard/pb_mom6 (HARD_PB_SPEC): primary-balance momentum on the sovereign spread (Phase 4.5 re-test).

For each it (1) reads the PIT monthly returns for the spec's instrument, wrapping them with the CI-tested
publication-lag boundary (the only place look-ahead can enter); (2) for the nowcast, builds the strictly
point-in-time activity factor and the oriented signal; (3) runs the deterministic loop month-by-month
(catch-up), persisting an append-only paper ledger PER STRATEGY and emitting a human-approval Proposal.

The forward stream each accrues IS that strategy's reserved single-use holdout. Scoring is a SEPARATE,
human-gated step: ``--verdict`` fires the one-shot ``promotion_verdict`` only at exactly ``eval_at_n``
out-of-time months. Each strategy is a distinct booked trial (distinct hash, its own deflation basis).

Usage:
  python scripts/paper_loop.py --strategy nowcast --book                 # human: book trial + freeze basis
  python scripts/paper_loop.py --strategy nowcast --catch-up             # accrue forward months + proposal
  python scripts/paper_loop.py --strategy nowcast --verdict              # one-shot verdict (consumes holdout)
"""

from __future__ import annotations

import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODEL_DIR = os.path.join(ROOT, "server", "model")
for _k, _v in {
    "ARC_CAUSAL_WINSORIZE": "1", "ARC_FORWARD_TARGET": "1", "ARC_HMM_FILTERED": "1",
    "ARC_BOUNDED_FFILL": "1", "ARC_CAUSAL_RSTAR_REGIME": "1", "ARC_REGIME_PER_SERIES": "1",
    "ARC_FEAT_PER_SERIES": "1", "ARC_REGIME_POINT_IN_TIME": "1", "ARC_PUBLICATION_LAG": "1",
    "ARC_CAUSAL_INTERP": "1", "ARC_CARRY_HARD_SPREAD": "1",
}.items():
    os.environ.setdefault(_k, _v)
sys.path.insert(0, MODEL_DIR)
sys.path.insert(0, ROOT)

EVAL_AT_N = 24         # pre-committed forward sample size for the one-shot verdict (all strategies)
DSR_MIN = 0.50         # pre-committed promotion bar
# per-strategy honest multiple-testing count: momentum screened 45, nowcast 55 (cumulative rounds 1+2),
# fiscal pb_momentum 69 (cumulative through round 3, the hard-spread search that surfaced it).
N_TRIALS = {"momentum": 45, "nowcast": 55, "fiscal": 69}


def _engine_data():
    import macro_risk_os_v2 as eng  # noqa: E402
    print("[paper] initializing engine (PIT returns)...", file=sys.stderr)
    e = eng.ProductionEngine(eng.DEFAULT_CONFIG)
    e.initialize()
    return e.data_layer.ret_df, e.data_layer.monthly


def _build_signal(spec, monthly):
    """The oriented, point-in-time signal that drives the position.

    Returns None for price momentum (the loop derives it from returns). For the nowcast spec it builds the
    activity factor; for the fiscal spec it is the L-month change in the primary balance (oriented POSITIVE:
    improving primary balance -> spread tightens -> sovereign-spread receiver gains). The sleeve applies the
    causal expanding z-score (z_window/clip_z from the spec) to whatever raw signal is returned here."""
    kind = spec.get("kind")
    if kind == "momentum":
        return None
    if kind == "fiscal_momentum":
        pb = monthly.get("primary_balance")
        if pb is None:
            raise SystemExit("[paper] 'primary_balance' not in monthly — cannot run fiscal sleeve")
        return pb.diff(int(spec.get("lookback", 6)))
    if kind == "nowcast":
        from arc.features.nowcast import activity_nowcast, nowcast_surprise
        factor = activity_nowcast(monthly, spec["inputs"], ref_col="ibc_br")
        name = spec["signal"]
        if name == "neg_nowcast":
            return -factor
        if name == "neg_nowcast_mom3":
            return -factor.diff(3)
        if name == "neg_nowcast_surprise":
            return -nowcast_surprise(factor)
        raise SystemExit(f"[paper] unknown nowcast signal '{name}'")
    raise SystemExit(f"[paper] unknown spec kind '{kind}'")


def main() -> None:
    import pandas as pd  # noqa: E402

    from arc.autonomy import (PaperLedger, book_trial, issue_token, promotion_verdict, run_loop,
                              FROZEN_SPEC, NOWCAST_SPEC, HARD_PB_SPEC)
    from arc.autonomy.source import knowledge_time, monthly_return_provider

    ap = argparse.ArgumentParser(description="ARC gated-edge paper loop (multi-strategy)")
    ap.add_argument("--strategy", choices=["momentum", "nowcast", "fiscal"], default="momentum")
    ap.add_argument("--state-dir", default=None, help="default: state/paper/<strategy>")
    ap.add_argument("--asof", default=None, help="ISO date; default = latest knowable month")
    ap.add_argument("--forward-start", default=None,
                    help="ISO month-end research cutoff; only later months count as holdout "
                         "(default = the latest in-sample month at book time)")
    ap.add_argument("--vol-target", type=float, default=0.10)
    ap.add_argument("--pub-lag-days", type=int, default=1)
    ap.add_argument("--book", action="store_true", help="human: book the trial + freeze the deflation basis")
    ap.add_argument("--catch-up", action="store_true", help="run the loop for every knowable forward month")
    ap.add_argument("--verdict", action="store_true", help="one-shot promotion verdict (CONSUMES the holdout)")
    ap.add_argument("--issued-by", default="owner")
    args = ap.parse_args()

    spec = {"momentum": FROZEN_SPEC, "nowcast": NOWCAST_SPEC, "fiscal": HARD_PB_SPEC}[args.strategy]
    inst = spec["instrument"]
    n_trials = N_TRIALS[args.strategy]
    state_dir = args.state_dir or os.path.join(ROOT, "state", "paper", args.strategy)

    ledger = PaperLedger(state_dir)
    ret_df, monthly = _engine_data()
    if inst not in ret_df.columns:
        raise SystemExit(f"[paper] '{inst}' not in ret_df — cannot run {args.strategy}")
    rets = ret_df[inst].dropna()
    provider = monthly_return_provider(rets, pub_lag_days=args.pub_lag_days)

    signal = _build_signal(spec, monthly)
    signal_provider = None
    if signal is not None:
        signal = pd.Series(signal).dropna()
        signal_provider = lambda asof: signal[signal.index <= pd.Timestamp(asof)]  # noqa: E731

    # research cutoff: months at/before the last in-sample return are NOT holdout (default = last data month)
    research_cutoff = (pd.Timestamp(args.forward_start) if args.forward_start
                       else (rets.index[-1] + pd.offsets.MonthEnd(0))).strftime("%Y-%m-%d")

    if args.book:
        h = book_trial(ledger, spec=spec, n_trials=n_trials, sr_std=None, eval_at_n=EVAL_AT_N,
                       dsr_min=DSR_MIN, forward_start=research_cutoff, issued_by=args.issued_by)
        print(f"[paper] booked {args.strategy} ({inst}) {h} | n_trials={n_trials} sr_std=auto(Lo-2002) "
              f"eval_at_n={EVAL_AT_N} dsr_min={DSR_MIN} forward_start={research_cutoff}")

    last_known = knowledge_time(rets.index[-1] + pd.offsets.MonthEnd(0), args.pub_lag_days)
    asof = pd.Timestamp(args.asof) if args.asof else last_known

    def _loop(at, run_id):
        return run_loop(at, provider, ledger, spec=spec, vol_target=args.vol_target,
                        signal_provider=signal_provider, run_id=run_id)

    if args.catch_up:
        out = None
        for mo in [m for m in rets.index if knowledge_time(m, args.pub_lag_days) <= asof]:
            out = _loop(knowledge_time(mo, args.pub_lag_days), "paper-catchup")
        if out is not None:
            print(json.dumps(out["proposal"], indent=2))
        print(f"[paper] {args.strategy} forward months accrued: {ledger.frozen_frame().shape[0]}", file=sys.stderr)
    else:
        print(json.dumps(_loop(asof, "paper")["proposal"], indent=2))

    if args.verdict:
        tok = issue_token(spec, issued_by=args.issued_by)
        try:
            v = promotion_verdict(ledger, tok, asof=asof, spec=spec, run_id="paper-verdict")
            print(f"\n[paper] {args.strategy} PROMOTION VERDICT:")
            print(json.dumps(v, indent=2))
        except Exception as exc:  # noqa: BLE001 — surface the governance refusal verbatim
            print(f"\n[paper] verdict refused (by design): {type(exc).__name__}: {exc}", file=sys.stderr)


if __name__ == "__main__":
    main()
