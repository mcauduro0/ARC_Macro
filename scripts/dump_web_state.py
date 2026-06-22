"""Produce the engine-heavy web snapshot for the ARC 2.0 UI: run the co-pilot proposals for every booked
sleeve (the part that needs the macro engine, ~30-60s) and write them to state/web/state.json.

The FastAPI bridge (arc/webapi/app.py) reads this cache for the proposals + macro context and merges it
with the live (fast) JSONL ledger reads. Run it from the monthly accrual cycle, a cron, or by hand:

  python scripts/dump_web_state.py

It books each sleeve idempotently (so the proposal's decision exists for the UI to act on), advances the
loop with the live VaR/ES gate on, and serializes each OperatorProposal. The macro context (r*, regime) is
left for a later phase; the ledger-derived state the UI shows is always served live by the API regardless.
"""

from __future__ import annotations

import json
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

EVAL_AT_N = 24
DSR_MIN = 0.50
N_TRIALS = {"momentum": 45, "nowcast": 55, "fiscal_momentum": 69}

# Curated state-variable labels — only those actually present in feature_df are emitted (never invented).
_STATE_VAR_LABELS = {
    "Z_real_diff": "real rate diff", "Z_fiscal": "fiscal stress", "Z_dxy": "global USD (DXY)",
    "Z_vix": "global risk (VIX)", "Z_cds_br": "BR credit (CDS)", "Z_rstar_composite": "r* level",
    "Z_beer": "FX misalignment (BEER)", "Z_reer_gap": "REER gap", "Z_term_premium": "term premium",
    "Z_policy_gap": "policy gap (SELIC-SELIC*)", "Z_infl_surprise": "inflation surprise",
    "Z_tot": "terms of trade",
}
_FX_SPOT_CANDIDATES = ("ptax", "usdbrl", "usd_brl", "brl", "brl_spot", "fx", "spot")
_DI_TENORS = [("di_3m", "3M"), ("di_6m", "6M"), ("di_1y", "1Y"), ("di_2y", "2Y"),
              ("di_3y", "3Y"), ("di_5y", "5Y"), ("di_10y", "10Y")]


def _ts_date(ts) -> str:
    d = getattr(ts, "date", None)
    return str(d() if callable(d) else ts)


def _monthly_keys(monthly) -> list:
    """``data_layer.monthly`` may be a DataFrame OR a dict of Series — handle both."""
    if monthly is None:
        return []
    if hasattr(monthly, "columns"):
        return list(monthly.columns)
    if isinstance(monthly, dict):
        return list(monthly.keys())
    return []


def _monthly_series(monthly, name):
    import pandas as pd
    try:
        if hasattr(monthly, "columns"):
            if name in monthly.columns:
                return pd.Series(monthly[name]).dropna()
        elif isinstance(monthly, dict):
            if name in monthly:
                return pd.Series(monthly[name]).dropna()
    except Exception:  # noqa: BLE001
        return None
    return None


def _extract_macro(e) -> dict:
    """Defensive, HONEST extraction of macro engine context for the UI. Every field is emitted ONLY when it
    is genuinely populated by the engine; otherwise it is null and a note records why. Critically: the regime
    model is NOT fit by ``initialize()`` (it is fit lazily in ``step``), so we fit it explicitly here and
    refuse to emit the unfit 1/3 placeholder. Nothing is fabricated; absence is reported as absence."""
    import numpy as np
    import pandas as pd

    notes: list[str] = []
    macro: dict = {"as_of": None, "rstar": None, "regime": None, "state_vars": None,
                   "fx_fair": None, "di_curve": None, "notes": notes}
    fe = getattr(e, "feature_engine", None)
    dl = getattr(e, "data_layer", None)

    # --- regime probabilities (must fit explicitly; initialize() leaves the model unfit) ---
    try:
        rm = getattr(e, "regime_model", None)
        if rm is not None and getattr(rm, "regime_probs", None) is None and hasattr(rm, "fit"):
            rm.fit()  # full-sample causal (filtered) fit; populates regime_probs
        rp = getattr(rm, "regime_probs", None)
        if rp is not None and len(rp) > 0:
            num = rp.select_dtypes("number")
            var_ok = num.shape[1] > 0 and float(np.nanstd(num.to_numpy())) > 1e-6
            if var_ok:
                latest = {k: round(float(v), 4) for k, v in rp.iloc[-1].items()
                          if isinstance(v, (int, float, np.floating))}
                hist = [{"date": _ts_date(ts),
                         "probs": {k: round(float(v), 4) for k, v in row.items()
                                   if isinstance(v, (int, float, np.floating))}}
                        for ts, row in rp.tail(36).iterrows()]
                macro["regime"] = {"latest": latest, "labels": list(latest.keys()), "history": hist}
            else:
                notes.append("regime: probabilities are the unfit/degenerate placeholder — omitted")
        else:
            notes.append("regime: regime_probs unavailable after fit — omitted")
    except Exception as exc:  # noqa: BLE001 — never let macro extraction take the dump down
        notes.append(f"regime: extraction failed ({type(exc).__name__}: {exc}) — omitted")

    # --- composite r* (neutral real rate) ---
    try:
        rs = getattr(fe, "_composite_rstar", None)
        if rs is not None and len(rs) > 0:
            rs = pd.Series(rs).dropna()
            if len(rs) > 0:
                macro["rstar"] = {
                    "latest": round(float(rs.iloc[-1]), 3), "unit": "% real (neutral rate)",
                    "history": [[_ts_date(ts), round(float(v), 3)] for ts, v in rs.tail(36).items()]}
        if macro["rstar"] is None:
            notes.append("rstar: _composite_rstar unavailable — omitted")
    except Exception as exc:  # noqa: BLE001
        notes.append(f"rstar: extraction failed ({type(exc).__name__}: {exc}) — omitted")

    # --- state variables (curated Z_ features that actually exist) ---
    try:
        fdf = getattr(fe, "feature_df", None)
        if fdf is not None and len(fdf) > 0:
            last = fdf.iloc[-1]
            sv = [{"key": k, "label": lab, "value": round(float(last[k]), 3)}
                  for k, lab in _STATE_VAR_LABELS.items()
                  if k in fdf.columns and last[k] == last[k]]
            macro["state_vars"] = sv or None
            if not sv:
                notes.append("state_vars: no curated Z_ features present — omitted")
        else:
            notes.append("state_vars: feature_df unavailable — omitted")
    except Exception as exc:  # noqa: BLE001
        notes.append(f"state_vars: extraction failed ({type(exc).__name__}: {exc}) — omitted")

    # --- FX fair value vs spot ---
    try:
        fair = getattr(fe, "_fx_fair", None)
        monthly = getattr(dl, "monthly", None)
        spot = None
        for cand in _FX_SPOT_CANDIDATES:
            s = _monthly_series(monthly, cand)
            if s is not None and len(s) > 0:
                spot = float(s.iloc[-1]); break  # noqa: E702
        if fair is not None and float(fair) == float(fair):
            fairf = float(fair)
            mis = round((spot / fairf - 1.0) * 100.0, 2) if (spot and fairf) else None
            macro["fx_fair"] = {"fair": round(fairf, 4), "spot": (round(spot, 4) if spot else None),
                                "misalignment_pct": mis}
            if spot is None:
                notes.append("fx_fair: spot not found among monthly keys — fair only")
        else:
            notes.append("fx_fair: _fx_fair unavailable — omitted")
    except Exception as exc:  # noqa: BLE001
        notes.append(f"fx_fair: extraction failed ({type(exc).__name__}: {exc}) — omitted")

    # --- DI curve levels (only tenors present in monthly) ---
    try:
        monthly = getattr(dl, "monthly", None)
        pts = []
        for col, lab in _DI_TENORS:
            s = _monthly_series(monthly, col)
            if s is not None and len(s) > 0:
                pts.append({"tenor": lab, "rate": round(float(s.iloc[-1]), 3)})
        macro["di_curve"] = pts or None
        if not pts:
            keys = [str(k) for k in _monthly_keys(monthly)]
            di_like = [k for k in keys if "di" in k.lower()][:8]
            notes.append(f"di_curve: no di_* levels among monthly keys (di-like seen: {di_like}) — omitted")
    except Exception as exc:  # noqa: BLE001
        notes.append(f"di_curve: extraction failed ({type(exc).__name__}: {exc}) — omitted")

    try:
        macro["as_of"] = _ts_date(e.data_layer.ret_df.index[-1])
    except Exception:  # noqa: BLE001
        pass
    return macro


def main() -> None:
    from dataclasses import asdict

    import pandas as pd

    import macro_risk_os_v2 as eng
    from arc.autonomy import PaperLedger, book_trial, build_signal
    from arc.autonomy.copilot import propose
    from arc.autonomy.risk_gate import RiskLimits
    from arc.autonomy.source import knowledge_time, monthly_return_provider
    from arc.autonomy.spec import SPECS
    from arc.webapi.state import STATE_KEY

    print("[dump] initializing engine (PIT returns)...", file=sys.stderr)
    e = eng.ProductionEngine(eng.DEFAULT_CONFIG)
    e.initialize()
    ret_df, monthly = e.data_layer.ret_df, e.data_layer.monthly
    data_through = str(ret_df.index[-1].date())
    state_root = os.path.join(ROOT, "state", "paper")
    risk_limits = RiskLimits()

    proposals = {}
    for name, spec in SPECS.items():
        inst, kind = spec["instrument"], spec["kind"]
        if inst not in ret_df.columns:
            print(f"[dump] WARNING: '{inst}' not in ret_df — skipping {name}", file=sys.stderr)
            continue
        ledger = PaperLedger(os.path.join(state_root, STATE_KEY[name]))
        rets = ret_df[inst].dropna()
        provider = monthly_return_provider(rets, pub_lag_days=1)
        signal = build_signal(spec, monthly)
        signal_provider = None
        if signal is not None:
            signal = pd.Series(signal).dropna()
            signal_provider = lambda asof, _s=signal: _s[_s.index <= pd.Timestamp(asof)]  # noqa: E731

        research_cutoff = (rets.index[-1] + pd.offsets.MonthEnd(0)).strftime("%Y-%m-%d")
        book_trial(ledger, spec=spec, n_trials=N_TRIALS[kind], sr_std=None, eval_at_n=EVAL_AT_N,
                   dsr_min=DSR_MIN, forward_start=research_cutoff, issued_by="owner")

        last_known = knowledge_time(rets.index[-1] + pd.offsets.MonthEnd(0), 1)
        p = None
        for mo in [m for m in rets.index if knowledge_time(m, 1) <= last_known]:
            p = propose(knowledge_time(mo, 1), provider, ledger, spec=spec, signal_provider=signal_provider,
                        vol_target=0.10, risk_limits=risk_limits, strategy=name, run_id="dump")
        if p is not None:
            proposals[name] = asdict(p)
            print(f"[dump] {name}: proposal for {p.month} action={p.action_suggestion} "
                  f"pos={p.proposed_position}", file=sys.stderr)

    out = {
        "as_of": str(last_known.date()),
        "dumped_at": str(last_known.date()),  # stamp with the knowledge date (deterministic, repo norm)
        "data_through": data_through,
        "proposals": proposals,
        "macro": _extract_macro(e),  # honest, defensive engine context (real fields only; null otherwise)
    }
    out_dir = os.path.join(ROOT, "state", "web")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "state.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, default=str)
    print(f"[dump] wrote {len(proposals)} proposal(s) + meta to {out_path}")


if __name__ == "__main__":
    main()
