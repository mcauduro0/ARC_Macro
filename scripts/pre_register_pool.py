"""Phase 7.4 (track a) — durably PRE-REGISTER the pooled forward holdout, then prove it is honestly
blocked today (0 common forward months).

Pure (reads the three booked member ledgers under state/paper/<key>; no engine, no network). The pool is
an equal-weight panel of momentum_front + nowcast_long + fiscal_hard, pre-committed to a SHORTER forward
sample so it can reach a verdict ~1 year sooner than a single sleeve — IF several sleeves carry real edge.

The pre-registration numbers are FIXED HERE (committed before any forward data exists), never recomputed:
  POOL_N_TRIALS  = 72   cumulative multiple-testing count (69 cumulative component search + 3 pooling
                        design d.o.f.: membership, equal-weight choice, the eval_at_n formula).
  POOL_EVAL_AT_N = 12   = max(12, ceil(24 / K_eff)) with the measured K_eff=2.92 (the sleeves' breadth);
                        the 12-month CALENDAR FLOOR guards against regime-thinness.
  POOL_DSR_MIN   = 0.50 same promotion bar as the singles (NOT lowered for the pool).
  forward_start         inherited from the members (the last in-sample month), so only later COMMON
                        months count as the pooled holdout.

Booking is idempotent (the immutable basis is kept). The default mode runs a NON-CONSUMING readiness
check (pure read of the pooled common-support count vs eval_at_n); the consuming one-shot verdict only
fires under --attempt-verdict, and today it correctly REFUSES (0 < 12).

Usage:
  python scripts/pre_register_pool.py                    # book(idempotent) + non-consuming readiness
  python scripts/pre_register_pool.py --attempt-verdict  # ALSO attempt the one-shot pooled verdict
"""

from __future__ import annotations

import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

POOL_N_TRIALS = 72
POOL_EVAL_AT_N = 12
POOL_DSR_MIN = 0.50
STATE_KEY = {"momentum_front": "momentum", "nowcast_long": "nowcast", "fiscal_hard": "fiscal"}


def main() -> None:
    from arc.autonomy import PaperLedger
    from arc.autonomy.pool import (
        book_pool,
        issue_pool_token,
        pooled_forward_returns,
        pooled_verdict,
    )
    from arc.autonomy.spec import POOL_HASH, strategy_hash
    from arc.autonomy.spec import FROZEN_SPEC, NOWCAST_SPEC, HARD_PB_SPEC

    ap = argparse.ArgumentParser(description="Pre-register the pooled forward holdout (honest, blocked today)")
    ap.add_argument("--state-root", default=None, help="default: state/paper")
    ap.add_argument("--forward-start", default=None, help="ISO month-end; default: inherit from members")
    ap.add_argument("--issued-by", default="owner")
    ap.add_argument("--attempt-verdict", action="store_true",
                    help="ALSO attempt the one-shot pooled verdict (CONSUMES when exactly eval_at_n)")
    args = ap.parse_args()

    state_root = args.state_root or os.path.join(ROOT, "state", "paper")
    member_specs = {"momentum_front": FROZEN_SPEC, "nowcast_long": NOWCAST_SPEC, "fiscal_hard": HARD_PB_SPEC}

    # read the three member ledgers
    member_ledgers, member_frozen, forward_starts = {}, {}, []
    for name, key in STATE_KEY.items():
        led = PaperLedger(os.path.join(state_root, key))
        member_ledgers[name] = led
        member_frozen[name] = led.frozen_frame()
        b = led.basis_for(strategy_hash(member_specs[name]))
        if b is not None and b.forward_start:
            forward_starts.append(b.forward_start)
        print(f"[pool] member {name:14s}: frozen forward months = {member_frozen[name].shape[0]}"
              + (f", forward_start={b.forward_start}" if b else ", NOT BOOKED"))

    # forward_start: inherit the LATEST member cutoff (most conservative), or the arg
    forward_start = args.forward_start or (max(forward_starts) if forward_starts else None)
    if forward_start is None:
        raise SystemExit("[pool] no member forward_start found and none given; book the members first "
                         "(scripts/score_both_edges.py) or pass --forward-start")

    pool_led = PaperLedger(os.path.join(state_root, "pool"))
    h = book_pool(pool_led, n_trials=POOL_N_TRIALS, eval_at_n=POOL_EVAL_AT_N, dsr_min=POOL_DSR_MIN,
                  forward_start=forward_start, issued_by=args.issued_by)
    assert h == POOL_HASH
    basis = pool_led.basis_for(POOL_HASH)
    print(f"\n[pool] BOOKED pool {h} | members={len(member_specs)} | n_trials={basis.n_trials} "
          f"sr_std=auto(Lo-2002) eval_at_n={basis.eval_at_n} dsr_min={basis.dsr_min} "
          f"forward_start={basis.forward_start}")

    pooled = pooled_forward_returns(member_frozen)
    n = int(len(pooled))
    print(f"[pool] pooled common forward months (all 3 members realized): {n} (eval_at_n={basis.eval_at_n})")

    consumed = POOL_HASH in pool_led.consumed_hashes()
    if consumed:
        v = pool_led.verdict_for(POOL_HASH)
        print(f"[pool] SPENT: prior verdict {'PASS' if v and v.passed else 'FAIL/none'}")
    elif n < basis.eval_at_n:
        print(f"[pool] READINESS: REFUSED (HoldoutNotReadyError {n}<{basis.eval_at_n}) — "
              f"{basis.eval_at_n - n} common forward months still needed.")
    elif n > basis.eval_at_n:
        print(f"[pool] READINESS: REFUSED (overshot {n}>{basis.eval_at_n}) — re-book a new schedule.")
    else:
        print(f"[pool] READINESS: READY (exactly {n}=={basis.eval_at_n}) — a verdict WOULD fire.")

    if args.attempt_verdict:
        try:
            v = pooled_verdict(pool_led, member_frozen, issue_pool_token(issued_by=args.issued_by),
                               asof=str(forward_start), run_id="pool-cli")
            print(f"\n[pool] POOLED VERDICT: {'PASS' if v['passed'] else 'FAIL'} — {v['reason']}")
        except Exception as exc:  # noqa: BLE001 — surface the governance refusal verbatim
            print(f"\n[pool] verdict refused (by design): {type(exc).__name__}: {exc}", file=sys.stderr)

    print("\n[pool] Pre-registered. The pool accrues a COMMON forward month only when ALL three sleeves "
          "have realized that month; it can reach a one-shot, deflated verdict at 12 common months "
          "(~1y sooner than a single sleeve) — and only if several sleeves carry real edge. The forward "
          "holdout is the sole judge; nothing is promoted here.")


if __name__ == "__main__":
    main()
