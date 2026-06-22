"""PRE-REGISTRATION of forward sizing experiments — confirm ONLY on forward paper (Phase 7.x).

WHAT THIS IS (read first — it is NOT a result):
    ``measure_intelligence`` found a TENTATIVE *in-sample* gain: the ``nowcast_long`` sleeve, when its
    recorded position is rescaled by a conformal-width CONFIDENCE multiplier ("confidence_vol" sizing),
    beat FLAT sizing by +0.060 deflated DSR. Per the project's honesty law ("não invente resultados") an
    in-sample gain is NOT evidence of edge — it is a HYPOTHESIS. This module is the timestamped
    pre-registration of that hypothesis: a DETERMINISTIC sizing rule plus a PRE-COMMITTED PASS/FAIL
    criterion, committed to git NOW (git commit == the prereg timestamp), BEFORE any out-of-time month
    exists. Nothing here is judged in-sample, and nothing here books a new trial or ticks the autonomy
    spine — the criterion is evaluated later, purely by reading the frozen forward stream.

WHY POST-HOC RECOMPUTATION IS LEGITIMATE (no new booked trial, no tick change):
    The frozen ledger already records, per forward month, the base ``held_position`` and the
    ``realized_return`` that the booked sleeve actually earned. Flat-vs-sized can therefore be recomputed
    AFTER THE FACT from those recorded decisions times a CAUSAL confidence multiplier. We never re-trade,
    never append a Decision/Realization, never touch paper.py / ledger.py / spec.py / loop.py / monitor.py.
    The booked single-use holdout and its verdict are untouched; this is a *parallel, read-only* recompute
    on the same accrued months.

THE DETERMINISTIC SIZING RULE ("confidence_vol"), causal at every t (index <= t only):
    1. point-prediction of the sleeve's realized return, using ONLY strictly-past realized returns:
           pred[t] = expanding_mean(realized_return).shift(1)[t]      (no row sees its own outcome)
    2. split-conformal credible band around that prediction, calibrated on strictly-past residuals:
           width[t] = conformal_intervals(pred, realized, alpha=<alpha>, min_train=...).width[t]
    3. width -> confidence, benchmarked against the EXPANDING MEDIAN of past widths (index <= t):
           confidence[t] = interval_confidence(width, min_periods=...)[t]   in (0, 1]
    4. scale the RECORDED base position by a causal, bounded confidence factor in [lo, hi]:
           mult[t] = confidence_scaled_position(held_position, confidence, lo=..., hi=...)[t] / held[t]
       (equivalently the sized position is confidence_scaled_position(held_position, confidence)).
    5. sized sleeve return reuses the recorded per-month return relationship:
           sized_return[t] = (held_position[t] * mult[t]) * realized_return[t]
       i.e. the sized POSITION earns the SAME recorded realized_return the flat position earned. This is
       intentionally consistent with how the ledger forms sleeve returns in arc/research/sleeve.py and
       arc/autonomy/paper.py (sleeve = held * realized - turnover_cost): we rescale the gross
       position-times-return term and leave the (second-order, already-paid) turnover cost as recorded.

PRE-COMMITTED CRITERION (committed now, evaluated later, NEVER chosen after seeing the result):
    sized forward DSR (deflated) >= flat forward DSR + 0.05  AND  sized forward Sharpe > flat forward Sharpe.
    Both legs use the SAME deflation basis (n_trials, sr_std) the booked sleeve already committed — the
    comparison is sized-vs-flat on the identical frozen months, so no second multiple-testing budget is
    introduced.

This module is PURE (pandas/numpy + arc.intelligence + arc.research only). It imports NO engine and does
NOT modify the autonomy spine. It is a registry + one pure recompute function + a tiny stats helper.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from arc.intelligence.sizing import confidence_scaled_position
from arc.intelligence.uncertainty import conformal_intervals, interval_confidence

# --------------------------------------------------------------------------------------------------
# Pre-registration registry. Each entry is a DETERMINISTIC, frozen description of a forward experiment.
# Adding/changing an entry is a new pre-registration (commit it before forward data accrues).
# --------------------------------------------------------------------------------------------------
FORWARD_EXPERIMENTS: list[dict[str, Any]] = [
    {
        "name": "nowcast_confvol",
        "base_strategy": "nowcast_long",           # the booked spec name in arc.autonomy.spec.SPECS
        "state_key": "nowcast",                    # ledger dir: state/paper/<state_key>
        "sizing": "confidence_vol",                # the deterministic rule implemented in apply_sizing
        "alpha": 0.10,                             # conformal miscoverage (90% credible band)
        "criterion": (
            "sized forward DSR (deflated) >= flat forward DSR + 0.05 "
            "AND sized forward Sharpe > flat forward Sharpe"
        ),
        "in_sample_motivation": "measure_intelligence dDSR +0.060",
        "prereg_note": "confirm ONLY on forward paper",
    },
]

# Pre-committed numeric margins / sizing bounds — frozen here so they cannot be chosen after the result.
DSR_MARGIN: float = 0.05          # sized DSR must beat flat DSR by at least this
CONF_LO: float = 0.25             # confidence-scale lower bound (shrink, never below this)
CONF_HI: float = 1.0              # confidence-scale upper bound (never lever up beyond the base bet)
CONFORMAL_MIN_TRAIN: int = 12     # strictly-past residuals required before a band exists (forward-stream scale)
CONFIDENCE_MIN_PERIODS: int = 12  # past widths required before a confidence is produced

_SIZINGS = {"confidence_vol"}


def _causal_point_pred(realized: pd.Series) -> pd.Series:
    """Strictly-causal point prediction of the realized return: the expanding mean of STRICTLY-PAST
    realized returns. ``pred[t] = mean(realized[s] : s < t)`` via ``expanding().mean().shift(1)`` so the
    row being predicted never sees its own outcome (no leakage). NaN until at least one past value
    exists. This is a deliberately weak, assumption-light predictor — the experiment is about the
    conformal *width/confidence* it induces, not about a return forecast."""
    r = pd.Series(realized, dtype="float64")
    return r.expanding(min_periods=1).mean().shift(1)


def apply_sizing(frozen_frame: pd.DataFrame, sizing: str, *, alpha: float) -> pd.Series:
    """Recompute the SIZED sleeve-return stream from a frozen ledger frame — CAUSALLY and deterministically.

    PRE-REGISTRATION, NOT A RESULT. Given a ``PaperLedger.frozen_frame()`` (columns include
    ``held_position`` and ``realized_return``, indexed by forward month), recompute the confidence
    multiplier from the frame's OWN realized-return history (no external data, strictly point-in-time)
    and return the sized sleeve return per month:

        sized_return[t] = (held_position[t] * mult[t]) * realized_return[t]

    where ``mult[t]`` is the causal confidence multiplier described in the module docstring. With
    ``sizing == "confidence_vol"``:

        pred        = expanding_mean(realized_return).shift(1)              # causal point pred
        width       = conformal_intervals(pred, realized, alpha=alpha).width  # strictly-past calibration
        confidence  = interval_confidence(width)                            # vs expanding-median width
        sized_pos   = confidence_scaled_position(held_position, confidence, lo=CONF_LO, hi=CONF_HI)
        mult        = sized_pos / held_position                             # in [CONF_LO, CONF_HI]

    Causality: every step uses index <= t only (conformal calibrates on residuals strictly < t;
    interval_confidence and confidence_scaled_position use expanding statistics). Appending later forward
    months never changes an earlier ``sized_return`` — the as-of invariance the tests assert.

    Robustness: an empty frame returns an empty Series (the honest "not ready" path). Months whose
    confidence is still warming up (NaN multiplier) FALL BACK to the recorded flat sleeve return, so the
    sized stream is defined on exactly the months the flat stream is — a fair, like-for-like comparison.
    The flat baseline itself is the recorded ``sleeve_return`` (see ``flat_returns``).

    Parameters
    ----------
    frozen_frame : pd.DataFrame
        Output of ``PaperLedger.frozen_frame()``: needs ``held_position`` and ``realized_return`` columns
        (``sleeve_return`` optional, used for the warm-up fallback). May be empty.
    sizing : str
        Must be ``"confidence_vol"`` (the only pre-registered rule). Other values raise ``ValueError``.
    alpha : float
        Conformal miscoverage level (e.g. 0.10 for ~90% bands). Passed through to ``conformal_intervals``.

    Returns
    -------
    pd.Series
        SIZED sleeve returns indexed by month (same index as the input rows that have a realized return).
        Empty when the frame is empty.
    """
    if sizing not in _SIZINGS:
        raise ValueError(f"unknown sizing {sizing!r}; pre-registered sizings are {sorted(_SIZINGS)}")

    if frozen_frame is None or len(frozen_frame) == 0:
        return pd.Series(dtype="float64", name="sized_return")

    df = frozen_frame.sort_index()
    held = pd.Series(df["held_position"], dtype="float64")
    realized = pd.Series(df["realized_return"], dtype="float64")

    # Flat baseline per month = recorded sleeve return if present, else held*realized (no recorded cost).
    if "sleeve_return" in df.columns:
        flat = pd.Series(df["sleeve_return"], dtype="float64")
    else:
        flat = held * realized

    # 1) causal point prediction of realized returns (strictly-past expanding mean).
    pred = _causal_point_pred(realized)
    # 2) split-conformal width, calibrated on strictly-past residuals only.
    band = conformal_intervals(pred, realized, alpha=alpha, min_train=CONFORMAL_MIN_TRAIN)
    width = band["width"]
    # 3) width -> causal confidence (vs expanding-median past width).
    confidence = interval_confidence(width, min_periods=CONFIDENCE_MIN_PERIODS)
    # 4) scale the RECORDED base position by the causal, bounded confidence factor.
    sized_pos = confidence_scaled_position(held, confidence, lo=CONF_LO, hi=CONF_HI)

    # multiplier in [CONF_LO, CONF_HI] where defined; NaN during warm-up. Where held==0 the position is
    # 0 either way, so the multiplier is irrelevant -> treat as 1.0 (no change to a zero bet).
    with np.errstate(divide="ignore", invalid="ignore"):
        mult = sized_pos / held.where(held != 0.0)
    mult = mult.where(held != 0.0, other=1.0)

    # 5) sized return reuses the recorded per-month return relationship; warm-up months fall back to flat.
    sized = (held * mult) * realized
    sized = sized.where(mult.notna(), other=flat)
    # Only keep months with a defined realized return (mirrors the flat stream's support).
    sized = sized.where(realized.notna())
    return sized.rename("sized_return")


def flat_returns(frozen_frame: pd.DataFrame) -> pd.Series:
    """The FLAT (recorded, unsized) sleeve-return baseline — the comparison arm. Uses the recorded
    ``sleeve_return`` when present (net of the cost the loop actually paid), else ``held*realized``.
    Empty frame -> empty Series. This is what ``apply_sizing(..., 'confidence_vol')`` is judged against."""
    if frozen_frame is None or len(frozen_frame) == 0:
        return pd.Series(dtype="float64", name="flat_return")
    df = frozen_frame.sort_index()
    if "sleeve_return" in df.columns:
        out = pd.Series(df["sleeve_return"], dtype="float64")
    else:
        out = pd.Series(df["held_position"], dtype="float64") * pd.Series(df["realized_return"], dtype="float64")
    return out.rename("flat_return")


def criterion_met(flat_stats: dict, sized_stats: dict, *, dsr_margin: float = DSR_MARGIN) -> tuple[bool, str]:
    """Evaluate the PRE-COMMITTED criterion from two ``sleeve_stats`` dicts (flat vs sized). Returns
    ``(passed, human_reason)``. NaN-fatal: a degenerate (NaN) DSR/Sharpe on either arm is a FAIL, never a
    silent pass. The criterion (frozen at pre-registration time) is::

        sized DSR >= flat DSR + dsr_margin   AND   sized Sharpe > flat Sharpe
    """
    fd, sd = flat_stats.get("dsr", float("nan")), sized_stats.get("dsr", float("nan"))
    fs, ss = flat_stats.get("sharpe_ann", float("nan")), sized_stats.get("sharpe_ann", float("nan"))
    finite = all(x == x for x in (fd, sd, fs, ss))  # (x == x) is False for NaN
    if not finite:
        return False, "FAIL: degenerate (NaN) DSR/Sharpe on flat or sized arm"
    dsr_ok = sd >= fd + dsr_margin
    sr_ok = ss > fs
    passed = bool(dsr_ok and sr_ok)
    reason = (
        f"{'PASS' if passed else 'FAIL'}: sized DSR {sd:.3f} vs flat {fd:.3f} "
        f"(need >= flat+{dsr_margin}: {'ok' if dsr_ok else 'no'}); "
        f"sized Sharpe {ss:.2f} vs flat {fs:.2f} ({'ok' if sr_ok else 'no'})"
    )
    return passed, reason


def get_experiment(name: str) -> dict[str, Any]:
    """Look up a pre-registered experiment by name (raises ``KeyError`` if absent)."""
    for exp in FORWARD_EXPERIMENTS:
        if exp["name"] == name:
            return exp
    raise KeyError(f"no pre-registered forward experiment named {name!r}")


__all__ = [
    "FORWARD_EXPERIMENTS",
    "apply_sizing",
    "flat_returns",
    "criterion_met",
    "get_experiment",
    "DSR_MARGIN",
    "CONF_LO",
    "CONF_HI",
]
