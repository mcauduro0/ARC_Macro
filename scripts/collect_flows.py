"""Robust, provenance-honest collection of the BCB external-flow series (IDP, portfolio).

For each of IDP_FLOW / PORTFOLIO_FLOW it tries the PRIMARY BCB SGS route first
(``build_monthly_flow``); on any Exception (e.g. the 502s observed on api.bcb.gov.br) it
falls back to ``fetch_flow_ipeadata`` — which ONLY adopts an IPEADATA series if its metadata
unambiguously confirms it is the SAME BCB BPM6 concept (Bacen as source). An unconfirmable
match is reported as a failure, NEVER silently substituted with a different series.

Any OK series is persisted to the engine data dir as ``{SERIES_ID}.csv`` (header-less, the
format ``collect_connectors.py`` uses) so it is available for gating. The status table prints
the ROUTE actually used and the provenance, and network failures are reported honestly per
series. Run: python scripts/collect_flows.py
"""

from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
DATA_DIR = os.path.join(ROOT, "server", "model", "data")

FLOW_IDS = ["IDP_FLOW", "PORTFOLIO_FLOW"]


def main() -> None:
    import pandas as pd

    from arc.data.adapters.bcb_flows import build_monthly_flow, fetch_flow_ipeadata

    os.makedirs(DATA_DIR, exist_ok=True)
    results = []  # (series_id, n, range, route, status, provenance)

    def _save(series_id, s, route, provenance=""):
        s = pd.Series(s).dropna().sort_index()
        path = os.path.join(DATA_DIR, f"{series_id}.csv")
        s.to_csv(path, header=False)
        rng = f"{s.index[0].date()}..{s.index[-1].date()}" if len(s) else "empty"
        results.append((series_id, len(s), rng, route, "OK", provenance))

    def _fail(series_id, route, exc):
        results.append((series_id, 0, "-", route, f"{type(exc).__name__}: {str(exc)[:70]}", ""))

    for sid in FLOW_IDS:
        # 1) PRIMARY: BCB SGS.
        try:
            s = build_monthly_flow(sid)
            _save(sid, s, "SGS", provenance="SGS (primary, BCB BPM6)")
            continue
        except Exception as sgs_exc:  # noqa: BLE001 — fall through to the IPEADATA fallback
            sgs_reason = f"{type(sgs_exc).__name__}: {str(sgs_exc)[:60]}"

        # 2) FALLBACK: IPEADATA (only adopted if the BPM6 match is confirmed).
        try:
            s, prov = fetch_flow_ipeadata(sid)
            prov_str = (
                f"IPEADATA {prov.get('sercodigo')} | FONTE={prov.get('fonte')} | "
                f"{prov.get('periodicidade')} | {prov.get('unidade')} | "
                f"==SGS {prov.get('sgs_equivalent')} (SGS down: {sgs_reason})"
            )
            _save(sid, s, "IPEADATA", provenance=prov_str)
        except Exception as ipea_exc:  # noqa: BLE001 — both routes down / unconfirmable
            _fail(sid, "SGS->IPEADATA", RuntimeError(f"SGS [{sgs_reason}]; IPEADATA [{ipea_exc}]"))

    print("\n" + "=" * 100)
    print("BCB EXTERNAL-FLOW COLLECTION (SGS primary, IPEADATA confirmed-fallback)")
    print("=" * 100)
    print(f"  {'series':16s} {'n':>5s}  {'range':24s} {'route':14s} status")
    print("  " + "-" * 92)
    for sid, n, rng, route, status, _prov in results:
        print(f"  {sid:16s} {n:>5d}  {rng:24s} {route:14s} {status}")
    print("\n  provenance:")
    for sid, _n, _rng, _route, _status, prov in results:
        if prov:
            print(f"    {sid:16s} {prov}")
    print(f"\n  saved CSVs (where OK) to {DATA_DIR}")


if __name__ == "__main__":
    main()
