from pathlib import Path

import pytest

from constellation_control.adapters.legacy_glonass_source import (
    additional_reference_pairs,
    load_legacy_glonass_source,
    parse_legacy_glonass_source,
)


SOURCE = Path("data/legacy/glonass/AS_GLO_24plus6.txt")


def test_restored_legacy_glonass_source_has_exact_24plus6_inventory() -> None:
    rows = load_legacy_glonass_source(SOURCE)
    assert len(rows) == 30
    assert [row.satellite_number for row in rows] == list(range(1, 31))
    assert {row.t_ob_s for row in rows} == {40544.0}
    assert {row.inclination_deg for row in rows} == {64.8}
    assert {row.eccentricity for row in rows} == {0.0}


def test_additional_pair_lineage_is_explicit() -> None:
    assert additional_reference_pairs() == {
        25: (1, 2),
        26: (5, 6),
        27: (10, 11),
        28: (14, 15),
        29: (19, 20),
        30: (23, 24),
    }


def test_known_source_rows_are_preserved() -> None:
    rows = {row.satellite_number: row for row in load_legacy_glonass_source(SOURCE)}
    assert rows[1].t_om_s == 3600.0
    assert rows[1].l_om_deg == 180.0
    assert rows[25].t_om_s == 6134.0
    assert rows[25].l_om_deg == 169.415
    assert rows[30].t_om_s == 33163.0
    assert rows[30].l_om_deg == -63.52


def test_parser_fails_closed_on_incomplete_inventory() -> None:
    with pytest.raises(ValueError, match="1..30"):
        parse_legacy_glonass_source("01 01 01 20 3600 40544 0 64.8 180 0 0 1 0\n")
