"""Phase 4.5 — live validation + collection for the new connectors (NTN-B, CFTC, BCB flows).

Best-effort: fetches each new catalog series through its adapter, reports coverage (n, date range), and
persists the result to the engine data dir as ``{SERIES_ID}.csv`` so it is available for future gating
(e.g. the real-curve track, previously dead for lack of NTN-B history). Network failures are reported
honestly per series, never silently substituted. Run: python scripts/collect_connectors.py
"""

from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
DATA_DIR = os.path.join(ROOT, "server", "model", "data")


def main() -> None:
    import pandas as pd

    from arc.data.adapters import CftcCotAdapter, TesouroNtnbAdapter, build_monthly_flow
    from arc.data.catalog import get_contract

    os.makedirs(DATA_DIR, exist_ok=True)
    results = []

    def _save(series_id, s):
        s = pd.Series(s).dropna().sort_index()
        path = os.path.join(DATA_DIR, f"{series_id}.csv")
        s.to_csv(path, header=False)
        rng = f"{s.index[0].date()}..{s.index[-1].date()}" if len(s) else "empty"
        results.append((series_id, len(s), rng, "OK"))

    def _fail(series_id, exc):
        results.append((series_id, 0, "-", f"{type(exc).__name__}: {str(exc)[:60]}"))

    # --- NTN-B real yields (fetch the big CSV ONCE, slice both tenors) ---
    try:
        ad = TesouroNtnbAdapter()
        raw = ad.fetch_raw(get_contract("NTNB_REAL_5Y"))
        wide = ad.parse(raw)
        for sid in ["NTNB_REAL_5Y", "NTNB_REAL_10Y"]:
            if sid in wide.columns:
                _save(sid, wide[sid])
            else:
                _fail(sid, RuntimeError("tenor column missing"))
    except Exception as exc:  # noqa: BLE001
        _fail("NTNB_REAL_5Y", exc); _fail("NTNB_REAL_10Y", exc)

    # --- CFTC BRL net speculative positioning ---
    try:
        ad = CftcCotAdapter()
        s = ad.parse(ad.fetch_raw(get_contract("CFTC_BRL_NET_SPEC")))
        _save("CFTC_BRL_NET_SPEC", s)
    except Exception as exc:  # noqa: BLE001
        _fail("CFTC_BRL_NET_SPEC", exc)

    # --- BCB external flows ---
    for sid in ["IDP_FLOW", "PORTFOLIO_FLOW"]:
        try:
            _save(sid, build_monthly_flow(sid))
        except Exception as exc:  # noqa: BLE001
            _fail(sid, exc)

    print("\n" + "=" * 78)
    print("PHASE 4.5 — CONNECTOR LIVE COLLECTION")
    print("=" * 78)
    print(f"  {'series':22s} {'n':>5s}  {'range':24s} status")
    print("  " + "-" * 70)
    for sid, n, rng, status in results:
        print(f"  {sid:22s} {n:>5d}  {rng:24s} {status}")
    print(f"\n  saved CSVs (where OK) to {DATA_DIR}")


if __name__ == "__main__":
    main()
