"""Append-only, checksummed, idempotent persistence for the paper loop (Phase 7).

This mirrors the bitemporal store's discipline: every fact is an immutable JSONL line, never edited.
Reconciliation does NOT mutate a Decision — it appends a separate Realization. Re-running a tick for
an already-recorded month is a no-op (idempotent on the ``(month, strategy_hash)`` key), never an
overwrite. A revised input for an already-decided month raises ``DataRevisionError`` rather than
silently repainting the recorded position.

Structural guards (from the adversarial governance audit):
- ``_append`` is the SOLE writer; mode ``"a"`` only, flush + fsync; no truncation anywhere.
- Every line carries ``seq`` and ``record_sha`` IN the payload; ``seq`` is never derived from line
  position, so interior corruption cannot renumber valid records.
- Reads validate every line's checksum; a corrupt line (anywhere) is quarantined to a ``.corrupt``
  sidecar with a loud warning — never silently dropped.
- ``(month, strategy_hash)`` uniqueness is asserted on read (``LedgerIntegrityError``) — there is no
  "last-wins" repaint-by-read.
- Single-use holdout and the deflation basis are DURABLE ledger facts, not in-memory flags, so they
  survive restarts (the in-memory ``HoldoutToken``/``GovernanceLedger`` reset on every process).
"""

from __future__ import annotations

import os
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Optional

import pandas as pd

from arc.autonomy.spec import canonical_json

SCHEMA_VERSION = 1


# ---------------------------------------------------------------------------- exceptions
class LedgerError(RuntimeError):
    """Base for all ledger integrity failures."""


class RepaintError(LedgerError):
    """An attempt to overwrite/edit an existing immutable record."""


class LedgerIntegrityError(LedgerError):
    """Duplicate ``(month, strategy_hash)`` keys, or a checksum/structure violation on read."""


class DataRevisionError(LedgerError):
    """A new tick for an already-decided ``(month, hash)`` carries a different input digest."""


class HoldoutConsumedError(LedgerError):
    """The single-use holdout for this strategy hash was already consumed (durable, ledger-anchored)."""


class MissingDeflationBasisError(LedgerError):
    """A promotion verdict was attempted with no persisted, pre-committed deflation basis."""


class UnbookedTrialError(LedgerError):
    """A tick was attempted for a strategy hash with no booked governance trial."""


class LookAheadError(LedgerError):
    """A decision would use a return from the very month it is supposed to earn."""


class HoldoutNotReadyError(LedgerError):
    """A verdict was attempted before the pre-committed forward sample size was reached (or it
    overshot it) — refusing to consume the holdout to avoid optional-stopping bias."""


# ---------------------------------------------------------------------------- helpers
def _iso(ts: Any) -> str:
    return pd.Timestamp(ts).strftime("%Y-%m-%d")


def record_sha(payload: dict[str, Any]) -> str:
    """SHA-256 over the canonical payload MINUS its own ``record_sha`` field. Per-line integrity."""
    import hashlib

    body = {k: v for k, v in payload.items() if k != "record_sha"}
    return hashlib.sha256(canonical_json(body).encode("ascii")).hexdigest()


# ---------------------------------------------------------------------------- records
@dataclass(frozen=True)
class Decision:
    """The position formed at the end of the latest known return month, keyed to the month it EARNS.

    ``data_max_knowledge_time`` = the latest return month used (knowledge boundary). ``frozen_position``
    is the unbreakered strategy position (the ONLY thing the verdict ever scores); ``live_position`` is
    what is actually traded (may be 0 if the breaker has halted). ``input_digest`` lets a re-tick detect
    a data revision without ever recomputing the (non-idempotent, expanding-z) position."""

    month: str            # ISO month-end the decision earns (= next month after data_max_knowledge_time)
    strategy_hash: str
    frozen_position: float
    live_position: float
    signal: float         # trailing-lookback momentum value
    signal_z: float       # expanding z-score (pre-clip)
    data_max_knowledge_time: str
    input_digest: str
    run_id: str
    created_at: str


@dataclass(frozen=True)
class Realization:
    """Realized outcome for a decided month, in one stream. Separate record — never edits a Decision."""

    month: str
    strategy_hash: str
    stream: str           # "frozen" (scored) | "live" (operated)
    held_position: float
    prev_held: float
    realized_return: float
    sleeve_return: float
    realized_knowledge_time: str
    return_vintage_seq: int
    reconciled_at: str
    run_id: str


@dataclass(frozen=True)
class RunManifest:
    """Provenance per invocation. ``appended`` distinguishes real activity from idempotent no-ops."""

    run_id: str
    action: str           # "tick" | "reconcile" | "loop" | "verdict" | "book"
    asof: str
    strategy_hash: str
    code_version: str
    appended: list         # list of [file, seq] actually written this run
    created_at: str


@dataclass(frozen=True)
class DeflationBasis:
    """The pre-committed, immutable deflation contract for a strategy's forward holdout.

    Frozen by a human at booking time, BEFORE forward data accrues. The verdict reproduces the gate's
    deflation exactly by passing ``(n_trials, sr_std)`` to ``gate.sharpe_stats`` — and refuses to
    score until exactly ``eval_at_n`` months have accrued (no optional stopping). ``dsr_min`` is the
    promotion bar, committed in advance so it cannot be chosen after seeing the result."""

    strategy_hash: str
    n_trials: int
    sr_std: Optional[float]   # None => Lo-2002 auto SE (the same default sleeve_stats used in-sample)
    eval_at_n: int
    dsr_min: float
    forward_start: Optional[str]  # ISO month-end research cutoff; ONLY months after it count as holdout
    issued_by: str
    created_at: str


@dataclass(frozen=True)
class TrialBooking:
    """A persisted mirror of a GovernanceLedger trial — so ``n_trials`` survives restarts."""

    strategy_hash: str
    label: str
    issued_by: str
    created_at: str


@dataclass(frozen=True)
class HoldoutConsumedRecord:
    """Durable single-use lock. Written + fsync'd BEFORE any score is computed (fail-closed)."""

    strategy_hash: str
    token_id: str
    eval_at_n: int
    consumed_at: str
    run_id: str


@dataclass(frozen=True)
class VerdictRecord:
    """The rendered verdict, persisted so a second call is a deterministic READ, never a recompute."""

    strategy_hash: str
    passed: bool
    reason: str
    dsr: float
    sr_annual: float
    n: int
    dsr_min: float
    n_trials: int
    sr_std: float
    rendered_at: str
    run_id: str


# ---------------------------------------------------------------------------- store
class PaperLedger:
    """Append-only JSONL store. One file per record family; ``_append`` is the only writer."""

    DECISIONS = "decisions.jsonl"
    REALIZATIONS = "realizations.jsonl"
    MANIFESTS = "manifests.jsonl"
    GOVERNANCE = "governance.jsonl"  # bookings + bases + consumed + verdicts

    def __init__(self, state_dir: str | Path) -> None:
        self.state_dir = Path(state_dir)
        self.state_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, name: str) -> Path:
        return self.state_dir / name

    # ---- low-level I/O (sole writer + validating reader) -------------------
    def _append(self, name: str, payload: dict[str, Any]) -> int:
        """Stamp ``seq`` (max existing + 1) and ``record_sha`` into the payload, then append one line.
        flush + fsync for durability. Returns the assigned seq."""
        path = self._path(name)
        existing = self._load(name)
        seq = max((int(r.get("seq", 0)) for r in existing), default=0) + 1
        out = {**payload, "schema_version": SCHEMA_VERSION, "seq": seq}
        out["record_sha"] = record_sha(out)
        line = canonical_json(out)
        with open(path, "a", encoding="ascii", newline="\n") as f:
            f.write(line + "\n")
            f.flush()
            os.fsync(f.fileno())
        return seq

    def _load(self, name: str) -> list[dict[str, Any]]:
        """Read + checksum-validate every line. Corrupt lines are quarantined to ``<file>.corrupt``
        with a loud warning and excluded — never silently dropped. ``seq`` comes from the payload."""
        import json as _json

        path = self._path(name)
        if not path.exists():
            return []
        good: list[dict[str, Any]] = []
        bad: list[str] = []
        for raw in path.read_text(encoding="ascii").splitlines():
            if not raw.strip():
                continue
            try:
                obj = _json.loads(raw)
                if obj.get("record_sha") != record_sha(obj):
                    raise ValueError("checksum mismatch")
                good.append(obj)
            except Exception:  # noqa: BLE001 — any malformed/corrupt line is quarantined
                bad.append(raw)
        if bad:
            corrupt = path.with_suffix(path.suffix + ".corrupt")
            with open(corrupt, "a", encoding="ascii", newline="\n") as f:
                for raw in bad:
                    f.write(raw + "\n")
            print(f"[ledger] WARNING: {len(bad)} corrupt line(s) in {name} quarantined to "
                  f"{corrupt.name}; excluded from reads.", file=sys.stderr)
        return good

    def _filter(self, name: str, kind: str) -> list[dict[str, Any]]:
        return [r for r in self._load(name) if r.get("kind") == kind]

    # ---- decisions --------------------------------------------------------
    def append_decision(self, d: Decision) -> bool:
        """Idempotent on ``(month, strategy_hash)``. Returns False (no-op) if already present with the
        same input; raises ``DataRevisionError`` if the same key reappears with a different input."""
        rows = self._filter(self.DECISIONS, "decision")
        for r in rows:
            if r["month"] == d.month and r["strategy_hash"] == d.strategy_hash:
                if r["input_digest"] != d.input_digest:
                    raise DataRevisionError(
                        f"decision {d.month}/{d.strategy_hash[:8]} already recorded with a different "
                        f"input_digest ({r['input_digest'][:8]} != {d.input_digest[:8]}); refusing to repaint")
                return False
        self._append(self.DECISIONS, {"kind": "decision", **asdict(d)})
        return True

    def decisions(self) -> dict[str, Decision]:
        """Map month -> Decision for the frozen strategy hash. Duplicate keys are FATAL (no last-wins)."""
        rows = self._filter(self.DECISIONS, "decision")
        out: dict[str, Decision] = {}
        for r in rows:
            key = r["month"]
            if key in out:
                raise LedgerIntegrityError(f"duplicate decision for month {key} — ledger is corrupt")
            out[key] = Decision(**{k: r[k] for k in Decision.__dataclass_fields__})
        return out

    # ---- realizations -----------------------------------------------------
    def append_realization(self, r: Realization) -> bool:
        """Idempotent on ``(month, strategy_hash, stream)``."""
        rows = self._filter(self.REALIZATIONS, "realization")
        for ex in rows:
            if ex["month"] == r.month and ex["strategy_hash"] == r.strategy_hash and ex["stream"] == r.stream:
                return False
        self._append(self.REALIZATIONS, {"kind": "realization", **asdict(r)})
        return True

    def realizations(self, stream: str) -> dict[str, Realization]:
        rows = [r for r in self._filter(self.REALIZATIONS, "realization") if r["stream"] == stream]
        out: dict[str, Realization] = {}
        for r in rows:
            key = r["month"]
            if key in out:
                raise LedgerIntegrityError(f"duplicate {stream} realization for month {key}")
            out[key] = Realization(**{k: r[k] for k in Realization.__dataclass_fields__})
        return out

    def _stream_frame(self, stream: str) -> pd.DataFrame:
        decs = self.decisions()
        reals = self.realizations(stream)
        months = sorted(set(decs) & set(reals))
        if not months:
            return pd.DataFrame(columns=["month", "held_position", "realized_return", "sleeve_return"])
        df = pd.DataFrame([{
            "month": pd.Timestamp(m),
            "held_position": reals[m].held_position,
            "realized_return": reals[m].realized_return,
            "sleeve_return": reals[m].sleeve_return,
            "signal_z": decs[m].signal_z,
        } for m in months]).set_index("month").sort_index()
        return df

    def frozen_frame(self) -> pd.DataFrame:
        """The accumulated out-of-time stream the verdict scores. NEVER touched by the breaker."""
        return self._stream_frame("frozen")

    def live_frame(self) -> pd.DataFrame:
        """The actually-operated stream (breaker may have zeroed positions). Operational only."""
        return self._stream_frame("live")

    # ---- manifests --------------------------------------------------------
    def append_manifest(self, m: RunManifest) -> int:
        return self._append(self.MANIFESTS, {"kind": "manifest", **asdict(m)})

    # ---- governance: trial bookings, deflation bases, consumption, verdicts
    def append_booking(self, b: TrialBooking) -> bool:
        if b.strategy_hash in self.booked_hashes():
            return False
        self._append(self.GOVERNANCE, {"kind": "booking", **asdict(b)})
        return True

    def booked_hashes(self) -> set[str]:
        return {r["strategy_hash"] for r in self._filter(self.GOVERNANCE, "booking")}

    def append_basis(self, b: DeflationBasis) -> bool:
        if self.basis_for(b.strategy_hash) is not None:
            raise RepaintError(f"deflation basis for {b.strategy_hash[:8]} already exists; immutable")
        self._append(self.GOVERNANCE, {"kind": "basis", **asdict(b)})
        return True

    def basis_for(self, h: str) -> Optional[DeflationBasis]:
        rows = [r for r in self._filter(self.GOVERNANCE, "basis") if r["strategy_hash"] == h]
        if not rows:
            return None
        if len(rows) > 1:
            raise LedgerIntegrityError(f"multiple deflation bases for {h[:8]}")
        r = rows[0]
        return DeflationBasis(**{k: r[k] for k in DeflationBasis.__dataclass_fields__})

    def append_consumed(self, c: HoldoutConsumedRecord) -> int:
        return self._append(self.GOVERNANCE, {"kind": "consumed", **asdict(c)})

    def consumed_hashes(self) -> set[str]:
        return {r["strategy_hash"] for r in self._filter(self.GOVERNANCE, "consumed")}

    def append_verdict(self, v: VerdictRecord) -> int:
        return self._append(self.GOVERNANCE, {"kind": "verdict", **asdict(v)})

    def verdict_for(self, h: str) -> Optional[VerdictRecord]:
        rows = [r for r in self._filter(self.GOVERNANCE, "verdict") if r["strategy_hash"] == h]
        if not rows:
            return None
        if len(rows) > 1:  # duplicate-fatal, like decisions()/realizations() — no last-wins repaint
            raise LedgerIntegrityError(f"multiple verdicts for {h[:8]} — ledger is corrupt")
        r = rows[0]
        return VerdictRecord(**{k: r[k] for k in VerdictRecord.__dataclass_fields__})


__all__ = [
    "PaperLedger", "Decision", "Realization", "RunManifest", "DeflationBasis", "TrialBooking",
    "HoldoutConsumedRecord", "VerdictRecord", "record_sha", "SCHEMA_VERSION",
    "LedgerError", "RepaintError", "LedgerIntegrityError", "DataRevisionError",
    "HoldoutConsumedError", "MissingDeflationBasisError", "UnbookedTrialError",
    "LookAheadError", "HoldoutNotReadyError",
]
