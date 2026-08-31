from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest

from constellation_control.adapters.synthetic.propagator import SyntheticMeanPropagator
from constellation_control.application.propagated_child import build_propagated_child, save_propagated_child
from constellation_control.application.propellant_state import resolve_operational_satellites
from constellation_control.application.run import load_scenario
from constellation_control.domain.models import PropagationRequest


def _propagate(source):
    request = PropagationRequest(
        scenario_id=source.scenario_id,
        epoch=source.epoch,
        frame=source.frame,
        time_scale=source.time_scale,
        satellites=resolve_operational_satellites(source),
        maneuvers=source.maneuvers,
        duration_s=source.duration_s,
        output_step_s=source.output_step_s,
        force_model=source.force_model,
        integrator=source.integrator,
        seed=source.seed,
    )
    return SyntheticMeanPropagator().propagate(request)


def test_propagated_child_advances_epoch_orbits_and_resource_state() -> None:
    source = load_scenario(Path("scenarios/mvp_45deg.yaml"))
    result = _propagate(source)

    child = build_propagated_child(source, result, new_scenario_id="mvp-continued")

    assert child.epoch == source.epoch + timedelta(seconds=source.duration_s)
    assert child.maneuvers == ()
    assert child.force_model == source.force_model
    assert child.frame == source.frame
    assert child.time_scale == source.time_scale
    assert child.digital_twin is not None
    assert child.digital_twin.lineage is not None
    assert child.digital_twin.lineage.transformation == "propagated_state"
    assert child.digital_twin.lineage.parent_scenario_id == source.scenario_id
    assert child.digital_twin.lineage.parent_config_hash == source.config_hash()

    source_by_id = {sat.satellite_id: sat for sat in source.constellation.satellites}
    for satellite in child.constellation.satellites:
        assert satellite.mean_orbit == result.mean_orbits[satellite.satellite_id][-1]
        state = next(
            item for item in child.digital_twin.spacecraft_states if item.satellite_id == satellite.satellite_id
        )
        assert state.current_mass_kg == pytest.approx(
            state.dry_mass_kg + state.current_propellant_mass_kg
        )
        assert satellite.spacecraft.propellant_mass_kg == pytest.approx(state.current_propellant_mass_kg)
        assert satellite.spacecraft.area_m2 == source_by_id[satellite.satellite_id].spacecraft.area_m2


def test_propagated_child_rejects_incomplete_result() -> None:
    source = load_scenario(Path("scenarios/mvp_45deg.yaml"))
    result = _propagate(source)
    incomplete = result.model_copy(update={"times_s": result.times_s[:-1]})

    with pytest.raises(ValueError, match="incomplete"):
        build_propagated_child(source, incomplete, new_scenario_id="bad-child")


def test_save_propagated_child_is_immutable(tmp_path: Path) -> None:
    source = load_scenario(Path("scenarios/mvp_45deg.yaml"))
    result = _propagate(source)

    saved = save_propagated_child(
        tmp_path,
        source,
        result,
        target_scenario_name="continued.yaml",
        new_scenario_id="continued",
    )
    child = load_scenario(tmp_path / "continued.yaml")
    assert saved["child_config_hash"] == child.config_hash()
    assert child.epoch > source.epoch

    with pytest.raises(ValueError, match="overwrite"):
        save_propagated_child(
            tmp_path,
            source,
            result,
            target_scenario_name="continued.yaml",
            new_scenario_id="continued-2",
        )
