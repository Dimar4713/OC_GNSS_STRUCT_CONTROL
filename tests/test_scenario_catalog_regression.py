from __future__ import annotations

import shutil
from pathlib import Path

from fastapi.testclient import TestClient

from constellation_control.preview.gravity_release_app import create_preview_app


def _copy_scenarios(target: Path) -> None:
    target.mkdir(parents=True, exist_ok=True)
    for source in Path("scenarios").glob("*.y*ml"):
        shutil.copy2(source, target / source.name)


def test_gravity_derived_scenario_round_trip_and_force_model_guard(tmp_path: Path) -> None:
    scenario_root = tmp_path / "scenarios"
    output_root = tmp_path / "runs"
    _copy_scenarios(scenario_root)
    client = TestClient(create_preview_app(scenario_root, output_root))

    baseline = client.get("/api/scenarios")
    assert baseline.status_code == 200
    before = baseline.json()
    assert len(before["scenarios"]) == 6
    assert {item["name"] for item in before["other_inputs"]} == {
        "design_pipeline_smoke.yaml",
        "robustness_campaign_smoke.yaml",
    }

    same_force = client.post(
        "/api/gravity-model/create",
        json={
            "source_scenario_name": "orekit_validation_smoke.yaml",
            "target_scenario_name": "orekit-validation-copy.yaml",
            "new_scenario_id": "orekit-validation-copy",
            "gravity_degree": 8,
            "gravity_order": 8,
        },
    )
    assert same_force.status_code == 200, same_force.text
    payload = same_force.json()
    assert payload["scenario_name"] == "orekit-validation-copy.yaml"
    assert "orekit-validation-copy.yaml" in payload["catalog"]["scenarios"]
    assert len(payload["catalog"]["scenarios"]) == 7

    # The unit-test process deliberately has no Orekit sidecar running. Changing
    # the force model must therefore fail closed with a bilingual structured
    # diagnostic, rather than copying stale mean elements or writing a bad YAML.
    changed_force = client.post(
        "/api/gravity-model/create",
        json={
            "source_scenario_name": "orekit_validation_smoke.yaml",
            "target_scenario_name": "orekit-validation-32x32.yaml",
            "new_scenario_id": "orekit-validation-32x32",
            "gravity_degree": 32,
            "gravity_order": 32,
        },
    )
    assert changed_force.status_code == 422
    detail = changed_force.json()["detail"]
    assert detail["code"] == "gravity_rederive_failed"
    assert "Orekit" in detail["ru"]
    assert "средние элементы" in detail["ru"]
    assert "Orekit" in detail["en"]
    assert "mean elements" in detail["en"]
    assert not (scenario_root / "orekit-validation-32x32.yaml").exists()

    refreshed = client.get("/api/scenarios")
    assert refreshed.status_code == 200
    after = refreshed.json()
    assert "orekit-validation-copy.yaml" in after["scenarios"]
    assert "orekit-validation-32x32.yaml" not in after["scenarios"]
    assert len(after["scenarios"]) == 7
