"""BCB Focus adapter parsing tests (pure)."""

from __future__ import annotations

from arc.data.adapters import BcbFocusAdapter


def test_focus_parse_uses_data_index_and_median():
    raw = {"value": [
        {"Indicador": "IPCA", "Data": "2026-06-15", "Media": 4.1, "Mediana": 4.0},
        {"Indicador": "IPCA", "Data": "2026-06-08", "Media": 4.3, "Mediana": 4.2},
    ]}
    s = BcbFocusAdapter().parse(raw)
    assert s.loc["2026-06-15"] == 4.0  # default stat = Mediana
    assert list(s.index) == sorted(s.index)


def test_focus_media_stat_option():
    raw = {"value": [{"Indicador": "IPCA", "Data": "2026-06-15", "Media": 4.1, "Mediana": 4.0}]}
    assert BcbFocusAdapter(stat="Media").parse(raw).iloc[0] == 4.1


def test_focus_empty():
    assert BcbFocusAdapter().parse({"value": []}).empty
