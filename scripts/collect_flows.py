"""Robust, provenance-honest collection of the BCB external-flow series (IDP, portfolio).

For each of IDP_FLOW / PORTFOLIO_FLOW it tries the PRIMARY BCB SGS route first
(``build_monthly_flow``); on any Exception (e.g. the 502s observed on api.bcb.gov.br) it
falls back to ``fetch_flow_ipeadata`` — which ONLY adopts an IPEADATA series if its metadata
unambiguously confirms it is the SAME BCB BPM6 concept (Bacen as source). An unconfirmable
match is reported as a failure, NEVER silently substituted with a different series.

The route decision is EXPLICIT and observable: :func:`route_flow` returns the route actually
taken in {"SGS" | "IPEADATA" | "FAILED"} plus the provenance string, and the CLI prints a
one-line SGS health banner (via ``sgs_is_up()``) up top. The same ``route_flow`` is used by
the CLI and by the tests, so what is tested is exactly what runs.

Any OK series is persisted to the engine data dir as ``{SERIES_ID}.csv`` (header-less, the
format ``collect_connectors.py`` uses) so it is available for gating. The status table prints
the ROUTE actually used and the provenance, and network failures are reported honestly per
series.

Run: python scripts/collect_flows.py [--source {auto,sgs,ipeadata}]
  auto     (default) — SGS first, IPEADATA only if SGS fails (the production behavior).
  sgs      — force the canonical SGS route only (FAILED if SGS is down; no fallback).
  ipeadata — force the provenance-verified IPEADATA fallback only (for tests/ops).
"""

from __future__ import annotations

import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
DATA_DIR = os.path.join(ROOT, "server", "model", "data")

FLOW_IDS = ["IDP_FLOW", "PORTFOLIO_FLOW"]
SOURCES = ("auto", "sgs", "ipeadata")


def route_flow(series_id: str, *, source: str = "auto"):
    """Resolve ONE flow series to ``(series, route, provenance)`` — the route contract.

    ``route`` is one of:
      * ``"SGS"``      — canonical BCB SGS used (``series`` is the parsed month-end Series).
      * ``"IPEADATA"`` — SGS unavailable, provenance-VERIFIED IPEADATA fallback adopted.
      * ``"FAILED"``   — neither route yielded a confirmed series; ``series is None`` and the
                         ``provenance`` string carries the honest reason(s). NOTHING is fabricated.

    ``source`` forces a route for tests/ops:
      * ``"auto"``     — SGS first, IPEADATA only if SGS raises (production behavior).
      * ``"sgs"``      — SGS only; if it raises -> FAILED (no fallback).
      * ``"ipeadata"`` — IPEADATA only; if it raises -> FAILED (no SGS attempt).

    Pure routing logic over the two adapter calls — the only network is whatever the
    adapters do lazily. Never substitutes a different series: a non-confirmable IPEADATA
    match raises inside ``fetch_flow_ipeadata`` and surfaces here as ``FAILED``.
    """
    from arc.data.adapters.bcb_flows import build_monthly_flow, fetch_flow_ipeadata

    if source not in SOURCES:
        raise ValueError(f"unknown source {source!r}; expected one of {SOURCES}")

    sgs_reason = ""

    # 1) PRIMARY: BCB SGS (unless explicitly forced to ipeadata).
    if source in ("auto", "sgs"):
        try:
            s = build_monthly_flow(series_id)
            return s, "SGS", "SGS (primary, BCB BPM6)"
        except Exception as sgs_exc:  # noqa: BLE001 — fall through to fallback / FAILED
            sgs_reason = f"{type(sgs_exc).__name__}: {str(sgs_exc)[:60]}"
            if source == "sgs":  # forced SGS-only: do NOT fall back.
                return None, "FAILED", f"SGS forced but down [{sgs_reason}]"

    # 2) FALLBACK: IPEADATA (only adopted if the BPM6 match is confirmed).
    if source in ("auto", "ipeadata"):
        try:
            s, prov = fetch_flow_ipeadata(series_id)
            down_note = f" (SGS down: {sgs_reason})" if sgs_reason else ""
            prov_str = (
                f"IPEADATA {prov.get('sercodigo')} | FONTE={prov.get('fonte')} | "
                f"{prov.get('periodicidade')} | {prov.get('unidade')} | "
                f"==SGS {prov.get('sgs_equivalent')}{down_note}"
            )
            return s, "IPEADATA", prov_str
        except Exception as ipea_exc:  # noqa: BLE001 — both routes down / unconfirmable
            sgs_part = f"SGS [{sgs_reason}]; " if sgs_reason else ""
            return None, "FAILED", f"{sgs_part}IPEADATA [{ipea_exc}]"

    # source == "sgs" with no SGS failure is handled above; defensive fallthrough.
    return None, "FAILED", "no route attempted"


def main(argv=None) -> None:
    import pandas as pd

    from arc.data.adapters.bcb_flows import sgs_is_up

    parser = argparse.ArgumentParser(description="Collect BCB external-flow series (SGS primary, IPEADATA fallback).")
    parser.add_argument(
        "--source",
        choices=SOURCES,
        default="auto",
        help="route to force: auto (SGS->IPEADATA), sgs (canonical only), ipeadata (fallback only).",
    )
    args = parser.parse_args(argv)

    os.makedirs(DATA_DIR, exist_ok=True)
    results = []  # (series_id, n, range, route, status, provenance)

    # Health banner: probe SGS up top so the operator sees which source will be canonical.
    up = sgs_is_up()
    if up:
        print("BCB SGS: UP -> using canonical source")
    else:
        print("BCB SGS: DOWN (HTTP error/timeout) -> provenance-verified IPEADATA fallback")
    if args.source != "auto":
        print(f"  (--source {args.source}: route forced)")

    def _save(series_id, s, route, provenance=""):
        s = pd.Series(s).dropna().sort_index()
        path = os.path.join(DATA_DIR, f"{series_id}.csv")
        s.to_csv(path, header=False)
        rng = f"{s.index[0].date()}..{s.index[-1].date()}" if len(s) else "empty"
        results.append((series_id, len(s), rng, route, "OK", provenance))

    for sid in FLOW_IDS:
        series, route, provenance = route_flow(sid, source=args.source)
        if route == "FAILED" or series is None:
            results.append((sid, 0, "-", route, provenance, ""))
        else:
            _save(sid, series, route, provenance=provenance)

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
