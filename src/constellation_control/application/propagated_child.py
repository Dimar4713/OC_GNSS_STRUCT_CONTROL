from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import yaml

from constellation_control.application.propellant_state import (
    build_maneuver_resource_rows,
    resolve_operational_satellites,
)
from constellation_control.domain.digital_twin import (
    DigitalTwinConfig,
    ScenarioLineage,
    SpacecraftOperationalState,
)
from constellation_control.domain.models import ConstellationSpec, PropagationResult, ScenarioConfig

_TIME_TOLERANCE_S = 1.0e-6


def _safe_new_yaml_path(root: Path, name: str) -> Path:
    if not name or Path(name).name != name or not name.lower().endswith((".yaml", ".yml")):
        raise ValueError("target_scenario_name must be a new YAML file name without path components")
    base = root.resolve()
    base.mkdir(parents=True, exist_ok=True)
    target = (base / name).resolve()
    if target.parent != base:
        raise ValueError("invalid target scenario path")
    if target.exists():
        raise ValueError("target scenario already exists; overwrite is forbidden")
    return target


def _validate_complete_result(source: ScenarioConfig, result: PropagationResult) -> None:
    if result.force_model_fingerprint != source.force_model.fingerprint():
        raise ValueError("propagation result force-model fingerprint does not match source scenario")
    if not result.times_s:
        raise ValueError("propagation result contains no output times")
    final_time = float(result.times_s[-1])
    if abs(final_time - source.duration_s) > _TIME_TOLERANCE_S:
        raise ValueError(
            f"propagation result is incomplete: final_time_s={final_time:g} duration_s={source.duration_s:g}"
        )
    known = {sat.satellite_id for sat in source.constellation.satellites}
    if set(result.mean_orbits) != known:
        raise ValueError("propagation result mean-orbit satellite set does not match source constellation")
    for satellite_id in known:
        series = result.mean_orbits[satellite_id]
        if len(series) != len(result.times_s):
            raise ValueError(f"mean-orbit series length mismatch for {satellite_id}")
        if not series:
            raise ValueError(f"mean-orbit series is empty for {satellite_id}")


def build_propagated_child(
    source: ScenarioConfig,
    result: PropagationResult,
    *,
    new_scenario_id: str,
) -> ScenarioConfig:
    if not new_scenario_id or new_scenario_id == source.scenario_id:
        raise ValueError("new_scenario_id must be non-empty and differ from parent scenario_id")
    _validate_complete_result(source, result)

    resource_rows = build_maneuver_resource_rows(source)
    final_resource: dict[str, dict[str, float | str]] = {}
    for row in resource_rows:
        final_resource[str(row["satellite_id"])] = row

    operational = {sat.satellite_id: sat for sat in resolve_operational_satellites(source)}
    source_states = (
        {state.satellite_id: state for state in source.digital_twin.spacecraft_states}
        if source.digital_twin is not None
        else {}
    )

    child_satellites = []
    child_states = []
    for satellite in source.constellation.satellites:
        satellite_id = satellite.satellite_id
        final_row = final_resource[satellite_id]
        final_propellant = float(final_row["residual_propellant_kg"])
        final_mass = float(final_row["mass_after_kg"])
        operational_satellite = operational[satellite_id]
        child_spacecraft = operational_satellite.spacecraft.model_copy(
            update={"propellant_mass_kg": final_propellant}
        )
        child_satellites.append(
            satellite.model_copy(
                update={
                    "mean_orbit": result.mean_orbits[satellite_id][-1],
                    "spacecraft": child_spacecraft,
                }
            )
        )

        previous_state = source_states.get(satellite_id)
        child_states.append(
            SpacecraftOperationalState(
                satellite_id=satellite_id,
                spacecraft_model_id=(previous_state.spacecraft_model_id if previous_state is not None else None),
                dry_mass_kg=child_spacecraft.dry_mass_kg,
                current_propellant_mass_kg=final_propellant,
                propellant_capacity_kg=(previous_state.propellant_capacity_kg if previous_state is not None else None),
                current_mass_kg=final_mass,
                propulsion=(previous_state.propulsion if previous_state is not None else None),
                correction_system=(previous_state.correction_system if previous_state is not None else None),
            )
        )

    groups = source.digital_twin.groups if source.digital_twin is not None else ()
    child_twin = DigitalTwinConfig(
        spacecraft_states=tuple(child_states),
        groups=groups,
        lineage=ScenarioLineage(
            parent_scenario_id=source.scenario_id,
            parent_config_hash=source.config_hash(),
            transformation="propagated_state",
            random_seed=source.seed,
        ),
    )
    child_constellation = ConstellationSpec(
        satellites=tuple(child_satellites),
        planes=source.constellation.planes,
    )
    child_epoch = source.epoch + timedelta(seconds=source.duration_s)
    child = source.model_copy(
        update={
            "scenario_id": new_scenario_id,
            "epoch": child_epoch,
            "constellation": child_constellation,
            "maneuvers": (),
            "digital_twin": child_twin,
        }
    )
    return ScenarioConfig.model_validate(child.model_dump(mode="json"))


def save_propagated_child(
    scenario_root: Path,
    source: ScenarioConfig,
    result: PropagationResult,
    *,
    target_scenario_name: str,
    new_scenario_id: str,
) -> dict[str, object]:
    target = _safe_new_yaml_path(scenario_root, target_scenario_name)
    child = build_propagated_child(source, result, new_scenario_id=new_scenario_id)
    target.write_text(
        yaml.safe_dump(child.model_dump(mode="json"), sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    return {
        "saved": True,
        "scenario_name": target.name,
        "scenario_id": child.scenario_id,
        "parent_scenario_id": source.scenario_id,
        "parent_config_hash": source.config_hash(),
        "child_config_hash": child.config_hash(),
        "epoch": child.epoch.isoformat(),
        "satellite_count": len(child.constellation.satellites),
    }
