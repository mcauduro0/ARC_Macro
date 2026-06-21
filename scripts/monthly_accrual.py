"""Phase 7.3 — the deterministic monthly accrual cycle: advance every booked edge's forward holdout.

A thin ORCHESTRATOR over the existing pieces. It does NOT re-init the engine and does NOT re-implement
the loop — it subprocesses the heavy steps (data refresh, flows, the all-edge accrual harness) and then
reads the durable ledgers (pure, NO engine) to log and summarize. Run on a monthly schedule, it accrues
each booked edge's single-use forward holdout as real out-of-time months arrive — and honestly accrues
**0** today (``ret_df`` ends 2026-06, ``forward_start`` = 2026-06-30 for every edge, so 0 out-of-time
months exist and every verdict correctly REFUSES with ``HoldoutNotReadyError 0<24``).

One idempotent monthly run does, in order:
  1) DATA REFRESH (best-effort): ``python server/model/data_collector.py`` (generous timeout) unless
     ``--skip-refresh``. Non-zero/exception is reported honestly (``refresh FAILED: ...``), NEVER fatal —
     accrual continues on the existing CSVs.
  2) FLOWS (best-effort): ``python scripts/collect_flows.py`` unless ``--skip-flows`` (SGS-first /
     IPEADATA-confirmed-fallback). Honest failure, never fatal.
  3) ACCRUAL: ``python scripts/score_both_edges.py`` — books idempotently, catches up the deterministic
     loop over every knowable month, and prints the NON-consuming readiness table for all 3 edges. Its
     STATUS TABLE is captured and re-printed.
  4) DURABLE LOG: read each edge's ledger directly (NO engine) and APPEND one JSON line per run to
     ``state/paper/accrual_log.jsonl`` (schema below).

The verdict is deliberately NOT run here — it is a one-shot, human-gated, token-bearing action. This cycle
only ACCRUES; a human scores.

Usage:
  python scripts/monthly_accrual.py                       # full cycle (refresh + flows + accrue + log)
  python scripts/monthly_accrual.py --skip-refresh        # skip the heavy data_collector
  python scripts/monthly_accrual.py --skip-flows          # skip the flow collector
  python scripts/monthly_accrual.py --stamp 2026-07-02    # explicit ISO run stamp (deterministic)
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)  # so the pure ledger read (`from arc.autonomy import ...`) resolves; no engine needed
STATE_ROOT = os.path.join(ROOT, "state", "paper")
ACCRUAL_LOG = os.path.join(STATE_ROOT, "accrual_log.jsonl")

# registry name -> per-strategy state dir key (the convention paper_loop.py / score_both_edges.py share).
STATE_KEY = {"momentum_front": "momentum", "nowcast_long": "nowcast", "fiscal_hard": "fiscal"}

REFRESH_TIMEOUT = 1200  # generous: data_collector hits many external APIs, several minutes.
FLOWS_TIMEOUT = 600
ACCRUAL_TIMEOUT = 1800  # the engine-touching harness initializes the monolith + catches up every month.


def _tail(text: str, n: int = 25) -> str:
    """Last ``n`` non-empty lines of captured output — enough to diagnose without flooding the log."""
    lines = [ln for ln in (text or "").splitlines() if ln.strip()]
    return "\n".join(lines[-n:])


def _run_step(label: str, argv: list[str], timeout: int) -> tuple[str, str]:
    """Subprocess one step honestly. Returns (route, captured_output).

    ``route`` is a single honest status string: 'OK rc=0', 'FAILED: rc=<n>', 'FAILED: TimeoutExpired',
    'FAILED: <ExcType>: <msg>', or 'SKIPPED'. An exception or non-zero return is reported, NEVER raised —
    the cycle must continue on the existing CSVs (the honesty contract: report failures, don't crash).
    """
    print(f"[accrual] STEP {label}: {' '.join(argv)}", file=sys.stderr)
    try:
        proc = subprocess.run(
            argv, cwd=ROOT, capture_output=True, text=True, timeout=timeout,
        )
        out = (proc.stdout or "") + (("\n" + proc.stderr) if proc.stderr else "")
        if proc.returncode == 0:
            route = "OK rc=0"
        else:
            route = f"{label} FAILED: rc={proc.returncode}"
            print(f"[accrual] {route}\n{_tail(out)}", file=sys.stderr)
        return route, out
    except subprocess.TimeoutExpired as exc:  # noqa: PERF203 — honest per-step capture
        out = ((exc.stdout or "") if isinstance(exc.stdout, str) else "") + \
              (("\n" + exc.stderr) if isinstance(exc.stderr, str) else "")
        route = f"{label} FAILED: TimeoutExpired after {timeout}s"
        print(f"[accrual] {route}", file=sys.stderr)
        return route, out
    except Exception as exc:  # noqa: BLE001 — best-effort: surface, never fatal
        route = f"{label} FAILED: {type(exc).__name__}: {exc}"
        print(f"[accrual] {route}", file=sys.stderr)
        return route, ""


def _ledger_snapshot(stamp: str | None) -> tuple[list[dict], str]:
    """Read each edge's durable ledger (PURE — no engine) and return (per-edge rows, latest_known_month).

    For each edge: n_frozen = frozen_frame().shape[0]; eval_at_n + forward_start from the immutable basis;
    months_to_verdict = max(0, eval_at_n - n). latest_known_month is the max forward_start across edges,
    used as the default run stamp when --stamp is not supplied (Date.now is unavailable in deterministic
    contexts)."""
    from arc.autonomy import PaperLedger, strategy_hash
    from arc.autonomy.spec import SPECS

    rows: list[dict] = []
    latest = stamp
    for name, spec in SPECS.items():
        key = STATE_KEY[name]
        ledger = PaperLedger(os.path.join(STATE_ROOT, key))
        h = strategy_hash(spec)
        n_frozen = int(ledger.frozen_frame().shape[0])
        basis = ledger.basis_for(h)
        eval_at_n = int(basis.eval_at_n) if basis is not None else None
        forward_start = basis.forward_start if basis is not None else None
        m2v = max(0, eval_at_n - n_frozen) if eval_at_n is not None else None
        rows.append({
            "name": name,
            "hash": h[:12],
            "inst": spec["instrument"],
            "n_frozen": n_frozen,
            "eval_at_n": eval_at_n,
            "forward_start": forward_start,
            "months_to_verdict": m2v,
        })
        if forward_start and (latest is None or str(forward_start) > str(latest)):
            latest = str(forward_start)
    return rows, (latest or "unknown")


def _append_log(record: dict) -> None:
    """Append one JSON line to the durable accrual log. Appending is idempotent-friendly — it is a log;
    re-runs are distinguishable by the stamp. Creates state/paper/ if missing."""
    os.makedirs(STATE_ROOT, exist_ok=True)
    with open(ACCRUAL_LOG, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, sort_keys=True) + "\n")


def main() -> None:
    ap = argparse.ArgumentParser(description="ARC monthly accrual cycle — advance every booked edge (honest)")
    ap.add_argument("--skip-refresh", action="store_true",
                    help="skip the heavy server/model/data_collector.py refresh")
    ap.add_argument("--skip-flows", action="store_true",
                    help="skip scripts/collect_flows.py")
    ap.add_argument("--stamp", default=None,
                    help="ISO run stamp (Date.now is unavailable in deterministic contexts); "
                         "default = the ledgers' latest known month (max forward_start)")
    args = ap.parse_args()

    py = sys.executable or "python"

    # 1) DATA REFRESH (best-effort, never fatal) -------------------------------------------------
    if args.skip_refresh:
        refresh_route = "SKIPPED"
        print("[accrual] STEP refresh: SKIPPED (--skip-refresh)", file=sys.stderr)
    else:
        refresh_route, _ = _run_step(
            "refresh", [py, os.path.join("server", "model", "data_collector.py")], REFRESH_TIMEOUT)

    # 2) FLOWS (best-effort, never fatal) --------------------------------------------------------
    if args.skip_flows:
        flows_route = "SKIPPED"
        print("[accrual] STEP flows: SKIPPED (--skip-flows)", file=sys.stderr)
    else:
        flows_route, _ = _run_step(
            "flows", [py, os.path.join("scripts", "collect_flows.py")], FLOWS_TIMEOUT)

    # 3) ACCRUAL (the all-edge harness: book idempotently + catch-up + readiness table) ----------
    accrual_route, accrual_out = _run_step(
        "accrual", [py, os.path.join("scripts", "score_both_edges.py")], ACCRUAL_TIMEOUT)
    # Re-print the harness STATUS TABLE verbatim (it is the operator-facing readiness view).
    if accrual_out:
        print("\n========== score_both_edges.py output ==========")
        print(accrual_out.rstrip())
        print("================================================\n")

    # 4) DURABLE LOG (pure ledger reads — NO engine) --------------------------------------------
    edges, latest_known = _ledger_snapshot(args.stamp)
    stamp = args.stamp or latest_known

    record = {
        "stamp": stamp,
        "phase": "7.3",
        "refresh_route": refresh_route,
        "flows_route": flows_route,
        "accrual_route": accrual_route,
        "edges": edges,
        "n_edges_accruing": sum(1 for e in edges if e["eval_at_n"] is not None),
        "n_out_of_time_months_today": max((e["n_frozen"] for e in edges), default=0),
    }
    _append_log(record)
    print(f"[accrual] appended run {stamp} to {ACCRUAL_LOG}", file=sys.stderr)

    # 5) FINAL HONEST SUMMARY -------------------------------------------------------------------
    k = record["n_edges_accruing"]
    ooi = record["n_out_of_time_months_today"]
    print("\n" + "=" * 78)
    for e in edges:
        print(f"[accrual] {e['name']:<15} ({e['inst']:<5}) {e['hash']}  "
              f"n_frozen={e['n_frozen']:>2}  eval_at_n={e['eval_at_n']}  "
              f"forward_start={e['forward_start']}  months_to_verdict={e['months_to_verdict']}")
    print("=" * 78)
    print(f"[accrual] {k}/3 edges accruing; {ooi} out-of-time months today; "
          f"first verdict eligible when each reaches eval_at_n (~2028-06).")
    print(f"[accrual] refresh={refresh_route} | flows={flows_route} | accrual={accrual_route}")
    print("[accrual] No forward months were fabricated. Each edge accrues its own single-use holdout; "
          "the one-shot verdict is human-gated and NOT run by this cycle.")


if __name__ == "__main__":
    main()
