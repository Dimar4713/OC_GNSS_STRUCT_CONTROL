from __future__ import annotations

from dataclasses import dataclass
from math import radians

from constellation_control.adapters.glonass_almanac_authority import GlonassAuthorityRecord
from constellation_control.adapters.iac_glonass_almanac import IacGlonassAlmanacRecord


GLONASS_NOMINAL_INCLINATION_DEG = 64.8
GLONASS_NOMINAL_DRACONIAN_PERIOD_S = 40_544.0


@dataclass(frozen=True)
class IacGlonassAuthoritySupplement:
    """Authority fields not present in the IAC almanac table.

    These values are deliberately mandatory. They must come from an explicit
    operator/source authority and are never silently defaulted by the bridge.
    """

    health: int
    glo_to_utc_s: float
    gps_to_glo_s: float
    glo_time_offset_s: float


def iac_glonass_to_authority_record(
    record: IacGlonassAlmanacRecord,
    supplement: IacGlonassAuthoritySupplement,
) -> GlonassAuthorityRecord:
    """Map an IAC GLONASS record into the existing Orekit authority contract.

    Source/spec mappings used here are explicit:
    - delta_i = i - 64.8 deg;
    - delta_t = T_orbit - 40544 s;
    - delta_t_dot = IAC rate-of-change field;
    - node longitude/perigee angle are converted degrees -> radians.

    IAC `delta_t2` is intentionally not substituted for any Orekit time-scale
    correction: the IAC legend describes it as an onboard-clock correction,
    while the current authority contract requires three separately identified
    time corrections. Those remain mandatory supplementary inputs.
    """

    if supplement.health < 0:
        raise ValueError("GLONASS health must be non-negative")
    return GlonassAuthorityRecord(
        slot=record.slot,
        frequency_channel=record.frequency_channel,
        health=supplement.health,
        reference_date=record.base_date_dmv,
        reference_time_s=record.ascending_node_time_s,
        lambda_rad=record.ascending_node_longitude_rad,
        delta_i_rad=radians(record.inclination_deg - GLONASS_NOMINAL_INCLINATION_DEG),
        eccentricity=record.eccentricity,
        argument_of_perigee_rad=record.argument_of_perigee_rad,
        delta_t_s=record.orbital_period_s - GLONASS_NOMINAL_DRACONIAN_PERIOD_S,
        delta_t_dot=record.draconian_period_rate,
        glo_to_utc_s=supplement.glo_to_utc_s,
        gps_to_glo_s=supplement.gps_to_glo_s,
        glo_time_offset_s=supplement.glo_time_offset_s,
    )
