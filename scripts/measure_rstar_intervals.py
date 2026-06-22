"""Measure r* (State-Space / Kalman) credible intervals from the filtered posterior variance.

Reuses the engine's data layer to feed StateSpaceRStar exactly the series the engine feeds it
(see macro_risk_os_v2._build_composite_equilibrium, ~line 1545), runs .estimate(...) then
.credible_intervals(), and reports the latest r* +/- 95% credible interval, a few historical
rows, and the median CI width.

HONEST BY CONSTRUCTION: this is uncertainty quantification of the FILTERED r* estimate (a band
around the in-sample Kalman posterior), NOT a forecast and NOT a claim of alpha. The interval
comes purely from the filter's own state covariance P[0,0] under its fixed parameters.

Usage:
    python scripts/measure_rstar_intervals.py

Writes: server/model/output/measure_rstar_intervals.json
"""

from __future__ import annotations

import json

# === Engine preamble (MUST precede engine import) ===
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

import pandas as pd  # noqa: E402

import macro_risk_os_v2 as eng  # noqa: E402
from composite_equilibrium import StateSpaceRStar  # noqa: E402


def _series(monthly: dict, key: str) -> pd.Series:
    s = monthly.get(key, pd.Series(dtype=float))
    return s if isinstance(s, pd.Series) else pd.Series(dtype=float)


def main() -> int:
    e = eng.ProductionEngine(eng.DEFAULT_CONFIG)
    e.initialize()
    m = e.data_layer.monthly

    # === Exactly the series the engine feeds StateSpaceRStar.estimate(...) ===
    # macro_risk_os_v2 ~L1546: estimate(selic, ipca_12m, ipca_exp, ibc_br, debt_gdp, cds_5y)
    # selic: selic_over, falling back to selic_target (mirrors engine L1452-1454).
    selic = _series(m, "selic_over")
    if len(selic) == 0:
        selic = _series(m, "selic_target")
    ipca_yoy = _series(m, "ipca_yoy")
    ipca_exp = _series(m, "ipca_exp")
    ibc_br = _series(m, "ibc_br")
    debt_gdp = _series(m, "debt_gdp")
    cds_5y = _series(m, "cds_5y")

    model = StateSpaceRStar(window=120)
    rstar = model.estimate(selic, ipca_yoy, ipca_exp, ibc_br, debt_gdp, cds_5y)

    result: dict = {
        "note": (
            "Credible band around the FILTERED Kalman r* posterior (P[0,0]); "
            "uncertainty quantification, NOT a forecast and NOT alpha."
        ),
        "z": 1.96,
        "n_months": int(len(rstar)),
        "inputs_lengths": {
            "selic": int(len(selic)), "ipca_yoy": int(len(ipca_yoy)),
            "ipca_exp": int(len(ipca_exp)), "ibc_br": int(len(ibc_br)),
            "debt_gdp": int(len(debt_gdp)), "cds_5y": int(len(cds_5y)),
        },
    }

    if len(rstar) == 0:
        result["status"] = "insufficient_data"
        _emit(result)
        return 0

    ci = model.credible_intervals(z=1.96)
    result["status"] = "ok"

    last = ci.iloc[-1]
    result["latest"] = {
        "date": str(ci.index[-1]),
        "rstar": float(last["rstar"]),
        "std": float(last["std"]),
        "lo": float(last["lo"]),
        "hi": float(last["hi"]),
        "width": float(last["hi"] - last["lo"]),
    }

    width = (ci["hi"] - ci["lo"])
    result["median_ci_width"] = float(width.median())
    result["mean_ci_width"] = float(width.mean())

    # A few historical rows (evenly spaced, including first and last).
    n = len(ci)
    if n <= 6:
        pick = list(range(n))
    else:
        pick = sorted(set([0, n // 4, n // 2, (3 * n) // 4, n - 1]))
    result["history"] = [
        {
            "date": str(ci.index[i]),
            "rstar": round(float(ci.iloc[i]["rstar"]), 4),
            "std": round(float(ci.iloc[i]["std"]), 4),
            "lo": round(float(ci.iloc[i]["lo"]), 4),
            "hi": round(float(ci.iloc[i]["hi"]), 4),
        }
        for i in pick
    ]

    _emit(result)
    return 0


def _emit(result: dict) -> None:
    out_path = os.path.join(eng.OUTPUT_DIR, "measure_rstar_intervals.json")
    with open(out_path, "w") as fh:
        json.dump(result, fh, indent=2)

    print(json.dumps(result, indent=2))
    if result.get("status") == "ok":
        lt = result["latest"]
        print(
            f"\nLatest r* ({lt['date']}): {lt['rstar']:.2f}% "
            f"[95% CI {lt['lo']:.2f}, {lt['hi']:.2f}], width={lt['width']:.2f}pp; "
            f"median CI width={result['median_ci_width']:.2f}pp",
            file=sys.stderr,
        )
    print(f"[measure] wrote {out_path}", file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
