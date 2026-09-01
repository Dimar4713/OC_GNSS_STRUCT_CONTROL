from datetime import timezone
from math import isclose, pi

import pytest

from constellation_control.adapters.iac_glonass_almanac import normalize_iac_glonass_almanac
from constellation_control.adapters.iac_gnss_tables import IacDataset, parse_iac_text


def _table(text: str):
    return parse_iac_text(IacDataset.GLONASS_ALMANAC, text, source_url="https://glonass-iac.ru/glonass/ephemeris/")


def test_normalizes_declared_glonass_iac_units_and_time_scale() -> None:
    table = _table(
        "NS\tДата\tTΩ\tTоб\te\ti\tLΩ\tω\tδt2\tnl\tΔT\n"
        "01\t08.08.26\t5679.75\t40543.81\t0.00039\t65.037445\t134.09329\t37.58972\t-1.7929077E-4\t1\t-4.272461E-4\n"
    )
    record = normalize_iac_glonass_almanac(table).records[0]

    assert record.slot == 1
    assert record.base_date_dmv.isoformat() == "2026-08-08"
    assert record.ascending_node_time_s == 5679.75
    assert record.orbital_period_s == 40543.81
    assert record.frequency_channel == 1
    assert record.onboard_time_correction_s == -1.7929077e-4
    assert record.draconian_period_rate == -4.272461e-4
    assert isclose(record.inclination_rad, 65.037445 * pi / 180.0)
    assert isclose(record.ascending_node_longitude_rad, 134.09329 * pi / 180.0)
    assert isclose(record.argument_of_perigee_rad, 37.58972 * pi / 180.0)
    assert record.ascending_node_epoch_dmv.utcoffset().total_seconds() == 3 * 3600
    assert record.ascending_node_epoch_utc.tzinfo == timezone.utc
    assert record.ascending_node_epoch_utc.isoformat() == "2026-08-07T22:34:39.750000+00:00"


def test_accepts_decimal_comma_but_keeps_conversion_explicit() -> None:
    table = _table(
        "NS;Дата;TΩ;Tоб;e;i;LΩ;ω;δt2;nl;ΔT\n"
        "01;08.08.26;5679,75;40543,81;0,00039;65,037445;134,09329;37,58972;-1,7929077E-4;1;-4,272461E-4\n"
    )
    record = normalize_iac_glonass_almanac(table).records[0]
    assert record.orbital_period_s == 40543.81


def test_fails_closed_on_missing_declared_column() -> None:
    table = _table("NS\tДата\tTΩ\tTоб\te\ti\tLΩ\tω\tδt2\tnl\n01\t08.08.26\t1\t40544\t0\t64.8\t1\t2\t0\t1\n")
    with pytest.raises(ValueError, match="missing columns: ΔT"):
        normalize_iac_glonass_almanac(table)


def test_fails_closed_on_duplicate_satellite_number() -> None:
    table = _table(
        "NS\tДата\tTΩ\tTоб\te\ti\tLΩ\tω\tδt2\tnl\tΔT\n"
        "01\t08.08.26\t1\t40544\t0\t64.8\t1\t2\t0\t1\t0\n"
        "01\t08.08.26\t2\t40544\t0\t64.8\t2\t3\t0\t1\t0\n"
    )
    with pytest.raises(ValueError, match="duplicate"):
        normalize_iac_glonass_almanac(table)
