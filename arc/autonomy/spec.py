"""The frozen strategy contract and the binding key that threads the whole autonomy spine.

A forward holdout is only honest if the strategy it scores is *frozen* before the forward data
exists. ``FROZEN_SPEC`` is that immutable contract; ``strategy_hash`` is the key stamped on every
ledger record, the GovernanceLedger trial, the DeflationBasis, and the HoldoutToken. Changing any
spec field changes the hash — which forces a NEW booked trial (raising the deflation bar) and starts
a NEW out-of-time window. Retuning is therefore structurally self-penalizing, not free.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

# The first gated edge (Phase 4.2/4.3): 3-month time-series momentum on the 1Y DI receiver.
# Every field here is part of the binding contract; touching one is a new hypothesis (new hash).
FROZEN_SPEC: dict[str, Any] = {
    "instrument": "front",
    "kind": "momentum",
    "lookback": 3,
    "z_window": 12,
    "clip_z": 2.0,
    "cost_bps": 2.0,
}

# The second gated edge (Phase 4.4): the point-in-time activity nowcast on the 10Y DI receiver, driven
# by the NEGATED 3-month change of the activity factor (decelerating activity => policy cuts => receiver
# gains). Chosen over the belly/level expression on every axis (best deflated DSR 0.549, lowest maxDD,
# most orthogonal to price momentum, cleanest predictive lag structure). Verified distinct from front/mom3.
NOWCAST_SPEC: dict[str, Any] = {
    "instrument": "long",
    "kind": "nowcast",
    "signal": "neg_nowcast_mom3",
    "inputs": ["ibc_br", "ewz", "iron_ore", "tot", "bcom"],
    "z_window": 12,
    "clip_z": 2.0,
    "cost_bps": 2.0,
}

# The third gated candidate (Phase 4.5 re-test): fiscal primary-balance momentum on the sovereign-spread
# receiver (hard). Signal = 6-month change in the primary balance (fiscal consolidation momentum); an
# improving primary balance tightens the sovereign spread, so the receiver gains (oriented POSITIVE). The
# v1 verify left it "borderline" only because the global-risk control was inconclusive (US-HY history too
# short, n=35<40); the v2 re-test with a LONG control panel (VIX+NFCI+US-term+Δcds, n=172) shows it is NOT
# risk-on/off (IC 0.116 -> 0.115 after neutralizing the panel), survives carry, is orthogonal to both other
# edges, predictive, and clears the gate's bar (H2 +0.198). RESIDUAL CAVEATS (why this is a CANDIDATE under
# forward paper, not a claimed edge): the edge lives in short-to-mid windows — diff(9)/diff(12) collapse —
# and a recency re-examination (scripts/reexamine_fiscal_hard.py, 2026-06 baseline) is an ORANGE FLAG: the
# last-36m carry-neutral IC is NEGATIVE (-0.170), pre-committed recency_ok=False. Booking is a forward-paper
# commitment (immutable basis), NOT a live allocation: a recent edge this weak will simply fail the one-shot
# forward verdict (that is the system working). Watch it. See docs/PHASE4_5_PB_RETEST_POSITIONING_2026-06.md
# + docs/PHASE7_3_AUTONOMOUS_ACCRUAL_2026-06.md (recency watch).
HARD_PB_SPEC: dict[str, Any] = {
    "instrument": "hard",
    "kind": "fiscal_momentum",
    "signal": "pb_mom6",
    "inputs": ["primary_balance"],
    "lookback": 6,
    "z_window": 12,
    "clip_z": 2.0,
    "cost_bps": 2.0,
}

# Registry of booked strategies the multi-strategy paper loop can host (each accrues its own holdout).
SPECS: dict[str, dict[str, Any]] = {
    "momentum_front": FROZEN_SPEC,
    "nowcast_long": NOWCAST_SPEC,
    "fiscal_hard": HARD_PB_SPEC,
}


def canonical_json(obj: dict[str, Any]) -> str:
    """Deterministic JSON: sorted keys, no whitespace. Used for BOTH hashing and per-line
    checksums so the same dict always serializes to the same bytes regardless of insertion order."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def strategy_hash(spec: dict[str, Any]) -> str:
    """16-hex-char SHA-256 of the canonicalized spec — the holdout/trial binding key."""
    return hashlib.sha256(canonical_json(spec).encode("ascii")).hexdigest()[:16]


FROZEN_HASH = strategy_hash(FROZEN_SPEC)


def _member_hashes() -> list[str]:
    """The three booked single-sleeve hashes, sorted — the immutable membership of the pool. Built from
    the live specs so that editing ANY member spec forks the pool hash too (a re-tuned member can never
    silently ride inside an already-booked pool)."""
    return sorted(strategy_hash(s) for s in (FROZEN_SPEC, NOWCAST_SPEC, HARD_PB_SPEC))


# The fourth booked candidate (Phase 7.4 / track-a): an EQUAL-WEIGHT POOL of the three single sleeves.
# Rationale (scripts/measure_statistical_power.py, 2026-06): the three sleeves are nearly independent
# (avg |corr| 0.11, K_eff 2.92 of 3), so an equal-weight pooled forward holdout carries the same t-content
# in ~24/K_eff calendar months -- its pre-committed eval_at_n is max(12, ceil(24/K_eff)) = 12, a verdict
# ~1y SOONER than a single sleeve. This is NOT a claim of edge: pooling pays off ONLY if several sleeves
# carry real, similarly-signed edge (if one is noise, pooling dilutes). The forward holdout is the sole
# judge; equal weights are FIXED (no in-sample tuning => no extra weight-deflation). The pool is bound to
# its members' hashes, so it forks if any member spec changes. cost_bps=0: the pooled stream inherits each
# member sleeve's own transaction costs; pooling adds no separately-modelled cost here.
POOL_SPEC: dict[str, Any] = {
    "kind": "pool",
    "members": _member_hashes(),
    "weights": "equal",
    "cost_bps": 0.0,
}
POOL_HASH = strategy_hash(POOL_SPEC)
