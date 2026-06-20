"""Phase 7 — run the front/mom3 paper loop against the production engine's returns (local-only CLI).

This is the engine-touching entrypoint (imports the heavy monolith, so it is NOT run in CI; the pure
``arc.autonomy`` package + ``tests/test_autonomy.py`` carry the CI guarantees). It:
  1. initializes the engine and reads the PIT monthly return for the 1Y receiver (``ret_df["front"]``);
  2. wraps it with the CI-tested publication-lag boundary (``monthly_return_provider``) — the single
     place look-ahead can enter — so a month-M return is invisible until M+lag;
  3. runs the deterministic loop month-by-month (catch-up), persisting an append-only paper ledger and
     emitting a human-approval Proposal for the latest month.

The forward stream this accumulates IS the reserved single-use holdout. Scoring it is a SEPARATE,
human-gated step: ``--verdict`` (with a booked deflation basis + a human-issued token) fires the
one-shot ``promotion_verdict`` only when exactly ``eval_at_n`` out-of-time months have accrued.

Usage:
  python scripts/paper_loop.py --book                  # human: book the trial + freeze the deflation bar
  python scripts/paper_loop.py --catch-up              # accrue forward months + emit the latest proposal
  python scripts/paper_loop.py --verdict               # one-shot promotion verdict (consumes the holdout)
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

DEFAULT_STATE = os.path.join(ROOT, "state", "paper")
N_TRIALS = 45          # Phase 4 multiple-testing count — the honest deflation penalty
EVAL_AT_N = 24         # pre-committed forward sample size for the one-shot verdict
DSR_MIN = 0.50         # pre-committed promotion bar (the in-sample screen cleared DSR(45)=0.53)


def _front_returns():
    import macro_risk_os_v2 as eng  # noqa: E402
    print("[paper] initializing engine (PIT returns)...", file=sys.stderr)
    e = eng.ProductionEngine(eng.DEFAULT_CONFIG)
    e.initialize()
    ret = e.data_layer.ret_df
    if "front" not in ret.columns:
        raise SystemExit("[paper] 'front' not in ret_df — cannot run the sleeve")
    return ret["front"].dropna()


def main() -> None:
    import pandas as pd  # noqa: E402

    from arc.autonomy import PaperLedger, book_trial, issue_token, promotion_verdict, run_loop
    from arc.autonomy.source import knowledge_time, monthly_return_provider

    ap = argparse.ArgumentParser(description="ARC front/mom3 paper loop")
    ap.add_argument("--state-dir", default=DEFAULT_STATE)
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

    ledger = PaperLedger(args.state_dir)
    front = _front_returns()
    provider = monthly_return_provider(front, pub_lag_days=args.pub_lag_days)

    # The research cutoff: months at/before the last in-sample return are NOT holdout. Default = the
    # latest data month at book time, so genuinely-new months (and only those) accrue to the holdout.
    research_cutoff = (pd.Timestamp(args.forward_start) if args.forward_start
                       else (front.index[-1] + pd.offsets.MonthEnd(0))).strftime("%Y-%m-%d")

    if args.book:
        h = book_trial(ledger, n_trials=N_TRIALS, sr_std=None, eval_at_n=EVAL_AT_N,
                       dsr_min=DSR_MIN, forward_start=research_cutoff, issued_by=args.issued_by)
        print(f"[paper] booked trial {h} | n_trials={N_TRIALS} sr_std=auto(Lo-2002) "
              f"eval_at_n={EVAL_AT_N} dsr_min={DSR_MIN} forward_start={research_cutoff}")

    # the latest knowable month-end as-of "now" (or the explicit --asof)
    last_known = knowledge_time(front.index[-1] + pd.offsets.MonthEnd(0), args.pub_lag_days)
    asof = pd.Timestamp(args.asof) if args.asof else last_known

    if args.catch_up:
        months = [m for m in front.index if knowledge_time(m, args.pub_lag_days) <= asof]
        out = None
        for m in months:
            run_asof = knowledge_time(m, args.pub_lag_days)
            out = run_loop(run_asof, provider, ledger, vol_target=args.vol_target, run_id="paper-catchup")
        if out is not None:
            print(json.dumps(out["proposal"], indent=2))
        print(f"[paper] forward months accrued: {ledger.frozen_frame().shape[0]}", file=sys.stderr)
    else:
        out = run_loop(asof, provider, ledger, vol_target=args.vol_target, run_id="paper")
        print(json.dumps(out["proposal"], indent=2))

    if args.verdict:
        tok = issue_token(issued_by=args.issued_by)
        try:
            v = promotion_verdict(ledger, tok, asof=asof, run_id="paper-verdict")
            print("\n[paper] PROMOTION VERDICT:")
            print(json.dumps(v, indent=2))
        except Exception as exc:  # noqa: BLE001 — surface the governance refusal verbatim
            print(f"\n[paper] verdict refused (by design): {type(exc).__name__}: {exc}", file=sys.stderr)


if __name__ == "__main__":
    main()
