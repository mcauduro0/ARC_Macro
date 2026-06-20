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

# Registry of booked strategies the multi-strategy paper loop can host (each accrues its own holdout).
SPECS: dict[str, dict[str, Any]] = {
    "momentum_front": FROZEN_SPEC,
    "nowcast_long": NOWCAST_SPEC,
}


def canonical_json(obj: dict[str, Any]) -> str:
    """Deterministic JSON: sorted keys, no whitespace. Used for BOTH hashing and per-line
    checksums so the same dict always serializes to the same bytes regardless of insertion order."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def strategy_hash(spec: dict[str, Any]) -> str:
    """16-hex-char SHA-256 of the canonicalized spec — the holdout/trial binding key."""
    return hashlib.sha256(canonical_json(spec).encode("ascii")).hexdigest()[:16]


FROZEN_HASH = strategy_hash(FROZEN_SPEC)
