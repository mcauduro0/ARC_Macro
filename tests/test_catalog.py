"""Series catalog tests."""

from __future__ import annotations

import pytest

from arc.data.catalog import all_contracts, by_source, get_contract


def test_get_contract_has_publication_lag():
    c = get_contract("IPCA_MOM")
    assert c.publication_lag_days == 10
    assert c.source == "BCB_SGS" and c.source_code == "433"


def test_every_catalog_series_has_code_and_nonneg_lag():
    for c in all_contracts():
        assert c.publication_lag_days >= 0
        assert c.source_code, f"{c.series_id} missing source_code"


def test_by_source_groups():
    assert {c.series_id for c in by_source("FRED")} >= {"UST10Y", "UST2Y", "US_CPI"}
    assert all(c.source == "BCB_SGS" for c in by_source("BCB_SGS"))


def test_unknown_series_raises():
    with pytest.raises(KeyError):
        get_contract("DOES_NOT_EXIST")
