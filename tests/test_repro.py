"""Reproducibility foundation tests (audit findings repro-1/-2/-3)."""

from __future__ import annotations

import numpy as np

from arc.repro import (
    DEFAULT_SEED,
    capture_manifest,
    config_hash,
    get_rng,
    init_reproducibility,
)


def test_seed_makes_numpy_global_deterministic():
    init_reproducibility(123)
    a = np.random.rand(5)
    init_reproducibility(123)
    b = np.random.rand(5)
    assert np.array_equal(a, b)


def test_get_rng_is_seeded_and_deterministic():
    init_reproducibility(999)
    a = get_rng().standard_normal(4)
    init_reproducibility(999)
    b = get_rng().standard_normal(4)
    assert np.array_equal(a, b)


def test_config_hash_is_order_independent_and_sensitive():
    h1 = config_hash({"a": 1, "b": 2})
    h2 = config_hash({"b": 2, "a": 1})
    h3 = config_hash({"a": 1, "b": 3})
    assert h1 == h2
    assert h1 != h3
    assert len(h1) == 64  # sha256 hex


def test_capture_manifest_populates_core_fields():
    init_reproducibility(DEFAULT_SEED)
    m = capture_manifest(config={"gamma": 2.0}, version="2.0-phase0")
    assert m.seed == DEFAULT_SEED
    assert m.version == "2.0-phase0"
    assert m.config_hash and len(m.config_hash) == 64
    assert m.python_version.count(".") >= 1
    assert "numpy" in m.package_versions and m.package_versions["numpy"] is not None
    # round-trips through the pydantic contract
    assert '"run_id"' in m.to_json()


def test_run_ids_are_unique():
    ids = {capture_manifest().run_id for _ in range(5)}
    assert len(ids) == 5
