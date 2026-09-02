from __future__ import annotations

import shutil
from pathlib import Path

from fastapi.testclient import TestClient

from constellation_control.preview.gravity_release_app import create_preview_app


def _copy_scenarios(target: Path) -> None:
    target.mkdir(parents=True, exist_ok=True)
    for source in Path("scenarios").glob("*.y*ml"):
        shutil.copy2(source, target / source.name)


def test_gravity_derived_scenario_is_immediately_discoverable(tmp_path: Path) -> None:
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

    created = client.post(
        "/api/gravity-model/create",
        json={
            "source_scenario_name": "orekit_validation_smoke.yaml",
            "target_scenario_name": "orekit-validation-32x32.yaml",
            "new_scenario_id": "orekit-validation-32x32",
            "gravity_degree": 32,
            "gravity_order": 32,
        },
    )
    assert created.status_code == 200, created.text
    payload = created.json()
    assert payload["scenario_name"] == "orekit-validation-32x32.yaml"
    assert "orekit-validation-32x32.yaml" in payload["catalog"]["scenarios"]
    assert len(payload["catalog"]["scenarios"]) == 7

    refreshed = client.get("/api/scenarios")
    assert refreshed.status_code == 200
    after = refreshed.json()
    assert "orekit-validation-32x32.yaml" in after["scenarios"]
    assert len(after["scenarios"]) == 7
