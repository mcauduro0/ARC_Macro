"""Phase 7.x — evaluate the PRE-REGISTERED forward sizing experiments on the FROZEN forward stream.

HONESTY CONTRACT (this project's prime directive): there are currently 0 out-of-time months (ret_df ends
2026-06). The correct behavior is NOT to fabricate forward months or to judge the hypothesis in-sample; it
is to read each pre-registered experiment's frozen ledger and report, per experiment, either:

  * NOT READY  — fewer than the pre-committed ``eval_at_n`` forward months have accrued. This is the honest
    output TODAY. The experiment, its deterministic sizing rule, and its PASS/FAIL criterion were committed
    to git BEFORE the data existed; nothing is decided yet. ("NOT READY: n<eval_at_n, pre-registered,
    confirm on forward paper").
  * PASS/FAIL  — exactly ``eval_at_n`` months have accrued: recompute flat-vs-sized sleeve returns from the
    RECORDED decisions (held_position) and realized returns via the causal confidence multiplier in
    ``arc.autonomy.forward_experiments.apply_sizing`` (NO new booked trial, NO tick), deflate both arms with
    the SAME persisted basis (n_trials, sr_std), and report whether the pre-committed criterion is met.

This script NEVER consumes the single-use holdout (it does not call ``promotion_verdict``); it is a pure
READ + RECOMPUTE on the same accrued months. It imports NO engine. Run it any number of times; it is
idempotent and side-effect free.

Usage:
  python scripts/confirm_sizing_forward.py                 # all pre-registered experiments
  python scripts/confirm_sizing_forward.py --state-root state/paper
  python scripts/confirm_sizing_forward.py --name nowcast_confvol
"""

from __future__ import annotations

import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)  # pure arc.* import path; NO engine, NO model dir

# per-strategy honest multiple-testing count (keyed by spec.kind), mirroring scripts/score_both_edges.py
# so the sized/flat deflation uses the SAME n_trials the booked sleeve committed to.
N_TRIALS = {"momentum": 45, "nowcast": 55, "fiscal_momentum": 69}


def _evaluate(exp: dict, state_root: str) -> dict:
    """Read one experiment's frozen ledger and return a status dict. Pure read + recompute; never consumes
    the holdout. Honest 'NOT READY' when fewer than eval_at_n forward months have accrued."""
    from arc.autonomy.forward_experiments import apply_sizing, criterion_met, flat_returns
    from arc.autonomy.ledger import PaperLedger
    from arc.autonomy.spec import SPECS, strategy_hash
    from arc.research.sleeve import sleeve_stats

    name = exp["name"]
    base_strategy = exp["base_strategy"]
    spec = SPECS[base_strategy]
    h = strategy_hash(spec)
    state_dir = os.path.join(state_root, exp["state_key"])

    ledger = PaperLedger(state_dir)
    fz = ledger.frozen_frame()
    n = int(len(fz))
    basis = ledger.basis_for(h)

    out = {"name": name, "base_strategy": base_strategy, "hash": h[:12], "n": n,
           "eval_at_n": None, "ready": False, "status": "", "criterion": exp["criterion"]}

    if basis is None:
        out["status"] = ("NOT READY: no deflation basis booked (run scripts/score_both_edges.py to book); "
                         "pre-registered, confirm on forward paper")
        return out
    eval_at_n = int(basis.eval_at_n)
    out["eval_at_n"] = eval_at_n

    # honest "not ready" — the only output possible today (0 < eval_at_n).
    if n < eval_at_n:
        out["status"] = (f"NOT READY: n={n}<eval_at_n={eval_at_n}, pre-registered, confirm on forward paper")
        return out
    if n > eval_at_n:
        # overshooting the pre-committed point is itself a governance refusal (no optional stopping).
        out["status"] = (f"NOT READY: overshot n={n}>eval_at_n={eval_at_n} — the pre-committed evaluation "
                         f"point was missed; re-register an explicit new schedule")
        return out

    # READY: recompute flat vs sized and judge the pre-committed criterion. Same n_trials/sr_std basis.
    n_trials = N_TRIALS.get(spec.get("kind"), basis.n_trials)
    flat = flat_returns(fz)
    sized = apply_sizing(fz, exp["sizing"], alpha=float(exp["alpha"]))

    flat_stats = sleeve_stats(flat, n_trials=n_trials)
    sized_stats = sleeve_stats(sized, n_trials=n_trials)
    passed, reason = criterion_met(flat_stats, sized_stats)

    out["ready"] = True
    out["passed"] = passed
    out["flat"] = {"dsr": flat_stats["dsr"], "sharpe_ann": flat_stats["sharpe_ann"], "n": flat_stats["n"]}
    out["sized"] = {"dsr": sized_stats["dsr"], "sharpe_ann": sized_stats["sharpe_ann"], "n": sized_stats["n"]}
    out["status"] = reason
    return out


def main() -> None:
    from arc.autonomy.forward_experiments import FORWARD_EXPERIMENTS

    ap = argparse.ArgumentParser(
        description="Evaluate pre-registered forward sizing experiments (read-only; never consumes holdout)")
    ap.add_argument("--state-root", default=os.path.join(ROOT, "state", "paper"),
                    help="root of per-strategy ledgers (default: state/paper)")
    ap.add_argument("--name", default=None, help="evaluate only this experiment name")
    args = ap.parse_args()

    experiments = FORWARD_EXPERIMENTS
    if args.name is not None:
        experiments = [e for e in FORWARD_EXPERIMENTS if e["name"] == args.name]
        if not experiments:
            print(f"[confirm] no pre-registered experiment named {args.name!r}", file=sys.stderr)
            sys.exit(2)

    results = [_evaluate(exp, args.state_root) for exp in experiments]

    print("\n=== PRE-REGISTERED FORWARD SIZING EXPERIMENTS (read-only; nothing judged in-sample) ===")
    for r in results:
        print(f"\n[{r['name']}] base={r['base_strategy']} hash={r['hash']} "
              f"forward_n={r['n']} eval_at_n={r['eval_at_n']}")
        print(f"  criterion (pre-committed): {r['criterion']}")
        if r.get("ready"):
            f, s = r["flat"], r["sized"]
            print(f"  flat : DSR {f['dsr']:.3f}  Sharpe {f['sharpe_ann']:.2f}  (n={f['n']})")
            print(f"  sized: DSR {s['dsr']:.3f}  Sharpe {s['sharpe_ann']:.2f}  (n={s['n']})")
            print(f"  verdict: {'PASS' if r['passed'] else 'FAIL'} — {r['status']}")
        else:
            print(f"  {r['status']}")

    n_ready = sum(1 for r in results if r.get("ready"))
    print(f"\n[confirm] experiments: {len(results)} | ready to judge today: {n_ready}")
    if n_ready == 0:
        print("[confirm] All experiments are PRE-REGISTERED and correctly NOT READY today: 0 out-of-time "
              "months exist. The deterministic sizing rule and PASS/FAIL criterion were committed to git "
              "before any forward data — they will be evaluated on the FROZEN forward stream once eval_at_n "
              "months accrue. Nothing is judged in-sample.")


if __name__ == "__main__":
    main()
