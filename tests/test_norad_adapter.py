from __future__ import annotations

import json

import pytest

from constellation_control.adapters.norad import NoradFormat, parse_omm_json, parse_tle, preview_norad_import


TLE_TEXT = """ISS (ZARYA)
1 25544U 98067A   24001.50000000  .00000000  00000-0  00000-0 0  9992
2 25544  51.6400 123.4567 0005000  10.0000 350.0000 15.50000000123456
"""


def test_tle_parses_with_checksum_and_preserves_sgp4_semantics() -> None:
    records = parse_tle(TLE_TEXT)
    assert len(records) == 1
    record = records[0]
    assert record.source_format is NoradFormat.TLE
    assert record.satellite_number == 25544
    assert record.object_name == "ISS (ZARYA)"
    assert record.eccentricity == pytest.approx(0.0005)
    assert record.mean_motion_rev_per_day == pytest.approx(15.5)
    assert record.epoch_utc.isoformat().startswith("2024-01-01T12:00:00")


def test_tle_bad_checksum_fails_closed() -> None:
    broken = TLE_TEXT.replace("9992", "9993")
    with pytest.raises(ValueError, match="checksum"):
        parse_tle(broken)


def test_omm_json_normalizes_required_mean_elements() -> None:
    payload = {
        "OBJECT_NAME": "TEST SAT",
        "OBJECT_ID": "2024-001A",
        "NORAD_CAT_ID": "60001",
        "EPOCH": "2024-01-01T12:00:00Z",
        "MEAN_MOTION": 14.25,
        "ECCENTRICITY": 0.001,
        "INCLINATION": 55.0,
        "RA_OF_ASC_NODE": 120.0,
        "ARG_OF_PERICENTER": 10.0,
        "MEAN_ANOMALY": 20.0,
        "BSTAR": 1.2e-5,
        "ELEMENT_SET_NO": 7,
        "REV_AT_EPOCH": 123,
    }
    record = parse_omm_json(json.dumps(payload))[0]
    assert record.source_format is NoradFormat.OMM_JSON
    assert record.satellite_number == 60001
    assert record.mean_motion_rev_per_day == pytest.approx(14.25)
    assert record.epoch_utc.isoformat() == "2024-01-01T12:00:00+00:00"


def test_preview_is_explicitly_non_promotable_until_authoritative_conversion() -> None:
    preview = preview_norad_import("iss.tle", TLE_TEXT)
    assert preview.source_sha256
    assert preview.runnable_promotion_allowed is False
    assert "SGP4 mean elements" in preview.promotion_block_reason
    assert "Orekit TLE/SGP4" in preview.promotion_block_reason


def test_unsupported_extension_fails_closed() -> None:
    with pytest.raises(ValueError, match="supported NORAD input extensions"):
        preview_norad_import("orbit.csv", "x")
