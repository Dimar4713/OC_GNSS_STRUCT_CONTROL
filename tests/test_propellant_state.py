from __future__ import annotations

from pathlib import Path

import pytest

from constellation_control.application.propellant_state import (
    build_maneuver_resource_rows,
    resolve_operational_satellites,
)
from constellation_control.application.run import load_scenario
from constellation_control.domain.digital_twin import (
    DigitalTwinConfig,
    PropulsionSystem,
    SpacecraftOperationalState,
)
from constellation_control.domain.models import Maneuver


def _scenario():
    return load_scenario(Path("scenarios/mvp_45deg.yaml"))


def test_operational_state_overrides_mass_fuel_and_isp_for_propagation() -> None:
    source = _scenario()
    twin = DigitalTwinConfig(
        spacecraft_states=(
            SpacecraftOperationalState(
                satellite_id="DEMO-REF",
                dry_mass_kg=480.0,
                current_propellant_mass_kg=20.0,
                current_mass_kg=500.0,
                propulsion=PropulsionSystem(
                    system_type="chemical",
                    model_id="engine-a",
                    isp_s=310.0,
                ),
            ),
        )
    )
    scenario = source.model_copy(update={"digital_twin": twin})

    satellites = resolve_operational_satellites(scenario)
    by_id = {satellite.satellite_id: satellite for satellite in satellites}

    assert by_id["DEMO-REF"].spacecraft.dry_mass_kg == pytest.approx(480.0)
    assert by_id["DEMO-REF"].spacecraft.propellant_mass_kg == pytest.approx(20.0)
    assert by_id["DEMO-REF"].spacecraft.initial_mass_kg == pytest.approx(500.0)
    assert by_id["DEMO-REF"].spacecraft.isp_s == pytest.approx(310.0)
    assert by_id["DEMO-ADD-45"].spacecraft == source.constellation.satellites[1].spacecraft


def test_resource_rows_consume_propellant_sequentially() -> None:
    source = _scenario()
    twin = DigitalTwinConfig(
        spacecraft_states=(
            SpacecraftOperationalState(
                satellite_id="DEMO-REF",
                dry_mass_kg=480.0,
                current_propellant_mass_kg=20.0,
                current_mass_kg=500.0,
                propellant_capacity_kg=40.0,
                propulsion=PropulsionSystem(system_type="chemical", isp_s=300.0),
            ),
        )
    )
    scenario = source.model_copy(
        update={
            "digital_twin": twin,
            "maneuvers": (
                Maneuver(satellite_id="DEMO-REF", time_s=100.0, dv_rtn_m_s=(1.0, 0.0, 0.0)),
                Maneuver(satellite_id="DEMO-REF", time_s=200.0, dv_rtn_m_s=(0.0, 2.0, 0.0)),
            ),
        }
    )

    rows = [row for row in build_maneuver_resource_rows(scenario) if row["satellite_id"] == "DEMO-REF"]
    maneuver_rows = [row for row in rows if row["event"] == "maneuver"]

    assert len(maneuver_rows) == 2
    assert maneuver_rows[0]["mass_before_kg"] == pytest.approx(500.0)
    assert maneuver_rows[1]["mass_before_kg"] == pytest.approx(maneuver_rows[0]["mass_after_kg"])
    assert maneuver_rows[1]["residual_propellant_kg"] < maneuver_rows[0]["residual_propellant_kg"] < 20.0
    assert maneuver_rows[1]["propellant_used_kg"] == pytest.approx(
        maneuver_rows[0]["propellant_used_step_kg"] + maneuver_rows[1]["propellant_used_step_kg"]
    )
    assert maneuver_rows[0]["isp_s"] == pytest.approx(300.0)
    assert maneuver_rows[0]["isp_authority"] == "digital_twin.propulsion.isp_s"
    assert maneuver_rows[0]["required_reserve_kg"] == pytest.approx(4.0)


def test_insufficient_propellant_fails_closed_before_propagation() -> None:
    source = _scenario()
    twin = DigitalTwinConfig(
        spacecraft_states=(
            SpacecraftOperationalState(
                satellite_id="DEMO-REF",
                dry_mass_kg=499.9,
                current_propellant_mass_kg=0.1,
                current_mass_kg=500.0,
                propulsion=PropulsionSystem(system_type="chemical", isp_s=100.0),
            ),
        )
    )
    scenario = source.model_copy(
        update={
            "digital_twin": twin,
            "maneuvers": (
                Maneuver(satellite_id="DEMO-REF", time_s=100.0, dv_rtn_m_s=(100.0, 0.0, 0.0)),
            ),
        }
    )

    with pytest.raises(ValueError, match="insufficient propellant"):
        build_maneuver_resource_rows(scenario)


def test_passport_isp_remains_authority_when_digital_twin_has_no_isp_override() -> None:
    source = _scenario()
    twin = DigitalTwinConfig(
        spacecraft_states=(
            SpacecraftOperationalState(
                satellite_id="DEMO-REF",
                dry_mass_kg=500.0,
                current_propellant_mass_kg=10.0,
                propulsion=PropulsionSystem(system_type="chemical", model_id="engine-without-isp"),
            ),
        )
    )
    scenario = source.model_copy(update={"digital_twin": twin})

    row = next(row for row in build_maneuver_resource_rows(scenario) if row["satellite_id"] == "DEMO-REF")
    assert row["isp_s"] == pytest.approx(source.constellation.satellites[0].spacecraft.isp_s)
    assert row["isp_authority"] == "satellite.spacecraft.isp_s"
