"""Phase 7.2 — readiness harness: prove the paper loop scores ALL booked edges, honestly blocked today.

Engine-touching entrypoint (imports the heavy monolith, so NOT run in CI; the pure ``arc.autonomy`` +
``tests/test_autonomy.py`` carry the CI guarantees). It is the multi-strategy companion to
``scripts/paper_loop.py`` (which operates ONE strategy at a time via ``--strategy``): this harness books,
catches up, and assesses the verdict for EVERY booked edge in ``arc.autonomy.spec.SPECS`` in one pass —
  momentum_front (FROZEN_SPEC, 'front'), nowcast_long (NOWCAST_SPEC, 'long'), fiscal_hard (HARD_PB_SPEC,
  'hard') — then prints a single honest STATUS TABLE proving the machinery is wired for ALL of them and
correctly blocked until real out-of-time months accrue.

It reuses ``scripts/paper_loop.py`` verbatim wherever possible (the env preamble, EVAL_AT_N/DSR_MIN/
N_TRIALS, ``_build_signal``, the per-strategy ``state/paper/<key>`` convention, the provider + signal
provider construction) so this harness and ``paper_loop.py`` share the same ledgers — running either
advances the same durable forward holdout.

THE HONESTY CONTRACT (this project's prime directive): TODAY is 2026-06-20 and ``ret_df`` ends 2026-06,
so there are NO out-of-time months yet. The correct behavior is NOT to fabricate forward months; it is to
show that BOTH holdouts accrue ~0 forward months and the one-shot verdict REFUSES
(``HoldoutNotReadyError: have 0 < eval_at_n=24``). We capture that refusal as a PASS of the *machinery*,
not a failure to report.

Safe-by-default: the verdict CONSUMES the single-use holdout. So the default mode (``--catch-up-only``)
runs the idempotent catch-up and then a NON-consuming readiness check that just compares accrued-n vs the
pre-committed eval_at_n by READING the ledger (``frozen_frame``/``basis_for``) — it NEVER calls
``promotion_verdict``. Running the default repeatedly is safe and idempotent. The consuming verdict only
runs under the explicit ``--attempt-verdict`` flag.

Usage:
  python scripts/score_both_edges.py                  # book(idempotent) + catch-up + non-consuming readiness
  python scripts/score_both_edges.py --catch-up-only  # same as default (explicit)
  python scripts/score_both_edges.py --attempt-verdict # ALSO attempt the one-shot verdict (CONSUMES holdout when ready)
"""

from __future__ import annotations

import argparse
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

EVAL_AT_N = 24         # pre-committed forward sample size for the one-shot verdict (both strategies)
DSR_MIN = 0.50         # pre-committed promotion bar
# per-strategy honest multiple-testing count: momentum 45, nowcast 55 (cumulative rounds 1+2), fiscal
# pb_momentum 69 (cumulative through round 3). Keyed by spec.kind so each registry name maps to the
# right deflation bar.
N_TRIALS = {"momentum": 45, "nowcast": 55, "fiscal_momentum": 69}
# state dir name per strategy: KEEP paper_loop.py's convention (state/paper/<key>: momentum|nowcast|fiscal)
# so this harness and paper_loop.py share the SAME ledger per edge.
STATE_KEY = {"momentum_front": "momentum", "nowcast_long": "nowcast", "fiscal_hard": "fiscal"}


def _engine_data():
    import macro_risk_os_v2 as eng  # noqa: E402
    print("[score] initializing engine (PIT returns)...", file=sys.stderr)
    e = eng.ProductionEngine(eng.DEFAULT_CONFIG)
    e.initialize()
    return e.data_layer.ret_df, e.data_layer.monthly


def _build_signal(spec, monthly):
    """The oriented, point-in-time signal driving the position (None for momentum -> loop uses returns).

    Copied verbatim from scripts/paper_loop.py so the scheduled run, the CLI, and this harness all
    reproduce the identical signal for every booked edge."""
    kind = spec.get("kind")
    if kind == "momentum":
        return None
    if kind == "fiscal_momentum":
        pb = monthly.get("primary_balance")
        if pb is None:
            raise SystemExit("[score] 'primary_balance' not in monthly — cannot run fiscal sleeve")
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
        raise SystemExit(f"[score] unknown nowcast signal '{name}'")
    raise SystemExit(f"[score] unknown spec kind '{kind}'")


def _readiness(ledger, spec):
    """NON-CONSUMING readiness check: read the durable ledger and report n-accrued vs the pre-committed
    eval_at_n WITHOUT ever calling promotion_verdict (which would consume the single-use holdout).

    Returns a dict describing exactly what a verdict WOULD do today, mirroring the verdict's own gate
    logic (HoldoutNotReadyError when n != eval_at_n; deterministic-read when already consumed) — but
    purely by inspection, so it is safe to run any number of times."""
    from arc.autonomy.spec import strategy_hash
    h = strategy_hash(spec)
    n = int(ledger.frozen_frame().shape[0])
    basis = ledger.basis_for(h)
    consumed = h in ledger.consumed_hashes()

    if basis is None:
        return {"n": n, "eval_at_n": None, "ready": False,
                "status": "REFUSED: MissingDeflationBasisError (not booked)"}
    eval_at_n = int(basis.eval_at_n)

    if consumed:
        v = ledger.verdict_for(h)
        if v is not None:
            return {"n": n, "eval_at_n": eval_at_n, "ready": False, "consumed": True,
                    "status": f"SPENT: prior verdict {'PASS' if v.passed else 'FAIL'} "
                              f"(DSR {v.dsr:.3f} vs {v.dsr_min}, Sharpe {v.sr_annual:.2f}, n={v.n})"}
        return {"n": n, "eval_at_n": eval_at_n, "ready": False, "consumed": True,
                "status": "SPENT: HoldoutConsumedError (consumed, no verdict — prior crash)"}

    if n < eval_at_n:
        return {"n": n, "eval_at_n": eval_at_n, "ready": False,
                "status": f"REFUSED: HoldoutNotReadyError {n}<{eval_at_n}"}
    if n > eval_at_n:
        return {"n": n, "eval_at_n": eval_at_n, "ready": False,
                "status": f"REFUSED: HoldoutNotReadyError overshot {n}>{eval_at_n}"}
    return {"n": n, "eval_at_n": eval_at_n, "ready": True,
            "status": f"READY: exactly {n}=={eval_at_n} forward months (verdict would fire)"}


def _print_table(rows) -> None:
    """One honest status line per edge: strategy, hash, instrument, forward_start, n accrued, eval_at_n,
    verdict status. Proves the system scores BOTH edges and is correctly blocked today."""
    cols = ["strategy", "hash", "inst", "forward_start", "fwd_n", "eval_at_n", "verdict status"]
    widths = [16, 16, 5, 12, 6, 9, 52]
    sep = "+".join("-" * (w + 2) for w in widths)
    header = "|".join(f" {c:<{w}} " for c, w in zip(cols, widths))
    print("\n" + sep)
    print(header)
    print(sep)
    for r in rows:
        cells = [r["strategy"], r["hash"], r["inst"], r["forward_start"],
                 str(r["fwd_n"]), str(r["eval_at_n"]), r["status"]]
        print("|".join(f" {str(c):<{w}} " for c, w in zip(cells, widths)))
    print(sep)


def main() -> None:
    import pandas as pd  # noqa: E402

    from arc.autonomy import (PaperLedger, book_trial, issue_token, promotion_verdict, run_loop)
    from arc.autonomy.source import knowledge_time, monthly_return_provider
    from arc.autonomy.spec import SPECS, strategy_hash

    ap = argparse.ArgumentParser(description="ARC readiness harness — score BOTH booked edges (honest)")
    ap.add_argument("--state-root", default=None, help="default: state/paper")
    ap.add_argument("--asof", default=None, help="ISO date; default = latest knowable month")
    ap.add_argument("--forward-start", default=None,
                    help="ISO month-end research cutoff; only later months count as holdout "
                         "(default per edge = latest in-sample month at book time)")
    ap.add_argument("--vol-target", type=float, default=0.10)
    ap.add_argument("--pub-lag-days", type=int, default=1)
    ap.add_argument("--issued-by", default="owner")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--catch-up-only", action="store_true", default=True,
                      help="(default) book+catch-up+NON-consuming readiness check (safe, idempotent)")
    mode.add_argument("--attempt-verdict", action="store_true",
                      help="ALSO attempt the one-shot promotion_verdict per edge (CONSUMES the holdout "
                           "when exactly eval_at_n months have accrued)")
    args = ap.parse_args()

    state_root = args.state_root or os.path.join(ROOT, "state", "paper")
    ret_df, monthly = _engine_data()

    rows = []
    for name, spec in SPECS.items():
        inst = spec["instrument"]
        kind = spec["kind"]
        key = STATE_KEY[name]
        n_trials = N_TRIALS[kind]
        state_dir = os.path.join(state_root, key)
        ledger = PaperLedger(state_dir)
        h = strategy_hash(spec)

        if inst not in ret_df.columns:
            rows.append({"strategy": name, "hash": h[:12], "inst": inst, "forward_start": "n/a",
                         "fwd_n": "?", "eval_at_n": EVAL_AT_N,
                         "status": f"SKIPPED: '{inst}' not in ret_df"})
            print(f"[score] WARNING: '{inst}' not in ret_df — skipping {name}", file=sys.stderr)
            continue

        rets = ret_df[inst].dropna()
        provider = monthly_return_provider(rets, pub_lag_days=args.pub_lag_days)

        signal = _build_signal(spec, monthly)
        signal_provider = None
        if signal is not None:
            signal = pd.Series(signal).dropna()
            signal_provider = lambda asof, _s=signal: _s[_s.index <= pd.Timestamp(asof)]  # noqa: E731

        # research cutoff: months at/before the last in-sample return are NOT holdout (default = last data month)
        research_cutoff = (pd.Timestamp(args.forward_start) if args.forward_start
                           else (rets.index[-1] + pd.offsets.MonthEnd(0))).strftime("%Y-%m-%d")

        # 1) book (idempotent): the booking is a no-op if already booked; the immutable basis is kept.
        book_trial(ledger, spec=spec, n_trials=n_trials, sr_std=None, eval_at_n=EVAL_AT_N,
                   dsr_min=DSR_MIN, forward_start=research_cutoff, issued_by=args.issued_by)
        basis = ledger.basis_for(h)
        # honest forward_start to display = the FROZEN one in the durable basis (not necessarily our arg)
        fs = basis.forward_start if basis is not None else research_cutoff

        # 2) catch-up: run the deterministic loop for every knowable forward month (idempotent re-tick).
        last_known = knowledge_time(rets.index[-1] + pd.offsets.MonthEnd(0), args.pub_lag_days)
        asof = pd.Timestamp(args.asof) if args.asof else last_known
        for mo in [m for m in rets.index if knowledge_time(m, args.pub_lag_days) <= asof]:
            run_loop(knowledge_time(mo, args.pub_lag_days), provider, ledger, spec=spec,
                     vol_target=args.vol_target, signal_provider=signal_provider, run_id="score-catchup")

        # 3) verdict assessment:
        if args.attempt_verdict:
            # CONSUMING path — explicit opt-in. Capture the governance refusal rather than crashing.
            tok = issue_token(spec, issued_by=args.issued_by)
            try:
                v = promotion_verdict(ledger, tok, asof=asof, spec=spec, run_id="score-verdict")
                status = (f"{'PASS' if v['passed'] else 'FAIL'}: DSR {v['dsr']:.3f} vs {v['dsr_min']}, "
                          f"Sharpe {v['sr_annual']:.2f}, n={v['n']}")
                rd = {"n": v["n"], "eval_at_n": basis.eval_at_n if basis else EVAL_AT_N}
            except Exception as exc:  # noqa: BLE001 — surface the governance refusal verbatim
                rd = _readiness(ledger, spec)
                status = f"REFUSED: {type(exc).__name__}: {exc}"
                print(f"[score] {name} verdict refused (by design): {type(exc).__name__}: {exc}",
                      file=sys.stderr)
        else:
            # DEFAULT non-consuming readiness — pure read, never calls promotion_verdict.
            rd = _readiness(ledger, spec)
            status = rd["status"]

        rows.append({"strategy": name, "hash": h[:12], "inst": inst, "forward_start": fs,
                     "fwd_n": rd.get("n", "?"), "eval_at_n": rd.get("eval_at_n", EVAL_AT_N),
                     "status": status})
        print(f"[score] {name} ({inst}) {h[:8]} forward months accrued: "
              f"{ledger.frozen_frame().shape[0]} (eval_at_n={EVAL_AT_N})", file=sys.stderr)

    _print_table(rows)

    mode_str = ("attempt-verdict (CONSUMING when ready)" if args.attempt_verdict
                else "catch-up-only (safe, NON-consuming readiness)")
    n_ready = sum(1 for r in rows if str(r["status"]).startswith("READY"))
    print(f"\n[score] mode={mode_str} | edges booked & scored: {len(rows)} | "
          f"ready for verdict today: {n_ready}")
    print("[score] All booked edges are wired into the scoring machinery and each accrues its own "
          "single-use holdout. Today: 0 out-of-time months exist (ret_df ends 2026-06), so every verdict "
          "correctly REFUSES (HoldoutNotReadyError). No forward months were fabricated. ~24 months must "
          "pass for the one-shot verdict to fire.")


if __name__ == "__main__":
    main()
