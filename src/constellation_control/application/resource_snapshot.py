from __future__ import annotations

from pathlib import Path

import yaml

from constellation_control.application.propellant_state import build_maneuver_resource_rows
from constellation_control.domain.digital_twin import SpacecraftOperationalState
from constellation_control.domain.models import ScenarioConfig

SNAPSHOT_VERSION = "operational-resource-state-v1"


def _existing_state_map(scenario: ScenarioConfig) -> dict[str, SpacecraftOperationalState]:
    if scenario.digital_twin is None:
        return {}
    return {state.satellite_id: state for state in scenario.digital_twin.spacecraft_states}


def build_operational_resource_snapshot(scenario: ScenarioConfig) -> dict[str, object]:
    rows = build_maneuver_resource_rows(scenario)
    by_satellite: dict[str, list[dict[str, float | str]]] = {}
    for row in rows:
        by_satellite.setdefault(str(row["satellite_id"]), []).append(row)
    existing = _existing_state_map(scenario)
    states: list[dict[str, object]] = []
    for satellite in scenario.constellation.satellites:
        history = by_satellite[satellite.satellite_id]
        final = history[-1]
        prior = existing.get(satellite.satellite_id)
        state = SpacecraftOperationalState(
            satellite_id=satellite.satellite_id,
            spacecraft_model_id=prior.spacecraft_model_id if prior else None,
            dry_mass_kg=satellite.spacecraft.dry_mass_kg if prior is None else prior.dry_mass_kg,
            current_propellant_mass_kg=float(final["residual_propellant_kg"]),
            propellant_capacity_kg=prior.propellant_capacity_kg if prior else None,
            current_mass_kg=float(final["mass_after_kg"]),
            propulsion=prior.propulsion if prior else None,
            correction_system=prior.correction_system if prior else None,
        )
        states.append(state.model_dump(mode="json"))
    return {
        "snapshot_version": SNAPSHOT_VERSION,
        "source_scenario_id": scenario.scenario_id,
        "source_config_hash": scenario.config_hash(),
        "snapshot_time_s": float(scenario.duration_s),
        "semantics": "planned operational resource state after all scheduled maneuvers; orbital state and epoch are not advanced",
        "spacecraft_states": states,
        "maneuver_resource_history": rows,
    }


def save_operational_resource_snapshot(
    scenario: ScenarioConfig,
    output_root: Path,
    snapshot_name: str,
) -> Path:
    if not snapshot_name or Path(snapshot_name).name != snapshot_name:
        raise ValueError("snapshot_name must be a file name without path components")
    if not snapshot_name.lower().endswith((".yaml", ".yml")):
        raise ValueError("snapshot_name must end with .yaml or .yml")
    root = (output_root / "state-snapshots").resolve()
    root.mkdir(parents=True, exist_ok=True)
    target = (root / snapshot_name).resolve()
    if target.parent != root:
        raise ValueError("invalid snapshot path")
    if target.exists():
        raise ValueError("snapshot already exists; overwrite is forbidden")
    payload = build_operational_resource_snapshot(scenario)
    target.write_text(yaml.safe_dump(payload, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return target
