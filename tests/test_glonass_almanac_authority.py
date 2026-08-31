from __future__ import annotations

import pytest

from constellation_control.adapters.glonass_almanac_authority import parse_glonass_authority_source

AUTHORITY_TEXT = """Slot: 1
Frequency Channel: -7
Health: 0
Reference Date: 2026-01-01
Reference Time(s): 3600
Lambda(rad): 1.0
Delta I(rad): 0.001
Eccentricity: 0.001
Argument of Perigee(rad): 0.5
Delta T(s): 0.0
Delta T Dot: 0.0
GLO to UTC(s): 0.0
GPS to GLO(s): 0.0
GLO Time Offset(s): 0.0
"""


def test_parses_authority_ready_glonass_record_with_explicit_time_semantics() -> None:
    source = parse_glonass_authority_source("glo-authority.txt", AUTHORITY_TEXT)
    assert source.source_format == "glonass-labelled-authority-v1"
    assert len(source.source_sha256) == 64
    assert len(source.records) == 1
    record = source.records[0]
    assert record.slot == 1
    assert record.frequency_channel == -7
    assert record.reference_date.isoformat() == "2026-01-01"
    assert record.reference_time_s == 3600.0
    assert record.delta_t_s == 0.0
    assert record.delta_t_dot == 0.0


def test_missing_delta_t_fails_closed_instead_of_using_absolute_draconian_period() -> None:
    text = AUTHORITY_TEXT.replace("Delta T(s): 0.0\n", "")
    with pytest.raises(ValueError, match="delta_t_s"):
        parse_glonass_authority_source("glo-authority.txt", text)


def test_missing_reference_date_fails_closed() -> None:
    text = AUTHORITY_TEXT.replace("Reference Date: 2026-01-01\n", "")
    with pytest.raises(ValueError, match="reference_date"):
        parse_glonass_authority_source("glo-authority.txt", text)


def test_unknown_field_is_rejected_for_authority_source() -> None:
    with pytest.raises(ValueError, match="unknown GLONASS authority field"):
        parse_glonass_authority_source("glo-authority.txt", AUTHORITY_TEXT + "Mystery: 1\n")


def test_duplicate_slots_are_rejected() -> None:
    with pytest.raises(ValueError, match="duplicate GLONASS slots"):
        parse_glonass_authority_source("glo-authority.txt", AUTHORITY_TEXT + "\n" + AUTHORITY_TEXT)
