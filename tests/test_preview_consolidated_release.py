from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

import constellation_control.preview.consolidated_release_app as consolidated


def _repo_root() -> Path:
    return Path(__file__).parents[1]


def test_consolidated_release_page_and_health(tmp_path: Path) -> None:
    client = TestClient(consolidated.create_preview_app(_repo_root() / "scenarios", tmp_path))
    assert client.get("/health").json() == {"status": "ok", "preview": "0.2.2"}
    page = client.get("/").text
    assert "Engineering Preview 0.2.2" in page
    assert "Optimal Operations Workspace 0.2" in page
    assert 'id="scenarioEditor"' in page
    assert "/api/scenario-drafts/validate" in page
    assert "/api/scenario-drafts/save" in page


def test_scenario_editor_validates_and_saves_only_new_yaml(tmp_path: Path) -> None:
    source_root = _repo_root() / "scenarios"
    scenario_root = tmp_path / "scenarios"
    scenario_root.mkdir()
    source = source_root / "design_pipeline_screening_smoke.yaml"
    text = source.read_text(encoding="utf-8")
    (scenario_root / source.name).write_text(text, encoding="utf-8")

    client = TestClient(consolidated.create_preview_app(scenario_root, tmp_path / "runs"))
    opened = client.get(f"/api/scenarios/{source.name}")
    assert opened.status_code == 200
    original = opened.json()["yaml_text"]
    assert original == text

    edited = original.replace("duration_s: 7200", "duration_s: 8100", 1)
    if edited == original:
        edited = original.replace("duration_s: 3600", "duration_s: 4500", 1)
    assert edited != original

    validated = client.post("/api/scenario-drafts/validate", json={"yaml_text": edited})
    assert validated.status_code == 200
    assert validated.json()["valid"] is True

    saved = client.post(
        "/api/scenario-drafts/save",
        json={"scenario_name": "operator-edited.yaml", "yaml_text": edited},
    )
    assert saved.status_code == 200
    assert saved.json()["scenario_name"] == "operator-edited.yaml"
    assert (scenario_root / "operator-edited.yaml").read_text(encoding="utf-8") == edited.rstrip("\n") + "\n"
    assert (scenario_root / source.name).read_text(encoding="utf-8") == original

    catalog = client.get("/api/scenarios").json()["scenarios"]
    assert "operator-edited.yaml" in catalog

    overwrite = client.post(
        "/api/scenario-drafts/save",
        json={"scenario_name": source.name, "yaml_text": edited},
    )
    assert overwrite.status_code == 422
    assert "never overwritten" in overwrite.json()["detail"]


def test_scenario_editor_rejects_invalid_yaml_and_path_escape(tmp_path: Path) -> None:
    scenario_root = tmp_path / "scenarios"
    scenario_root.mkdir()
    client = TestClient(consolidated.create_preview_app(scenario_root, tmp_path / "runs"))

    invalid = client.post("/api/scenario-drafts/validate", json={"yaml_text": "scenario_id: ["})
    assert invalid.status_code == 422

    source = (_repo_root() / "scenarios" / "design_pipeline_screening_smoke.yaml").read_text(encoding="utf-8")
    escaped = client.post(
        "/api/scenario-drafts/save",
        json={"scenario_name": "../escape.yaml", "yaml_text": source},
    )
    assert escaped.status_code == 422
