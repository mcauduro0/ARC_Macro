"""Tests for the typed artifacts (arc.contracts)."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from arc.contracts import RunManifest, SeriesContract


def _ipca() -> SeriesContract:
    return SeriesContract(
        series_id="IPCA_YOY",
        source="BCB_SGS",
        frequency="M",
        unit="percent",
        publication_lag_days=10,  # IPCA released ~10th of month for prior month
        valid_min=-5.0,
        valid_max=50.0,
        license="BCB open data",
    )


def test_series_contract_validate_value():
    c = _ipca()
    assert c.validate_value(4.5) == []
    assert c.validate_value(-9.0)  # below min -> error(s)
    assert c.validate_value(99.0)  # above max -> error(s)
    assert c.validate_value(float("nan"))  # NaN -> error


def test_series_contract_rejects_bad_frequency():
    with pytest.raises(ValidationError):
        SeriesContract(series_id="X", source="FRED", frequency="yearly", unit="pct",
                       publication_lag_days=0)


def test_series_contract_rejects_negative_lag():
    with pytest.raises(ValidationError):
        SeriesContract(series_id="X", source="FRED", frequency="M", unit="pct",
                       publication_lag_days=-1)


def test_run_manifest_forbids_unknown_fields():
    with pytest.raises(ValidationError):
        RunManifest(
            run_id="r", created_at=datetime.now(timezone.utc), seed=1,
            python_version="3.11.9", platform="x", surprise="nope",
        )
