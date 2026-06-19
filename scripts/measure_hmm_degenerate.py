"""Measure the combined impact of the HMM-gargalo (P6) + degenerate-model (fx/hard) fixes.

Isolates per-series regime alignment (ARC_REGIME_PER_SERIES) + per-series feature coverage
(ARC_FEAT_PER_SERIES) by running the backtest twice with ALL the earlier causal fixes held ON in both
(forward target, causal winsorize, filtered HMM, bounded ffill, causal r*):

  baseline : ARC_REGIME_PER_SERIES=0  ARC_FEAT_PER_SERIES=0  (global HMM collapses to uniform priors
             pre-2023; fx/hard silently skipped -> mu=0)
  fixed    : ARC_REGIME_PER_SERIES=1  ARC_FEAT_PER_SERIES=1

Diffs overlay metrics + per-instrument IC. Usage:  python scripts/measure_hmm_degenerate.py
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

_ALWAYS_ON = ["ARC_FORWARD_TARGET", "ARC_CAUSAL_WINSORIZE", "ARC_HMM_FILTERED",
              "ARC_BOUNDED_FFILL", "ARC_CAUSAL_RSTAR_REGIME"]
_PHASE = ["ARC_REGIME_PER_SERIES", "ARC_FEAT_PER_SERIES"]


def _run(state: str, timeout: int) -> dict:
    out_path = os.path.join(tempfile.gettempdir(), f"arc_summary_phase2_{state}.json")
    env = os.environ.copy()
    env["ARC_ROOT"] = ROOT
    env["ARC_OUT"] = out_path
    for v in _ALWAYS_ON:
        env[v] = "1"
    for v in _PHASE:
        env[v] = state
    print(f"[measure] running backtest with P6+degenerate fixes = {state} ...", file=sys.stderr)
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
    print("\n=== P6 (per-series regime) + fx/hard (per-series features) FIXES: IMPACT ===")
    print(f"{'metric':24} {'baseline':>14} {'fixed':>14} {'delta':>12}")
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
