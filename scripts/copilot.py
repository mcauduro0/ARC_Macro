"""Phase 7.4 — the CO-PILOT CLI: the loop PROPOSES, a human DECIDES, decisions feed a forward stream.

Engine-touching entrypoint (imports the heavy monolith, so NOT run in CI; the pure ``arc.autonomy.copilot``
+ ``tests/test_copilot.py`` carry the CI guarantees). This is the human-in-the-loop front-end over the
Phase 7 spine. It shares ledgers with ``scripts/paper_loop.py`` / ``scripts/score_both_edges.py`` (same
``state/paper/<key>`` per edge), so the frozen holdout it advances is the SAME single-use holdout — and
the human's choices are recorded in a THIRD, strictly separate ``operator`` stream that can NEVER touch
the scored ``frozen`` stream.

Three streams per edge:
  frozen   — deterministic scored holdout (the verdict's only input; the human can never touch it).
  live     — deterministic auto-operate baseline (breaker-controlled).
  operator — YOUR decisions (this CLI): APPROVE / OVERRIDE / SKIP, immutable, with a rationale.

Usage:
  python scripts/copilot.py --propose                      # advance + show the proposal for every edge
  python scripts/copilot.py --propose --strategy nowcast   # just one edge
  python scripts/copilot.py --decide --strategy momentum --action APPROVE  --rationale "trend intact"
  python scripts/copilot.py --decide --strategy nowcast  --action OVERRIDE --position 0.4 --rationale "half size, election risk"
  python scripts/copilot.py --decide --strategy fiscal   --action SKIP     --rationale "recency flag still red"
  python scripts/copilot.py --status                       # operational snapshot of all three streams

Honest note: APPROVE/OVERRIDE/SKIP shapes only the OPERATOR stream (your real forward track record).
The frozen holdout accrues deterministically regardless and is scored exactly once, later, via the
token-gated ``promotion_verdict`` — never from here.
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

EVAL_AT_N = 24
DSR_MIN = 0.50
N_TRIALS = {"momentum": 45, "nowcast": 55, "fiscal_momentum": 69}
# registry name <-> short --strategy choice <-> state dir key (shared with paper_loop.py)
NAME_BY_CHOICE = {"momentum": "momentum_front", "nowcast": "nowcast_long", "fiscal": "fiscal_hard"}
STATE_KEY = {"momentum_front": "momentum", "nowcast_long": "nowcast", "fiscal_hard": "fiscal"}


def _engine_data():
    import macro_risk_os_v2 as eng  # noqa: E402
    print("[copilot] initializing engine (PIT returns)...", file=sys.stderr)
    e = eng.ProductionEngine(eng.DEFAULT_CONFIG)
    e.initialize()
    return e.data_layer.ret_df, e.data_layer.monthly


def _build(name, spec, ret_df, monthly, *, state_root, pub_lag_days, forward_start_arg, issued_by):
    """Return (ledger, provider, signal_provider, asof, knowable_months) for one edge, booked idempotently.
    Returns None if the instrument is absent from ret_df."""
    import pandas as pd  # noqa: E402

    from arc.autonomy import PaperLedger, book_trial, build_signal
    from arc.autonomy.source import knowledge_time, monthly_return_provider

    inst, kind = spec["instrument"], spec["kind"]
    if inst not in ret_df.columns:
        print(f"[copilot] WARNING: '{inst}' not in ret_df — skipping {name}", file=sys.stderr)
        return None

    ledger = PaperLedger(os.path.join(state_root, STATE_KEY[name]))
    rets = ret_df[inst].dropna()
    provider = monthly_return_provider(rets, pub_lag_days=pub_lag_days)

    signal = build_signal(spec, monthly)
    signal_provider = None
    if signal is not None:
        signal = pd.Series(signal).dropna()
        signal_provider = lambda asof, _s=signal: _s[_s.index <= pd.Timestamp(asof)]  # noqa: E731

    research_cutoff = (pd.Timestamp(forward_start_arg) if forward_start_arg
                       else (rets.index[-1] + pd.offsets.MonthEnd(0))).strftime("%Y-%m-%d")
    book_trial(ledger, spec=spec, n_trials=N_TRIALS[kind], sr_std=None, eval_at_n=EVAL_AT_N,
               dsr_min=DSR_MIN, forward_start=research_cutoff, issued_by=issued_by)

    last_known = knowledge_time(rets.index[-1] + pd.offsets.MonthEnd(0), pub_lag_days)
    knowable = [knowledge_time(m, pub_lag_days) for m in rets.index
                if knowledge_time(m, pub_lag_days) <= last_known]
    return ledger, provider, signal_provider, last_known, knowable


def _advance_and_propose(name, spec, built, vol_target, risk_limits=None):
    """Catch up the deterministic loop over all knowable months (idempotent) and return the final
    OperatorProposal for the latest decidable month. ``risk_limits`` turns on the live VaR/ES gate."""
    from arc.autonomy.copilot import propose

    ledger, provider, signal_provider, asof, knowable = built
    p = None
    for at in knowable:
        p = propose(at, provider, ledger, spec=spec, signal_provider=signal_provider,
                    vol_target=vol_target, risk_limits=risk_limits, strategy=name, run_id="copilot")
    if p is None:  # no knowable months at all
        p = propose(asof, provider, ledger, spec=spec, signal_provider=signal_provider,
                    vol_target=vol_target, risk_limits=risk_limits, strategy=name, run_id="copilot")
    return p


def _pct(x):
    return f"{x * 100:.1f}%" if x == x else "n/a"  # x==x is False for NaN


def _print_proposals(rows):
    cols = ["strategy", "month", "suggest", "frozen", "proposed", "sized", "VaR95", "gate", "halt", "fwd_n"]
    widths = [14, 11, 8, 8, 8, 7, 7, 11, 5, 6]
    sep = "+".join("-" * (w + 2) for w in widths)
    print("\n" + sep)
    print("|".join(f" {c:<{w}} " for c, w in zip(cols, widths)))
    print(sep)
    for r in rows:
        if r["gate_active"]:
            gate = r["gate_binding"] or "-"           # vol_target / var_limit / es_limit
        elif r["gate_binding"] == "inactive":
            gate = "wait(<24m)"                        # enabled but not enough forward history yet
        else:
            gate = "off"                               # disabled (--no-risk-gate)
        cells = [r["strategy"], r["month"] or "(warmup)", r["suggest"],
                 f"{r['frozen_pos']:.3f}" if r["frozen_pos"] == r["frozen_pos"] else "nan",
                 f"{r['proposed']:.3f}" if r["proposed"] == r["proposed"] else "nan",
                 f"{r['sized']:.2f}" if r["sized"] == r["sized"] else "nan",
                 _pct(r["var_forecast"]), gate,
                 "YES" if r["halted"] else "no", str(r["fwd_n"])]
        print("|".join(f" {str(c):<{w}} " for c, w in zip(cells, widths)))
    print(sep)


def main() -> None:
    from dataclasses import asdict

    from arc.autonomy.copilot import copilot_status, decide
    from arc.autonomy.paper import reconcile, reconcile_operator
    from arc.autonomy.spec import SPECS

    ap = argparse.ArgumentParser(description="ARC co-pilot — propose / decide / status (human-in-the-loop)")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--propose", action="store_true", help="(default) advance + show proposals")
    mode.add_argument("--decide", action="store_true", help="commit your decision for one edge")
    mode.add_argument("--status", action="store_true", help="operational snapshot of all three streams")
    ap.add_argument("--strategy", choices=list(NAME_BY_CHOICE), default=None,
                    help="one edge (default: all)")
    ap.add_argument("--action", choices=["APPROVE", "OVERRIDE", "SKIP"], help="(--decide) your action")
    ap.add_argument("--position", type=float, default=None, help="(--decide OVERRIDE) the position to take")
    ap.add_argument("--rationale", default="", help="(--decide) why — recorded immutably in the ledger")
    ap.add_argument("--month", default=None, help="(--decide) target month-end ISO (default: latest decidable)")
    ap.add_argument("--max-abs-position", type=float, default=5.0, help="(--decide) fat-finger guard")
    ap.add_argument("--state-root", default=None, help="default: state/paper")
    ap.add_argument("--forward-start", default=None, help="ISO research cutoff (default: last in-sample month)")
    ap.add_argument("--vol-target", type=float, default=0.10)
    ap.add_argument("--pub-lag-days", type=int, default=1)
    ap.add_argument("--var-limit", type=float, default=0.055,
                    help="live pre-trade gate: max monthly 95%% VaR (positive loss) of the sized book")
    ap.add_argument("--es-limit", type=float, default=0.075, help="max monthly 95%% ES of the sized book")
    ap.add_argument("--no-risk-gate", action="store_true", help="disable the live VaR/ES pre-trade gate")
    ap.add_argument("--issued-by", default="owner")
    args = ap.parse_args()

    from arc.autonomy.risk_gate import RiskLimits
    risk_limits = None if args.no_risk_gate else RiskLimits(var_limit=args.var_limit, es_limit=args.es_limit)

    state_root = args.state_root or os.path.join(ROOT, "state", "paper")
    chosen = {NAME_BY_CHOICE[args.strategy]} if args.strategy else set(SPECS)

    # ---- status: pure read, no engine needed ------------------------------
    if args.status:
        from arc.autonomy import PaperLedger
        out = {}
        for name in SPECS:
            if name not in chosen:
                continue
            led = PaperLedger(os.path.join(state_root, STATE_KEY[name]))
            out[name] = copilot_status(led, strategy=name)
        print(json.dumps(out, indent=2, default=str))
        return

    ret_df, monthly = _engine_data()

    # ---- decide: commit one edge's operator decision ----------------------
    if args.decide:
        if not args.strategy or not args.action:
            raise SystemExit("[copilot] --decide requires --strategy and --action")
        name = NAME_BY_CHOICE[args.strategy]
        spec = SPECS[name]
        built = _build(name, spec, ret_df, monthly, state_root=state_root, pub_lag_days=args.pub_lag_days,
                       forward_start_arg=args.forward_start, issued_by=args.issued_by)
        if built is None:
            raise SystemExit(f"[copilot] cannot operate {name}: instrument absent")
        p = _advance_and_propose(name, spec, built, args.vol_target, risk_limits)  # ensure the decision exists
        if not p.month:
            raise SystemExit(f"[copilot] {name} is still warming up — nothing to decide yet")
        target = args.month or p.month
        ledger, provider, signal_provider, asof, _ = built
        od = decide(ledger, spec=spec, month=target, action=args.action, position=args.position,
                    rationale=args.rationale, decided_by=args.issued_by,
                    max_abs_position=args.max_abs_position, decided_at=str(asof.date()), run_id="copilot")
        # realize the operator stream for any now-final decided months
        import pandas as pd  # noqa: E402
        rets = ret_df[spec["instrument"]].dropna()
        reconcile(asof, rets, ledger, spec=spec, run_id="copilot")
        reconcile_operator(asof, rets, ledger, spec=spec, run_id="copilot")
        print(f"[copilot] {name}: committed {od.action} for {od.month} "
              f"(operator_position={od.operator_position:.4f}, proposed={od.proposed_position:.4f})")
        print(json.dumps(asdict(od), indent=2))
        print(json.dumps(copilot_status(ledger, strategy=name), indent=2, default=str))
        return

    # ---- propose (default): advance + show proposals ----------------------
    rows = []
    proposals = {}
    for name in SPECS:
        if name not in chosen:
            continue
        spec = SPECS[name]
        built = _build(name, spec, ret_df, monthly, state_root=state_root, pub_lag_days=args.pub_lag_days,
                       forward_start_arg=args.forward_start, issued_by=args.issued_by)
        if built is None:
            continue
        p = _advance_and_propose(name, spec, built, args.vol_target, risk_limits)
        proposals[name] = asdict(p)
        rows.append({"strategy": name, "month": p.month, "suggest": p.action_suggestion,
                     "frozen_pos": p.frozen_position, "proposed": p.proposed_position,
                     "sized": p.sized_exposure, "halted": p.circuit_halted,
                     "fwd_n": p.n_frozen_months, "decided": p.operator_decided,
                     "var_forecast": p.var_forecast, "gate_binding": p.risk_gate_binding,
                     "gate_active": p.risk_gate_active, "warnings": list(p.drift_warnings)})
    _print_proposals(rows)
    flagged = [(r["strategy"], w) for r in rows for w in r["warnings"]]
    if flagged:
        print("\n[copilot] WARNINGS:")
        for strat, w in flagged:
            print(f"  - {strat}: {w}")
    out_path = os.path.join(state_root, "copilot_proposals.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(proposals, f, indent=2, default=str)
    print(f"\n[copilot] proposals written to {out_path}")
    print("[copilot] To act: python scripts/copilot.py --decide --strategy <momentum|nowcast|fiscal> "
          "--action <APPROVE|OVERRIDE|SKIP> [--position P] --rationale \"...\"")
    print("[copilot] The frozen holdout accrues deterministically; your decision shapes only the operator "
          "stream. Promotion stays a separate, token-gated verdict.")


if __name__ == "__main__":
    main()
