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
        "macro": None,  # engine macro context (r* CI, regime) — filled in a later phase
    }
    out_dir = os.path.join(ROOT, "state", "web")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "state.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, default=str)
    print(f"[dump] wrote {len(proposals)} proposal(s) + meta to {out_path}")


if __name__ == "__main__":
    main()
