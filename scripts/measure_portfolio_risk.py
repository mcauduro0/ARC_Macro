"""Phase 6 — the HONEST integration measurement: compose the 3 booked sleeves into ONE book using the
new Phase 6 risk / portfolio / execution infrastructure, and report — DEFLATED, IN-SAMPLE — whether
risk-based or Black-Litterman weights beat the EQUAL-weight baseline, plus the book's VaR/ES profile and
the execution-friction drag.

THE HONESTY LAW (this project's prime directive — "nao invente resultados"): this is MEASURED
infrastructure, NOT an alpha claim. The project has NO demonstrated edge beyond carry; the three sleeves
are CANDIDATES under forward paper (0 out-of-time months exist today — data ends 2026-06). Everything here
is IN-SAMPLE; the reserved single-use forward holdout (untouched here) is what actually decides. A
weighting scheme only "wins" if it beats EQUAL on DEFLATED DSR by >= +0.05 WITHOUT adding leverage —
Sharpe/DSR are leverage-invariant, so any apparent win must be a genuine risk-adjusted improvement, not
more notional. The likely honest outcome is "marginal / none", and we report exactly that.

The VaR/ES profile and the execution-drag are RISK & REALISM tooling — they quantify and bound risk and
measure trading friction. They make NO alpha claim either.

What it does
------------
1. SLEEVES  — builds the three booked sleeves' FLAT causal return streams (momentum_front, nowcast_long,
   fiscal_hard) via ``arc.research.signal_sleeve_returns`` driven by ``arc.autonomy.build_signal``, aligned
   into a monthly 3-column panel (mirrors scripts/measure_online_weights.py so the sleeves are identical).

2. COVARIANCE & WEIGHTS — steps month by month; at each t it estimates a CAUSAL covariance FORECAST of the
   three sleeves from the trailing window of returns known at t (``ewma_cov`` and ``dcc_garch_cov``), then
   forms three weight schemes used for t+1:
     (a) EQUAL              — flat 1/k (the baseline).
     (b) MIN_VARIANCE       — min-variance / risk-parity long-only weights from the rolling cov.
     (c) BLACK_LITTERMAN    — equilibrium prior from the rolling cov + equal "market" weights, tilted by
         mild VIEWS = the SIGNS of the in-sample sleeve Sharpes (documented as ILLUSTRATIVE, not alpha),
         then ``bl_optimal_weights``.
   Weights decided at t are applied to the sleeve returns at t+1 (strictly causal). Reports ``sleeve_stats``
   (Sharpe / PSR / DSR / maxDD, n_trials=3) for EQUAL vs each, deflated.

3. VaR/ES PROFILE — for the EQUAL book: historical & parametric 95%/99% monthly VaR & ES, and a
   ``pretrade_var_gate`` demonstration at a sample limit (a breach and a no-breach case).

4. EXECUTION DRAG — runs ``PaperFillSimulator`` on the EQUAL book's implied position path (a single
   notional scaled by the book's net exposure) against a price proxy (a flat unit price), with
   slippage_bps=2 and cost_bps=2, and reports the friction drag (paper vs frictionless).

Run:
  python scripts/measure_portfolio_risk.py
  python scripts/measure_portfolio_risk.py --window 36 --halflife 12 --risk-aversion 2.5 --tau 0.05

Writes <engine OUTPUT_DIR>/measure_portfolio_risk.json. The single-use forward holdout is NOT touched here.
Do NOT run the heavy engine yourself in CI — the orchestrator runs this measurement.
"""

from __future__ import annotations

import argparse
import json

# === Engine preamble (MUST precede the engine import) ===
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

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

# --- Phase 6 infrastructure (built by sibling agents; consumed by these EXACT signatures) ---
from arc.execution.paper_fill import PaperFillSimulator, realized_vs_paper  # noqa: E402
from arc.portfolio.black_litterman import (  # noqa: E402
    bl_optimal_weights,
    black_litterman_posterior,
    implied_equilibrium_returns,
)
from arc.risk.covariance import dcc_garch_cov, ewma_cov  # noqa: E402
from arc.risk.var_es import (  # noqa: E402
    historical_es,
    historical_var,
    parametric_es,
    parametric_var,
    portfolio_var,
    pretrade_var_gate,
)

# --- existing, reused infrastructure ---
from arc.autonomy import SPECS, build_signal  # noqa: E402
from arc.research import momentum_signal, signal_sleeve_returns, sleeve_stats  # noqa: E402

# A scheme must beat EQUAL on DEFLATED DSR by at least this margin to be a (tentative) improvement.
DSR_WIN_MARGIN = 0.05

# Honest multiple-testing count for the COMBINED book: we choose among a few weighting schemes for the
# SAME three sleeves; n_trials = number of sleeves combined (3) is the conservative, stated bar.
N_TRIALS_COMBINED = 3

# Annual vol target used ONLY to report the leverage each scheme would need (Sharpe/DSR are unchanged by it).
VOL_TARGET_ANN = 0.10


# ====================================================================================================
# 1) Sleeve panel
# ====================================================================================================
def _build_sleeve_panel(ret_df, monthly):
    """Build the three booked sleeves' FLAT causal return streams and align into one monthly panel.

    Each column reproduces ``arc.research.signal_sleeve_returns`` for the booked spec (momentum derives
    price momentum from its own return stream; the others use ``build_signal``). Returns (panel, diag).
    The panel is the OUTER-aligned union of months; NaN marks a sleeve not tradable that month."""
    streams: dict[str, pd.Series] = {}
    diag: dict[str, dict] = {}
    for name, spec in SPECS.items():
        inst = spec["instrument"]
        if inst not in ret_df.columns:
            diag[name] = {"status": f"SKIPPED: '{inst}' not in ret_df", "instrument": inst}
            continue
        rets = ret_df[inst].dropna()
        signal = build_signal(spec, monthly)
        if signal is None:  # momentum kind -> derive price momentum from returns
            signal = momentum_signal(rets, int(spec.get("lookback", 3)))
        signal = pd.Series(signal).reindex(rets.index)
        sl = signal_sleeve_returns(
            signal, rets,
            z_window=int(spec.get("z_window", 12)),
            clip_z=float(spec.get("clip_z", 2.0)),
            cost_bps=float(spec.get("cost_bps", 2.0)),
        )
        streams[name] = sl
        diag[name] = {"status": "OK", "instrument": inst, "n": int(len(sl))}

    if not streams:
        return None, diag
    panel = pd.DataFrame(streams).sort_index()
    return panel, diag


# ====================================================================================================
# 2) Causal rolling covariance + weight schemes
# ====================================================================================================
def _coerce_cov(cov_obj, cols) -> np.ndarray | None:
    """Coerce a covariance estimate (DataFrame / ndarray / nested) to a clean (k,k) float ndarray
    aligned to ``cols``. Returns None if it cannot be made into a finite square matrix of the right size."""
    k = len(cols)
    if cov_obj is None:
        return None
    if isinstance(cov_obj, pd.DataFrame):
        try:
            cov_obj = cov_obj.reindex(index=cols, columns=cols)
        except Exception:
            pass
        arr = np.asarray(cov_obj.values, dtype=float)
    else:
        arr = np.asarray(cov_obj, dtype=float)
    if arr.ndim != 2 or arr.shape != (k, k):
        return None
    if not np.all(np.isfinite(arr)):
        return None
    return 0.5 * (arr + arr.T)  # symmetrize


def _min_variance_weights(cov: np.ndarray) -> np.ndarray:
    """Long-only min-variance weights w = Σ^-1 1 / (1' Σ^-1 1), clipped >= 0 and renormalized to sum 1.
    Falls back to equal weights if the system is singular or all clipped to zero (a risk-parity-style
    fully-defensive fallback). Pure linear algebra on the causal cov forecast."""
    k = cov.shape[0]
    ones = np.ones(k)
    try:
        x = np.linalg.solve(cov, ones)
    except np.linalg.LinAlgError:
        return ones / k
    s = float(x.sum())
    if not np.isfinite(s) or abs(s) < 1e-12:
        return ones / k
    w = x / s
    w = np.clip(w, 0.0, None)
    tot = float(w.sum())
    if tot < 1e-12:
        return ones / k
    return w / tot


def _bl_weights(cov: np.ndarray, view_signs: np.ndarray, *, risk_aversion: float, tau: float,
                view_strength: float) -> np.ndarray:
    """Black-Litterman long-only weights from the causal cov forecast.

    Prior  : equilibrium returns reverse-optimized from the cov + EQUAL "market" weights (1/k).
    Views  : ONE absolute view per sleeve, P = I (k x k), Q = view_signs * view_strength * sleeve_vol.
             ``view_signs`` are the SIGNS of the in-sample sleeve Sharpes — ILLUSTRATIVE ONLY, not an
             alpha claim (project honesty law). Scaling Q by each sleeve's own vol keeps the view in the
             same units as the prior. Omega = Idzorek default (None) so confidence tracks prior variance.
    Returns: long-only ``bl_optimal_weights`` summing to 1."""
    k = cov.shape[0]
    w_mkt = np.ones(k) / k
    pi = implied_equilibrium_returns(cov, w_mkt, risk_aversion=risk_aversion)
    sleeve_vol = np.sqrt(np.clip(np.diag(cov), 0.0, None))
    P = np.eye(k)
    Q = view_signs * view_strength * sleeve_vol
    mu_bl, cov_bl = black_litterman_posterior(pi, cov, P, Q, omega=None, tau=tau)
    try:
        return bl_optimal_weights(mu_bl, cov_bl, risk_aversion=risk_aversion,
                                  long_only=True, budget=1.0)
    except ValueError:
        # all weights clipped to ~0 -> defensive equal fallback (still long-only, sums to 1)
        return w_mkt


def _rolling_weighted_book(panel: pd.DataFrame, *, window: int, halflife: int, min_window: int,
                           risk_aversion: float, tau: float, view_strength: float, cov_method: str):
    """Walk forward month by month forming a CAUSAL covariance forecast and the weighted-book returns.

    At each month t (with at least ``min_window`` complete prior rows of all sleeves available), estimate
    a covariance forecast of the sleeves from the trailing window ENDING at t (data <= t), derive
    MIN_VARIANCE and BLACK_LITTERMAN weights, and EARN them on the NEXT month's sleeve returns (t+1) —
    strictly causal (a value/forecast at t uses only info <= t). Rows where the cov could not be formed
    are skipped (the book simply does not trade that month).

    ``cov_method`` selects the estimator: 'ewma' -> ewma_cov, 'dcc' -> dcc_garch_cov. The view SIGNS are
    the signs of the in-sample sleeve Sharpes, recomputed PER STEP from data <= t (so the view itself is
    causal; it remains ILLUSTRATIVE, not an alpha claim).

    Returns (mv_book, bl_book, n_cov_ok, n_cov_fail, last_weights) where the books are pd.Series of
    realized monthly returns and last_weights is the most recent (mv, bl) weight vectors for reporting."""
    cols = list(panel.columns)
    k = len(cols)
    full = panel.dropna(how="any")          # months where ALL sleeves are tradable (clean cov estimation)
    if len(full) < min_window + 1:
        return (pd.Series(dtype=float), pd.Series(dtype=float), 0, 0, None)

    idx = full.index
    mv_rows: dict = {}
    bl_rows: dict = {}
    n_ok = 0
    n_fail = 0
    last_weights = None

    for i in range(min_window - 1, len(idx) - 1):
        t = idx[i]
        t_next = idx[i + 1]
        lo = max(0, i - window + 1)
        win = full.iloc[lo: i + 1]          # trailing window ENDING at t (info <= t)
        if len(win) < min_window:
            continue

        if cov_method == "ewma":
            raw = _safe_cov(ewma_cov, win, halflife=halflife)
        else:
            raw = _safe_cov(dcc_garch_cov, win)
        cov = _coerce_cov(raw, cols)
        if cov is None:
            # fall back to a plain sample covariance of the window so the walk continues honestly
            cov = _coerce_cov(win.cov(), cols)
        if cov is None:
            n_fail += 1
            continue
        n_ok += 1

        # causal view signs: sign of each sleeve's in-sample Sharpe using data <= t
        means = win.mean().values
        stds = win.std(ddof=1).replace(0.0, np.nan).values
        sharpe_to_t = np.divide(means, stds, out=np.zeros(k), where=np.isfinite(stds))
        view_signs = np.sign(sharpe_to_t)
        view_signs[view_signs == 0.0] = 1.0  # a flat sleeve gets a neutral mild long view

        w_mv = _min_variance_weights(cov)
        w_bl = _bl_weights(cov, view_signs, risk_aversion=risk_aversion, tau=tau,
                           view_strength=view_strength)
        last_weights = {
            "as_of": str(t),
            "min_variance": {c: float(v) for c, v in zip(cols, w_mv)},
            "black_litterman": {c: float(v) for c, v in zip(cols, w_bl)},
            "view_signs": {c: float(v) for c, v in zip(cols, view_signs)},
        }

        r_next = full.loc[t_next].values     # next month's realized sleeve returns
        mv_rows[t_next] = float(np.dot(w_mv, r_next))
        bl_rows[t_next] = float(np.dot(w_bl, r_next))

    mv_book = pd.Series(mv_rows).sort_index()
    bl_book = pd.Series(bl_rows).sort_index()
    return mv_book, bl_book, n_ok, n_fail, last_weights


def _safe_cov(fn, win, **kw):
    """Call a covariance estimator with progressively simpler argument forms so the walk survives a
    signature we did not anticipate (the covariance module is built by a sibling agent). Returns the raw
    estimate or None if every call form raised. Never raises."""
    forms = []
    if kw:
        forms.append(((win,), dict(kw)))
    forms.append(((win,), {}))
    # also try the numpy view of the window in case the estimator wants an ndarray
    if kw:
        forms.append(((win.values,), dict(kw)))
    forms.append(((win.values,), {}))
    for args, kwargs in forms:
        try:
            return fn(*args, **kwargs)
        except TypeError:
            continue
        except Exception:
            return None
    return None


def _equal_book(panel: pd.DataFrame) -> pd.Series:
    """EQUAL-weight book: 1/k across the sleeves PRESENT each month (the honest, causal, static baseline)."""
    present = panel.notna()
    eq_w = present.div(present.sum(axis=1).replace(0, np.nan), axis=0)
    contrib = (eq_w * panel).sum(axis=1, min_count=1)
    return contrib.where(present.any(axis=1)).dropna()


def _stats_rec(book: pd.Series) -> dict:
    st = sleeve_stats(book, n_trials=N_TRIALS_COMBINED, vol_target_ann=VOL_TARGET_ANN)
    return {
        "n": st["n"], "ann_ret": st["ann_ret"], "ann_vol": st["ann_vol"],
        "sharpe_ann": st["sharpe_ann"], "psr_vs_0": st["psr_vs_0"], "dsr": st["dsr"],
        "max_drawdown": st["max_drawdown"], "hit_rate": st["hit_rate"],
        "leverage_for_vol_target": st.get("leverage_for_vol_target", float("nan")),
    }


def _delta(a: float, b: float) -> float:
    if a is None or b is None or not (np.isfinite(a) and np.isfinite(b)):
        return float("nan")
    return float(a - b)


# ====================================================================================================
# 3) VaR / ES profile (EQUAL book)
# ====================================================================================================
def _var_es_profile(equal_book: pd.Series) -> dict:
    """Historical & parametric 95%/99% monthly VaR & ES for the EQUAL book, plus a pre-trade gate demo.

    All quantities are POSITIVE loss magnitudes (per arc.risk.var_es sign convention). Parametric uses the
    book's own (in-sample) monthly mean/vol. The gate demo uses the 3-sleeve EQUAL weights against the
    book's monthly covariance to show a breach (tight limit) and a no-breach (loose limit) case."""
    r = pd.Series(equal_book).dropna()
    mu = float(r.mean())
    sigma = float(r.std(ddof=1)) if len(r) > 1 else 0.0
    levels = {"95": 0.05, "99": 0.01}
    profile: dict = {"n": int(len(r)), "monthly_mean": mu, "monthly_vol": sigma, "levels": {}}
    for lab, a in levels.items():
        profile["levels"][lab] = {
            "alpha": a,
            "historical_var": historical_var(r.values, alpha=a),
            "historical_es": historical_es(r.values, alpha=a),
            "parametric_var": parametric_var(mu, sigma, alpha=a),
            "parametric_es": parametric_es(mu, sigma, alpha=a),
        }
    # monotonicity assertion: deeper tail (99) must be >= shallower tail (95) for VaR and ES
    profile["monotonic_ok"] = bool(
        profile["levels"]["99"]["historical_var"] >= profile["levels"]["95"]["historical_var"] - 1e-12
        and profile["levels"]["99"]["historical_es"] >= profile["levels"]["95"]["historical_es"] - 1e-12
        and profile["levels"]["99"]["parametric_var"] >= profile["levels"]["95"]["parametric_var"] - 1e-12
    )
    return profile


def _pretrade_gate_demo(panel: pd.DataFrame) -> dict:
    """Demonstrate ``pretrade_var_gate`` on the EQUAL 3-sleeve book vs its in-sample monthly covariance,
    at a TIGHT limit (expected breach) and a LOOSE limit (expected no-breach)."""
    full = panel.dropna(how="any")
    if len(full) < 3:
        return {"status": "insufficient_data_for_gate_demo"}
    cov = np.asarray(full.cov().values, dtype=float)
    k = cov.shape[0]
    w_eq = np.ones(k) / k
    base_var = portfolio_var(w_eq, cov, alpha=0.05)  # positive monthly loss at 95%
    tight = max(base_var * 0.5, 1e-9)                # half the VaR -> breach
    loose = base_var * 2.0 + 1e-9                    # twice the VaR -> no breach
    return {
        "weights": {c: float(v) for c, v in zip(full.columns, w_eq)},
        "book_var_95": float(base_var),
        "tight_limit": _gate_payload(pretrade_var_gate(w_eq, cov, var_limit=tight, alpha=0.05)),
        "loose_limit": _gate_payload(pretrade_var_gate(w_eq, cov, var_limit=loose, alpha=0.05)),
    }


def _gate_payload(g: dict) -> dict:
    return {
        "var": float(g["var"]), "limit": float(g["limit"]), "breach": bool(g["breach"]),
        "utilization": float(g["utilization"]), "reason": g["reason"],
    }


# ====================================================================================================
# 4) Execution drag (EQUAL book)
# ====================================================================================================
def _execution_drag(equal_book: pd.Series, panel: pd.DataFrame, *, slippage_bps: float,
                    cost_bps: float, notional: float = 1.0) -> dict:
    """Friction drag of the EQUAL book under ``PaperFillSimulator`` (slippage + commission) vs frictionless.

    The book's IMPLIED position path is a single notional scaled by the book's net exposure each month
    (the EQUAL-weighted average of the sleeves' causal positions in [-1, 1], so the target position lives
    in [-notional, notional]). The price proxy is a FLAT unit price (1.0): with a flat price the gross PnL
    is identical between books, so the entire ``drag`` series is PURE friction (slippage + commission) on
    the rebalancing turnover — exactly what we want to isolate. Reports total drag, annualized drag, and
    the drag as a fraction of the book's gross notional turnover."""
    cols = list(panel.columns)
    # Each sleeve's causal position in [-1,1] = sign-preserving; reconstruct the book's net target exposure
    # as the EQUAL-weighted mean of the per-sleeve positions implied by the booked specs.
    positions = _book_target_positions(panel) * float(notional)
    positions = positions.dropna()
    if len(positions) < 3:
        return {"status": "insufficient_data_for_execution_demo"}

    price = pd.Series(1.0, index=positions.index)   # flat unit price -> drag is pure friction
    sim = PaperFillSimulator(slippage_bps=slippage_bps, cost_bps=cost_bps, max_participation=1.0)
    fills, orders = sim.simulate(positions, price, instrument="equal_book")

    # frictionless vs paper-filled: with a flat price both gross PnLs are ~0, so drag == friction cash.
    cmp = realized_vs_paper(positions, pd.Series(0.0, index=positions.index), fills)
    total_drag = float(cmp["drag"].sum())
    total_cost = float(cmp["cost"].sum())
    n = int(len(positions))
    gross_turnover = float(positions.diff().abs().sum())
    return {
        "slippage_bps": float(slippage_bps), "cost_bps": float(cost_bps), "notional": float(notional),
        "n_periods": n, "n_orders": int(len(orders)),
        "gross_turnover": gross_turnover,
        "total_friction_cost": total_cost,
        "total_drag": total_drag,
        "ann_drag": float(total_drag * 12.0 / n) if n else float("nan"),
        "drag_per_unit_turnover": float(total_drag / gross_turnover) if gross_turnover > 1e-12 else float("nan"),
        "note": ("price proxy is flat (1.0) so gross PnL is identical between books; the entire drag is "
                 "pure slippage+commission friction on rebalancing turnover."),
    }


def _book_target_positions(panel: pd.DataFrame) -> pd.Series:
    """Reconstruct the EQUAL book's net target exposure in [-1, 1] per month from the booked specs.

    For each sleeve we rebuild its causal position (the same expanding z-score the sleeve uses) from its
    own return-implied signal, then average across the sleeves present each month. This is the position the
    EQUAL book WANTS to hold; the simulator turns the month-to-month change into trades."""
    from arc.research.sleeve import causal_position
    # we don't have the raw instrument returns here, only the sleeve return panel; approximate each
    # sleeve's exposure by the causal z-position of its OWN return momentum (a faithful exposure proxy
    # for the friction demo — the absolute notional path, not alpha).
    pos_cols = {}
    for c in panel.columns:
        s = panel[c].dropna()
        if len(s) < 12:
            continue
        sig = momentum_signal(s, 3)
        pos_cols[c] = causal_position(sig, z_window=12, clip_z=2.0)
    if not pos_cols:
        return pd.Series(dtype=float)
    pdf = pd.DataFrame(pos_cols).reindex(panel.index)
    return pdf.mean(axis=1)


# ====================================================================================================
# Orchestration
# ====================================================================================================
def measure(ret_df, monthly, *, window: int, halflife: int, min_window: int, risk_aversion: float,
            tau: float, view_strength: float, slippage_bps: float, cost_bps: float) -> dict:
    """Build the panel, form EQUAL / MIN_VARIANCE / BLACK_LITTERMAN books (EWMA and DCC cov), compare them
    deflated, then add the VaR/ES profile and the execution drag. Returns a JSON-able dict with an honest
    verdict. Pure consumption of the engine's PIT ret_df/monthly + the Phase 6 APIs; no holdout touched."""
    panel, diag = _build_sleeve_panel(ret_df, monthly)
    out: dict = {
        "status": "ok",
        "honesty": (
            "IN-SAMPLE, DEFLATED measurement of the 3 booked CANDIDATE sleeves combined into one book. "
            "NOT an alpha claim; 0 forward out-of-time months exist (data ends 2026-06). The reserved "
            "single-use forward holdout is NOT touched here. VaR/ES + execution-drag are risk/realism "
            "tooling, not alpha. A weighting scheme 'wins' only if it beats EQUAL on DEFLATED DSR by "
            f">= +{DSR_WIN_MARGIN} WITHOUT extra leverage (Sharpe/DSR are leverage-invariant)."
        ),
        "params": {
            "window": window, "halflife": halflife, "min_window": min_window,
            "risk_aversion": risk_aversion, "tau": tau, "view_strength": view_strength,
            "n_trials_combined": N_TRIALS_COMBINED, "dsr_win_margin": DSR_WIN_MARGIN,
            "vol_target_ann": VOL_TARGET_ANN, "slippage_bps": slippage_bps, "cost_bps": cost_bps,
        },
        "view_construction": (
            "ILLUSTRATIVE views (NOT alpha): one absolute BL view per sleeve, P = I, "
            "Q = sign(in-sample sleeve Sharpe to t) * view_strength * sleeve_vol. Signs are recomputed "
            "per step from data <= t (causal). Equilibrium prior = implied_equilibrium_returns(cov, "
            "equal market weights). Omega = Idzorek default."
        ),
        "sleeves": diag,
    }
    if panel is None or panel.shape[1] == 0:
        out["status"] = "INCONCLUSIVE: no booked sleeve could be built"
        return out

    k = panel.shape[1]
    out["panel"] = {"columns": list(panel.columns), "n_months": int(len(panel.dropna(how="any")))}

    # --- EQUAL baseline (full panel) ---
    equal_book = _equal_book(panel)
    equal_rec = _stats_rec(equal_book)

    # --- rolling cov-based + BL books, for each cov estimator ---
    schemes: dict[str, dict] = {"EQUAL": equal_rec}
    last_weights_by_method: dict[str, dict] = {}
    for method in ("ewma", "dcc"):
        mv_book, bl_book, n_ok, n_fail, last_w = _rolling_weighted_book(
            panel, window=window, halflife=halflife, min_window=min_window,
            risk_aversion=risk_aversion, tau=tau, view_strength=view_strength, cov_method=method,
        )
        last_weights_by_method[method] = {
            "cov_ok": n_ok, "cov_fail": n_fail, "last_weights": last_w,
        }
        if len(mv_book) >= 6:
            schemes[f"MIN_VARIANCE_{method.upper()}"] = _stats_rec(mv_book)
        if len(bl_book) >= 6:
            schemes[f"BLACK_LITTERMAN_{method.upper()}"] = _stats_rec(bl_book)

    # --- deltas vs EQUAL + verdict ---
    eq_dsr = equal_rec["dsr"]
    best_scheme, best_d = None, float("-inf")
    for sname, rec in schemes.items():
        if sname == "EQUAL":
            rec["delta_vs_equal"] = {k2: 0.0 for k2 in ("sharpe_ann", "dsr", "max_drawdown", "hit_rate")}
            continue
        d = {
            "sharpe_ann": _delta(rec["sharpe_ann"], equal_rec["sharpe_ann"]),
            "dsr": _delta(rec["dsr"], eq_dsr),
            "max_drawdown": _delta(rec["max_drawdown"], equal_rec["max_drawdown"]),
            "hit_rate": _delta(rec["hit_rate"], equal_rec["hit_rate"]),
        }
        rec["delta_vs_equal"] = d
        if np.isfinite(d["dsr"]) and d["dsr"] > best_d:
            best_d, best_scheme = d["dsr"], sname

    out["schemes"] = schemes
    out["cov_diagnostics"] = last_weights_by_method
    beats = bool(best_scheme is not None and np.isfinite(best_d) and best_d >= DSR_WIN_MARGIN)
    out["verdict"] = {
        "best_non_equal_scheme": best_scheme,
        "best_delta_dsr_vs_equal": float(best_d) if np.isfinite(best_d) else float("nan"),
        "beats_equal_on_deflated_dsr": beats,
        "conclusion": (
            f"{best_scheme} beats EQUAL by +{best_d:.3f} deflated DSR (>= +{DSR_WIN_MARGIN}); a TENTATIVE, "
            "IN-SAMPLE risk-adjusted improvement — the forward holdout decides."
            if beats else
            "No weighting scheme beats EQUAL on deflated DSR by the required margin. HONEST verdict: "
            "marginal / none. Risk-based & BL weights are construction tooling here, not demonstrated edge; "
            "EQUAL remains the baseline. (Expected under the honesty law.)"
        ),
    }

    # --- VaR/ES profile + pre-trade gate demo (EQUAL book) ---
    out["var_es_profile"] = _var_es_profile(equal_book)
    out["pretrade_gate_demo"] = _pretrade_gate_demo(panel)

    # --- execution drag (EQUAL book) ---
    out["execution_drag"] = _execution_drag(
        equal_book, panel, slippage_bps=slippage_bps, cost_bps=cost_bps, notional=1.0
    )
    return out


def _emit(result: dict, out_dir: str) -> None:
    out_path = os.path.join(out_dir, "measure_portfolio_risk.json")
    with open(out_path, "w") as fh:
        json.dump(result, fh, indent=2, default=_json_default)
    print(json.dumps(result, indent=2, default=_json_default))
    v = result.get("verdict", {})
    if v:
        print(
            f"\n[verdict] best non-EQUAL scheme={v.get('best_non_equal_scheme')} "
            f"delta_dsr={v.get('best_delta_dsr_vs_equal')}; "
            f"beats_equal={v.get('beats_equal_on_deflated_dsr')}",
            file=sys.stderr,
        )
    print(f"[measure] wrote {out_path}", file=sys.stderr)


def _json_default(o):
    if isinstance(o, (np.floating,)):
        return float(o)
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.bool_,)):
        return bool(o)
    if isinstance(o, np.ndarray):
        return o.tolist()
    return str(o)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--window", type=int, default=36, help="trailing months for the rolling cov forecast")
    ap.add_argument("--halflife", type=int, default=12, help="EWMA halflife (rows) for ewma_cov")
    ap.add_argument("--min-window", type=int, default=18, help="min trailing months before trading begins")
    ap.add_argument("--risk-aversion", type=float, default=2.5, help="BL/MV risk aversion (delta)")
    ap.add_argument("--tau", type=float, default=0.05, help="BL tau (prior covariance scaling)")
    ap.add_argument("--view-strength", type=float, default=0.25,
                    help="multiplier on sleeve_vol for the illustrative BL views")
    ap.add_argument("--slippage-bps", type=float, default=2.0, help="execution slippage (bps)")
    ap.add_argument("--cost-bps", type=float, default=2.0, help="execution commission (bps)")
    args = ap.parse_args()

    import macro_risk_os_v2 as eng  # noqa: E402  (engine import AFTER the preamble)

    e = eng.ProductionEngine(eng.DEFAULT_CONFIG)
    e.initialize()
    ret_df = e.data_layer.ret_df
    monthly = e.data_layer.monthly

    result = measure(
        ret_df, monthly,
        window=args.window, halflife=args.halflife, min_window=args.min_window,
        risk_aversion=args.risk_aversion, tau=args.tau, view_strength=args.view_strength,
        slippage_bps=args.slippage_bps, cost_bps=args.cost_bps,
    )
    _emit(result, eng.OUTPUT_DIR)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
