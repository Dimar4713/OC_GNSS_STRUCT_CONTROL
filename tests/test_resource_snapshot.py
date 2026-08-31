from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from constellation_control.application.resource_snapshot import (
    SNAPSHOT_VERSION,
    build_operational_resource_snapshot,
    save_operational_resource_snapshot,
)
from constellation_control.application.run import load_scenario
from constellation_control.domain.digital_twin import DigitalTwinConfig, PropulsionSystem, SpacecraftOperationalState
from constellation_control.domain.models import Maneuver


def _scenario():
    source = load_scenario(Path("scenarios/mvp_45deg.yaml"))
    return source.model_copy(
        update={
            "digital_twin": DigitalTwinConfig(
                spacecraft_states=(
                    SpacecraftOperationalState(
                        satellite_id="DEMO-REF",
                        dry_mass_kg=480.0,
                        current_propellant_mass_kg=20.0,
                        current_mass_kg=500.0,
                        propulsion=PropulsionSystem(system_type="chemical", isp_s=300.0),
                    ),
                )
            ),
            "maneuvers": (
                Maneuver(satellite_id="DEMO-REF", time_s=100.0, dv_rtn_m_s=(1.0, 0.0, 0.0)),
            ),
        }
    )


def test_snapshot_records_final_operational_state_without_advancing_orbit() -> None:
    scenario = _scenario()
    snapshot = build_operational_resource_snapshot(scenario)
    assert snapshot["snapshot_version"] == SNAPSHOT_VERSION
    assert snapshot["source_scenario_id"] == scenario.scenario_id
    assert snapshot["source_config_hash"] == scenario.config_hash()
    assert snapshot["snapshot_time_s"] == scenario.duration_s
    assert "orbital state and epoch are not advanced" in str(snapshot["semantics"])
    state = next(item for item in snapshot["spacecraft_states"] if item["satellite_id"] == "DEMO-REF")
    assert state["current_propellant_mass_kg"] < 20.0
    assert state["current_mass_kg"] < 500.0
    final = [row for row in snapshot["maneuver_resource_history"] if row["satellite_id"] == "DEMO-REF"][-1]
    assert state["current_propellant_mass_kg"] == pytest.approx(final["residual_propellant_kg"])
    assert state["current_mass_kg"] == pytest.approx(final["mass_after_kg"])


def test_snapshot_save_is_immutable_and_separate_from_scenarios(tmp_path: Path) -> None:
    scenario = _scenario()
    scenario_root = tmp_path / "scenarios"
    scenario_root.mkdir()
    source = scenario_root / "source.yaml"
    source.write_text(yaml.safe_dump(scenario.model_dump(mode="json"), sort_keys=False), encoding="utf-8")
    before = source.read_bytes()
    output_root = tmp_path / "runs"

    path = save_operational_resource_snapshot(scenario, output_root, "state-01.yaml")
    assert path == output_root / "state-snapshots" / "state-01.yaml"
    assert source.read_bytes() == before
    assert not (scenario_root / "state-01.yaml").exists()
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert payload["source_config_hash"] == scenario.config_hash()

    with pytest.raises(ValueError, match="overwrite"):
        save_operational_resource_snapshot(scenario, output_root, "state-01.yaml")
    with pytest.raises(ValueError, match="path components"):
        save_operational_resource_snapshot(scenario, output_root, "../state-02.yaml")
