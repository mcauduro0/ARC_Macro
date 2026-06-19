"""Deterministic seeding + run-manifest capture (Phase 0).

Fixes audit findings repro-1/-2/-3 and version-1: no global seed, no run_id/git SHA,
version drift. Call ``init_reproducibility()`` at every Python entrypoint; use
``get_rng()`` instead of the global ``np.random`` state; stamp ``capture_manifest()``
onto every output (ARCHITECTURE_SOTA.md §4.7).
"""

from __future__ import annotations

import hashlib
import importlib.metadata as _md
import json
import os
import platform
import random
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

import numpy as np

from arc.contracts import RunManifest

DEFAULT_SEED = 20260619

# Packages whose versions materially affect numerical results — recorded in every manifest.
TRACKED_PACKAGES = (
    "numpy", "pandas", "scipy", "scikit-learn", "xgboost",
    "hmmlearn", "statsmodels", "arch", "shap", "pydantic",
)

_GLOBAL_SEED: Optional[int] = None
_RNG: Optional[np.random.Generator] = None


def init_reproducibility(seed: int = DEFAULT_SEED, *, single_thread_blas: bool = False) -> int:
    """Seed all RNGs and (optionally) pin BLAS threads for determinism.

    Note: PYTHONHASHSEED only takes effect for *child* processes started after this call;
    the current interpreter's hash randomization was fixed at startup. Numerical
    determinism (numpy/random/sklearn) is fully covered here.
    """
    global _GLOBAL_SEED, _RNG
    os.environ["PYTHONHASHSEED"] = str(seed)
    if single_thread_blas:
        for var in (
            "OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS",
            "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS",
        ):
            os.environ.setdefault(var, "1")
    random.seed(seed)
    np.random.seed(seed)  # legacy global state read by sklearn estimators without random_state
    _RNG = np.random.default_rng(seed)
    _GLOBAL_SEED = seed
    return seed


def get_rng() -> np.random.Generator:
    """The process-wide seeded Generator. Prefer this over ``np.random`` calls."""
    if _RNG is None:
        init_reproducibility()
    assert _RNG is not None
    return _RNG


def get_seed() -> Optional[int]:
    return _GLOBAL_SEED


def config_hash(config: Any) -> str:
    """Deterministic sha256 of a config object (order-independent for dicts)."""
    blob = json.dumps(config, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _git_sha() -> Optional[str]:
    try:
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, timeout=5
        )
        if head.returncode != 0:
            return None
        sha = head.stdout.strip()
        dirty = subprocess.run(
            ["git", "status", "--porcelain"], capture_output=True, text=True, timeout=5
        ).stdout.strip()
        return sha + ("-dirty" if dirty else "")
    except Exception:
        return None


def _package_versions(packages=TRACKED_PACKAGES) -> dict[str, Optional[str]]:
    out: dict[str, Optional[str]] = {}
    for p in packages:
        try:
            out[p] = _md.version(p)
        except Exception:
            out[p] = None
    return out


def capture_manifest(
    config: Any | None = None,
    *,
    version: str | None = None,
    extra: dict | None = None,
) -> RunManifest:
    """Build a RunManifest for the current run. Seeds reproducibility if not already done."""
    seed = _GLOBAL_SEED if _GLOBAL_SEED is not None else init_reproducibility()
    return RunManifest(
        run_id=str(uuid.uuid4()),
        created_at=datetime.now(timezone.utc),
        git_sha=_git_sha(),
        seed=seed,
        python_version=sys.version.split()[0],
        platform=platform.platform(),
        package_versions=_package_versions(),
        config_hash=config_hash(config) if config is not None else None,
        version=version,
        extra=extra or {},
    )
