"""Typed artifacts — the single source-of-truth schemas (Phase 0 minimal set).

Future: this becomes ``arc-contracts`` with JSON Schema codegen to Pydantic v2 + Zod
(see ARCHITECTURE_SOTA.md §2/§4.1). For Phase 0 we land the two artifacts every other
subsystem must stamp/consume: RunManifest (reproducibility join-key) and SeriesContract
(the data-platform contract carrying publication lag, validity, license).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class RunManifest(BaseModel):
    """Stamped on every run/artifact; the join key across MLflow, the governance ledger,
    the event store, and reports (ARCHITECTURE_SOTA.md §6 cross-cutting concern)."""

    model_config = ConfigDict(extra="forbid")

    run_id: str = Field(description="unique per execution (uuid4)")
    created_at: datetime
    git_sha: Optional[str] = Field(default=None, description="HEAD sha, '-dirty' suffix if worktree dirty")
    seed: int
    python_version: str
    platform: str
    package_versions: dict[str, Optional[str]] = Field(default_factory=dict)
    config_hash: Optional[str] = Field(default=None, description="sha256 of the run config")
    version: Optional[str] = Field(default=None, description="engine/model version string")
    extra: dict[str, Any] = Field(default_factory=dict)

    def to_json(self) -> str:
        return self.model_dump_json(indent=2)


Frequency = Literal["D", "B", "W", "M", "Q", "A"]


class SeriesContract(BaseModel):
    """Declarative contract for one data series. Backs the bitemporal store's validation
    and the as_of() publication-lag logic (ARCHITECTURE_SOTA.md §4.1)."""

    model_config = ConfigDict(extra="forbid")

    series_id: str
    source: str = Field(description="e.g. BCB_SGS, BCB_FOCUS, ANBIMA, FRED, FMP, TE, IPEADATA")
    source_code: Optional[str] = Field(default=None, description="provider's native series code, e.g. BCB SGS '432', FRED 'DGS10'")
    frequency: Frequency
    unit: str
    publication_lag_days: int = Field(
        ge=0, description="days from event_time until the value is KNOWABLE (knowledge_time)"
    )
    valid_min: Optional[float] = None
    valid_max: Optional[float] = None
    monotonic: Optional[Literal["inc", "dec"]] = None
    allowed_revision_abs: Optional[float] = Field(
        default=None, description="max plausible |revision| between vintages; larger => quarantine"
    )
    license: Optional[str] = Field(default=None, description="redistribution terms per source")
    description: Optional[str] = None

    def validate_value(self, value: float) -> list[str]:
        """Return a list of contract violations for a single observation (empty == valid)."""
        errs: list[str] = []
        if value is None or (isinstance(value, float) and value != value):  # None / NaN
            errs.append(f"{self.series_id}: value is null/NaN")
            return errs
        if self.valid_min is not None and value < self.valid_min:
            errs.append(f"{self.series_id}: {value} < valid_min {self.valid_min}")
        if self.valid_max is not None and value > self.valid_max:
            errs.append(f"{self.series_id}: {value} > valid_max {self.valid_max}")
        return errs
