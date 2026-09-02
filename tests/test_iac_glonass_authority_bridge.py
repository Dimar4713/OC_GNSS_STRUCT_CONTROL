from math import isclose, radians

import pytest

from constellation_control.adapters.iac_glonass_almanac import IacGlonassAlmanacRecord
from constellation_control.adapters.iac_glonass_authority_bridge import (
    GLONASS_NOMINAL_DRACONIAN_PERIOD_S,
    GLONASS_NOMINAL_INCLINATION_DEG,
    IacGlonassAuthoritySupplement,
    iac_glonass_to_authority_record,
)


def _record() -> IacGlonassAlmanacRecord:
    from datetime import date

    return IacGlonassAlmanacRecord(
        slot=1,
        base_date_dmv=date(2026, 8, 8),
        ascending_node_time_s=5679.75,
        orbital_period_s=40543.81,
        eccentricity=0.00039,
        inclination_deg=65.037445,
        ascending_node_longitude_deg=134.09329,
        argument_of_perigee_deg=37.58972,
        onboard_time_correction_s=-1.7929077e-4,
        frequency_channel=1,
        draconian_period_rate=-4.272461e-4,
    )


def test_iac_glonass_bridge_maps_only_proven_fields() -> None:
    supplement = IacGlonassAuthoritySupplement(
        health=0,
        glo_to_utc_s=1.0,
        gps_to_glo_s=2.0,
        glo_time_offset_s=3.0,
    )
    authority = iac_glonass_to_authority_record(_record(), supplement)

    assert authority.slot == 1
    assert authority.reference_date.isoformat() == "2026-08-08"
    assert authority.reference_time_s == 5679.75
    assert isclose(authority.lambda_rad, radians(134.09329))
    assert isclose(authority.delta_i_rad, radians(65.037445 - GLONASS_NOMINAL_INCLINATION_DEG))
    assert isclose(authority.delta_t_s, 40543.81 - GLONASS_NOMINAL_DRACONIAN_PERIOD_S)
    assert authority.delta_t_dot == -4.272461e-4
    assert authority.glo_to_utc_s == 1.0
    assert authority.gps_to_glo_s == 2.0
    assert authority.glo_time_offset_s == 3.0


def test_iac_delta_t2_is_not_silently_used_as_time_scale_correction() -> None:
    supplement = IacGlonassAuthoritySupplement(
        health=0,
        glo_to_utc_s=10.0,
        gps_to_glo_s=20.0,
        glo_time_offset_s=30.0,
    )
    authority = iac_glonass_to_authority_record(_record(), supplement)
    assert authority.glo_time_offset_s == 30.0
    assert authority.glo_time_offset_s != _record().onboard_time_correction_s


def test_iac_glonass_bridge_rejects_invalid_health() -> None:
    supplement = IacGlonassAuthoritySupplement(
        health=-1,
        glo_to_utc_s=0.0,
        gps_to_glo_s=0.0,
        glo_time_offset_s=0.0,
    )
    with pytest.raises(ValueError, match="health"):
        iac_glonass_to_authority_record(_record(), supplement)
