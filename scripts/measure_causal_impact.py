"""Measure the backtest impact of the causal-winsorize leakage fix.

Runs the v2 backtest twice — once with the causal (point-in-time) winsorize ON (the fix) and
once with the legacy full-sample winsorize (look-ahead) — and diffs the headline metrics.

Prereq: data already collected into server/model/data (run `python server/model/run_model.py`
once, or `python server/model/data_collector.py`). Usage:

    python scripts/measure_causal_impact.py

Honest by construction: it reports whatever the engine produces. If the leakage fix lowers
the in-sample Sharpe/IC, that is the point — the prior numbers were inflated by look-ahead.
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


def _run(causal: str, timeout: int) -> dict:
    out_path = os.path.join(tempfile.gettempdir(), f"arc_summary_causal_{causal}.json")
    var = os.environ.get("ARC_MEASURE_VAR", "ARC_CAUSAL_WINSORIZE")  # toggle to vary (fix=1, legacy=0)
    env = os.environ.copy()
    env[var] = causal
    env["ARC_OUT"] = out_path
    env["ARC_ROOT"] = ROOT
    print(f"[measure] running backtest with {var}={causal} ...", file=sys.stderr)
    p = subprocess.run([sys.executable, "-c", _RUN], cwd=MODEL_DIR, env=env,
                       capture_output=True, text=True, timeout=timeout)
    if not os.path.exists(out_path):
        raise RuntimeError(f"run failed (causal={causal}); stderr tail:\n{p.stderr[-2000:]}")
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
    fixed = _pick(_run("1", timeout))   # causal fix ON
    legacy = _pick(_run("0", timeout))  # legacy look-ahead
    print("\n=== CAUSAL-WINSORIZE LEAKAGE FIX: BACKTEST IMPACT ===")
    print(f"{'metric':24} {'legacy(leak)':>14} {'causal(fix)':>14} {'delta':>12}")
    for k in ["overlay_sharpe", "overlay_total_return", "overlay_max_drawdown", "overlay_win_rate", "mean_ic"]:
        a, b = legacy.get(k), fixed.get(k)
        delta = (b - a) if isinstance(a, (int, float)) and isinstance(b, (int, float)) else None
        fa = f"{a:.4f}" if isinstance(a, (int, float)) else str(a)
        fb = f"{b:.4f}" if isinstance(b, (int, float)) else str(b)
        fd = f"{delta:+.4f}" if isinstance(delta, (int, float)) else ""
        print(f"{k:24} {fa:>14} {fb:>14} {fd:>12}")
    print("\nPer-instrument IC (causal fix):", json.dumps(fixed.get("ic_per_instrument", {})))
    print("Per-instrument IC (legacy):    ", json.dumps(legacy.get("ic_per_instrument", {})))


if __name__ == "__main__":
    main()
