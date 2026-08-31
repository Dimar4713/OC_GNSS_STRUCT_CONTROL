from __future__ import annotations

import json
from pathlib import Path

import pytest

from constellation_control.application.run import load_scenario
from constellation_control.application.run_promotion import (
    list_promotable_runs,
    load_promotable_run,
    promote_completed_run,
)
from constellation_control.domain.models import ExperimentRunManifest, PropagationResult


def _write_complete_run(output_root: Path, source_path: Path) -> tuple[str, str]:
    source = load_scenario(source_path)
    run_id = "11111111-2222-3333-4444-555555555555"
    run_dir = output_root / source.scenario_id / run_id
    run_dir.mkdir(parents=True)
    times = (0.0, source.duration_s)
    mean = {
        sat.satellite_id: (sat.mean_orbit, sat.mean_orbit)
        for sat in source.constellation.satellites
    }
    result = PropagationResult(
        backend="synthetic-test",
        backend_version="test",
        force_model_fingerprint=source.force_model.fingerprint(),
        backend_metadata={"test": "true"},
        times_s=times,
        mean_orbits=mean,
        cartesian_states={},
    )
    manifest = ExperimentRunManifest(
        scenario_id=source.scenario_id,
        run_id=run_id,
        config_hash=source.config_hash(),
        code_version="test",
        force_model_fingerprint=source.force_model.fingerprint(),
        force_model_mode=source.force_model.mode,
        force_model=source.force_model,
        integrator=source.integrator,
        constraints=source.constraints,
        frame=source.frame,
        time_scale=source.time_scale,
        mean_element_definitions={
            sat.satellite_id: sat.mean_orbit.definition
            for sat in source.constellation.satellites
        },
        backend=result.backend,
        backend_version=result.backend_version,
        backend_metadata=result.backend_metadata,
        epoch=source.epoch,
        random_seed=source.seed,
        algorithm_versions={"test": "1"},
    )
    (run_dir / "manifest.json").write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
    (run_dir / "scenario.normalized.json").write_text(
        json.dumps(source.model_dump(mode="json"), indent=2, sort_keys=True),
        encoding="utf-8",
    )
    (run_dir / "propagation_result.json").write_text(result.model_dump_json(indent=2), encoding="utf-8")
    (run_dir / "resources.json").write_text("[]\n", encoding="utf-8")
    return source.scenario_id, run_id


def test_completed_run_promotion_creates_runnable_child(tmp_path: Path) -> None:
    output_root = tmp_path / "runs"
    scenario_root = tmp_path / "scenarios"
    scenario_root.mkdir()
    source_path = Path("scenarios/mvp_45deg.yaml")
    scenario_id, run_id = _write_complete_run(output_root, source_path)

    result = promote_completed_run(
        scenario_root,
        output_root,
        scenario_id=scenario_id,
        run_id=run_id,
        target_scenario_name="continued.yaml",
        new_scenario_id="continued-from-run",
    )

    assert result["saved"] is True
    assert result["source_run_id"] == run_id
    child = load_scenario(scenario_root / "continued.yaml")
    parent = load_scenario(source_path)
    assert child.scenario_id == "continued-from-run"
    assert child.epoch > parent.epoch
    assert child.maneuvers == ()
    assert child.digital_twin is not None
    assert child.digital_twin.lineage is not None
    assert child.digital_twin.lineage.transformation == "propagated_state"


def test_missing_propagation_result_is_not_promotable(tmp_path: Path) -> None:
    output_root = tmp_path / "runs"
    scenario_id, run_id = _write_complete_run(output_root, Path("scenarios/mvp_45deg.yaml"))
    (output_root / scenario_id / run_id / "propagation_result.json").unlink()

    with pytest.raises(ValueError, match="missing artifacts"):
        load_promotable_run(output_root, scenario_id=scenario_id, run_id=run_id)
    assert list_promotable_runs(output_root) == []


def test_tampered_normalized_scenario_hash_fails_closed(tmp_path: Path) -> None:
    output_root = tmp_path / "runs"
    scenario_id, run_id = _write_complete_run(output_root, Path("scenarios/mvp_45deg.yaml"))
    path = output_root / scenario_id / run_id / "scenario.normalized.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["seed"] = int(payload["seed"]) + 1
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="config hash"):
        load_promotable_run(output_root, scenario_id=scenario_id, run_id=run_id)


def test_target_overwrite_remains_forbidden(tmp_path: Path) -> None:
    output_root = tmp_path / "runs"
    scenario_root = tmp_path / "scenarios"
    scenario_root.mkdir()
    scenario_id, run_id = _write_complete_run(output_root, Path("scenarios/mvp_45deg.yaml"))
    (scenario_root / "continued.yaml").write_text("existing\n", encoding="utf-8")

    with pytest.raises(ValueError, match="overwrite"):
        promote_completed_run(
            scenario_root,
            output_root,
            scenario_id=scenario_id,
            run_id=run_id,
            target_scenario_name="continued.yaml",
            new_scenario_id="continued-from-run",
        )
