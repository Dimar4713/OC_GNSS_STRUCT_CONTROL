from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from constellation_control.application.run import load_scenario
from constellation_control.domain.models import ExperimentRunManifest, PropagationResult
from constellation_control.preview.consolidated_release_app import create_preview_app, render_preview_page_for_test


def _write_promotable_run(output_root: Path) -> tuple[str, str]:
    source = load_scenario(Path("scenarios/mvp_45deg.yaml"))
    run_id = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    run_dir = output_root / source.scenario_id / run_id
    run_dir.mkdir(parents=True)
    result = PropagationResult(
        backend="synthetic-test",
        backend_version="test",
        force_model_fingerprint=source.force_model.fingerprint(),
        backend_metadata={},
        times_s=(0.0, source.duration_s),
        mean_orbits={sat.satellite_id: (sat.mean_orbit, sat.mean_orbit) for sat in source.constellation.satellites},
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
        mean_element_definitions={sat.satellite_id: sat.mean_orbit.definition for sat in source.constellation.satellites},
        backend=result.backend,
        backend_version=result.backend_version,
        backend_metadata={},
        epoch=source.epoch,
        random_seed=source.seed,
        algorithm_versions={"test": "1"},
    )
    (run_dir / "manifest.json").write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
    (run_dir / "scenario.normalized.json").write_text(
        json.dumps(source.model_dump(mode="json"), indent=2, sort_keys=True), encoding="utf-8"
    )
    (run_dir / "propagation_result.json").write_text(result.model_dump_json(indent=2), encoding="utf-8")
    (run_dir / "resources.json").write_text("[]\n", encoding="utf-8")
    return source.scenario_id, run_id


def test_packaged_page_contains_completed_run_promotion_controls() -> None:
    page = render_preview_page_for_test()
    assert 'id="runPromotionCard"' in page
    assert "/api/promotable-runs" in page
    assert "promoteCompletedRun" in page


def test_promotable_run_routes_create_and_select_continuation(tmp_path: Path) -> None:
    scenario_root = tmp_path / "scenarios"
    scenario_root.mkdir()
    output_root = tmp_path / "runs"
    scenario_id, run_id = _write_promotable_run(output_root)
    app = create_preview_app(scenario_root=scenario_root, output_root=output_root)
    client = TestClient(app)

    listing = client.get("/api/promotable-runs")
    assert listing.status_code == 200
    assert listing.json()["runs"][0]["run_id"] == run_id

    response = client.post(
        "/api/promotable-runs/promote",
        json={
            "scenario_id": scenario_id,
            "run_id": run_id,
            "target_scenario_name": "continued.yaml",
            "new_scenario_id": "continued-from-ui",
        },
    )
    assert response.status_code == 200
    assert response.json()["scenario_name"] == "continued.yaml"
    child = load_scenario(scenario_root / "continued.yaml")
    assert child.scenario_id == "continued-from-ui"
    assert child.maneuvers == ()


def test_run_writer_persists_propagation_result_evidence() -> None:
    source = Path("src/constellation_control/application/run.py").read_text(encoding="utf-8")
    assert 'run_dir / "propagation_result.json"' in source
    assert "result.model_dump_json(indent=2)" in source
