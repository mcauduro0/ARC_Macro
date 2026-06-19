"""Measure the combined backtest impact of the THREE remaining leak fixes.

Isolates filtered-HMM (regime-1) + bounded-ffill (feat-3) + causal-r*-regime (eq-1/eq-3) by running
the backtest twice with the forward-target and causal-winsorize fixes held ON in BOTH runs:

  baseline  : ARC_HMM_FILTERED=0  ARC_BOUNDED_FFILL=0  ARC_CAUSAL_RSTAR_REGIME=0   (the FORWARD_TARGET
              doc's suspicious IC ~0.64 regime — forward target on, residual leaks present)
  fixed     : ARC_HMM_FILTERED=1  ARC_BOUNDED_FFILL=1  ARC_CAUSAL_RSTAR_REGIME=1

Diffs overlay Sharpe / return / max-dd / win-rate and per-instrument IC. The audit hypothesis is
that the implausible belly/long IC of ~0.6 DEFLATES toward reality once these leaks are removed; this
script measures by how much. Usage:  python scripts/measure_leak_fixes.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODEL_DIR = os.path.join(ROOT, "server", "model")

_RUN = (
    "import json, os, sys;"
    "sys.path.insert(0, '.'); sys.path.insert(0, os.environ['ARC_ROOT']);"
    "from macro_risk_os_v2 import run_v2;"
    "out = run_v2();"
    "json.dump(out['backtest']['summary'], open(os.environ['ARC_OUT'], 'w'))"
)

_FIXES = ["ARC_HMM_FILTERED", "ARC_BOUNDED_FFILL", "ARC_CAUSAL_RSTAR_REGIME"]


def _run(state: str, timeout: int) -> dict:
    out_path = os.path.join(tempfile.gettempdir(), f"arc_summary_leakfix_{state}.json")
    env = os.environ.copy()
    env["ARC_ROOT"] = ROOT
    env["ARC_OUT"] = out_path
    env["ARC_FORWARD_TARGET"] = "1"      # held ON in both
    env["ARC_CAUSAL_WINSORIZE"] = "1"    # held ON in both
    for v in _FIXES:
        env[v] = state                   # "1" = fixed, "0" = baseline
    print(f"[measure] running backtest with the 3 leak fixes = {state} ...", file=sys.stderr)
    p = subprocess.run([sys.executable, "-c", _RUN], cwd=MODEL_DIR, env=env,
                       capture_output=True, text=True, timeout=timeout)
    if not os.path.exists(out_path):
        raise RuntimeError(f"run failed (state={state}); stderr tail:\n{p.stderr[-2000:]}")
    return json.load(open(out_path))


def _pick(summary: dict) -> dict:
    ov = summary.get("overlay", {}) if isinstance(summary, dict) else {}
    ic = summary.get("ic_per_instrument", {})
    ic_vals = [v for v in ic.values() if isinstance(v, (int, float))]
    return {
        "overlay_sharpe": ov.get("sharpe"),
        "overlay_total_return": ov.get("total_return"),
        "overlay_max_drawdown": ov.get("max_drawdown"),
        "overlay_win_rate": ov.get("win_rate"),
        "mean_ic": (sum(ic_vals) / len(ic_vals)) if ic_vals else None,
        "ic_per_instrument": ic,
    }


def main() -> None:
    timeout = int(os.environ.get("ARC_MEASURE_TIMEOUT", "5400"))
    baseline = _pick(_run("0", timeout))
    fixed = _pick(_run("1", timeout))
    print("\n=== REMAINING LEAK FIXES (filtered HMM + bounded ffill + causal r*): IMPACT ===")
    print(f"{'metric':24} {'baseline(leak)':>14} {'fixed':>14} {'delta':>12}")
    for k in ["overlay_sharpe", "overlay_total_return", "overlay_max_drawdown", "overlay_win_rate", "mean_ic"]:
        a, b = baseline.get(k), fixed.get(k)
        delta = (b - a) if isinstance(a, (int, float)) and isinstance(b, (int, float)) else None
        fa = f"{a:.4f}" if isinstance(a, (int, float)) else str(a)
        fb = f"{b:.4f}" if isinstance(b, (int, float)) else str(b)
        fd = f"{delta:+.4f}" if isinstance(delta, (int, float)) else ""
        print(f"{k:24} {fa:>14} {fb:>14} {fd:>12}")
    print("\nPer-instrument IC (fixed):   ", json.dumps(fixed.get("ic_per_instrument", {})))
    print("Per-instrument IC (baseline):", json.dumps(baseline.get("ic_per_instrument", {})))


if __name__ == "__main__":
    main()
