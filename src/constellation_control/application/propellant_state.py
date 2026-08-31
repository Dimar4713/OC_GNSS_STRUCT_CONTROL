from __future__ import annotations

from math import exp, sqrt

from constellation_control.analysis.fuel import G0_M_S2
from constellation_control.domain.digital_twin import SpacecraftOperationalState
from constellation_control.domain.models import Maneuver, SatelliteSpec, ScenarioConfig, SpacecraftModel

_MASS_TOLERANCE_KG = 1.0e-9


def _state_map(scenario: ScenarioConfig) -> dict[str, SpacecraftOperationalState]:
    if scenario.digital_twin is None:
        return {}
    return {state.satellite_id: state for state in scenario.digital_twin.spacecraft_states}


def resolve_operational_spacecraft(
    satellite: SatelliteSpec,
    state: SpacecraftOperationalState | None,
) -> SpacecraftModel:
    if state is None:
        return satellite.spacecraft
    isp_s = satellite.spacecraft.isp_s
    if state.propulsion is not None and state.propulsion.isp_s is not None:
        isp_s = state.propulsion.isp_s
    return satellite.spacecraft.model_copy(
        update={
            "dry_mass_kg": state.dry_mass_kg,
            "propellant_mass_kg": state.current_propellant_mass_kg,
            "isp_s": isp_s,
        }
    )


def resolve_operational_satellites(scenario: ScenarioConfig) -> tuple[SatelliteSpec, ...]:
    states = _state_map(scenario)
    return tuple(
        satellite.model_copy(
            update={"spacecraft": resolve_operational_spacecraft(satellite, states.get(satellite.satellite_id))}
        )
        for satellite in scenario.constellation.satellites
    )


def _maneuver_delta_v_m_s(maneuver: Maneuver) -> float:
    radial, transverse, normal = maneuver.dv_rtn_m_s
    return sqrt(radial * radial + transverse * transverse + normal * normal)


def _reserve_basis_kg(
    satellite: SatelliteSpec,
    state: SpacecraftOperationalState | None,
) -> float:
    if state is not None and state.propellant_capacity_kg is not None:
        return state.propellant_capacity_kg
    return satellite.spacecraft.propellant_mass_kg


def build_maneuver_resource_rows(scenario: ScenarioConfig) -> list[dict[str, float | str]]:
    states = _state_map(scenario)
    rows: list[dict[str, float | str]] = []
    for satellite in scenario.constellation.satellites:
        state = states.get(satellite.satellite_id)
        spacecraft = resolve_operational_spacecraft(satellite, state)
        propellant_kg = spacecraft.propellant_mass_kg
        current_mass_kg = spacecraft.initial_mass_kg
        initial_propellant_kg = propellant_kg
        reserve_kg = _reserve_basis_kg(satellite, state) * scenario.constraints.propellant_reserve_fraction
        isp_source = (
            "digital_twin.propulsion.isp_s"
            if state is not None and state.propulsion is not None and state.propulsion.isp_s is not None
            else "satellite.spacecraft.isp_s"
        )
        maneuvers = sorted(
            (item for item in scenario.maneuvers if item.satellite_id == satellite.satellite_id),
            key=lambda item: item.time_s,
        )
        cumulative_delta_v = 0.0
        cumulative_used = 0.0
        rows.append(
            {
                "satellite_id": satellite.satellite_id,
                "time_s": 0.0,
                "event": "initial",
                "delta_v_m_s": 0.0,
                "cumulative_delta_v_m_s": 0.0,
                "mass_before_kg": current_mass_kg,
                "mass_after_kg": current_mass_kg,
                "propellant_used_step_kg": 0.0,
                "propellant_used_kg": 0.0,
                "residual_propellant_kg": propellant_kg,
                "initial_propellant_kg": initial_propellant_kg,
                "required_reserve_kg": reserve_kg,
                "isp_s": spacecraft.isp_s,
                "isp_authority": isp_source,
            }
        )
        for maneuver in maneuvers:
            delta_v = _maneuver_delta_v_m_s(maneuver)
            mass_before = current_mass_kg
            mass_after = mass_before * exp(-delta_v / (G0_M_S2 * spacecraft.isp_s))
            used_step = mass_before - mass_after
            if used_step > propellant_kg + _MASS_TOLERANCE_KG:
                raise ValueError(
                    "insufficient propellant for maneuver: "
                    f"satellite={satellite.satellite_id} time_s={maneuver.time_s:g} "
                    f"required_kg={used_step:.9g} available_kg={propellant_kg:.9g}"
                )
            propellant_kg = max(0.0, propellant_kg - used_step)
            current_mass_kg = mass_after
            cumulative_delta_v += delta_v
            cumulative_used += used_step
            if current_mass_kg + _MASS_TOLERANCE_KG < spacecraft.dry_mass_kg:
                raise ValueError(
                    f"maneuver would reduce {satellite.satellite_id} below dry mass"
                )
            rows.append(
                {
                    "satellite_id": satellite.satellite_id,
                    "time_s": float(maneuver.time_s),
                    "event": "maneuver",
                    "delta_v_m_s": delta_v,
                    "cumulative_delta_v_m_s": cumulative_delta_v,
                    "mass_before_kg": mass_before,
                    "mass_after_kg": current_mass_kg,
                    "propellant_used_step_kg": used_step,
                    "propellant_used_kg": cumulative_used,
                    "residual_propellant_kg": propellant_kg,
                    "initial_propellant_kg": initial_propellant_kg,
                    "required_reserve_kg": reserve_kg,
                    "isp_s": spacecraft.isp_s,
                    "isp_authority": isp_source,
                }
            )
        if scenario.duration_s > 0.0 and (not maneuvers or maneuvers[-1].time_s != scenario.duration_s):
            rows.append(
                {
                    "satellite_id": satellite.satellite_id,
                    "time_s": float(scenario.duration_s),
                    "event": "end",
                    "delta_v_m_s": 0.0,
                    "cumulative_delta_v_m_s": cumulative_delta_v,
                    "mass_before_kg": current_mass_kg,
                    "mass_after_kg": current_mass_kg,
                    "propellant_used_step_kg": 0.0,
                    "propellant_used_kg": cumulative_used,
                    "residual_propellant_kg": propellant_kg,
                    "initial_propellant_kg": initial_propellant_kg,
                    "required_reserve_kg": reserve_kg,
                    "isp_s": spacecraft.isp_s,
                    "isp_authority": isp_source,
                }
            )
    return rows
