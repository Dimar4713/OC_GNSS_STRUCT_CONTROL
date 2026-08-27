from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

import constellation_control.preview.workflow_app as workflow_app


def _repo_root() -> Path:
    return Path(__file__).parents[1]


def _fake_output(output_root: Path, group: str, run_id: str, artifacts: tuple[str, ...]) -> Path:
    run_dir = output_root / group / run_id
    run_dir.mkdir(parents=True)
    for name in artifacts:
        (run_dir / name).write_text("{}" if name.endswith(".json") else "ok", encoding="utf-8")
    return run_dir


def test_design_endpoint_routes_exact_inputs_to_existing_application(monkeypatch, tmp_path: Path) -> None:
    calls: list[tuple[Path, Path, Path, Path]] = []

    def fake_design(screening: Path, validation: Path, pipeline: Path, output: Path) -> Path:
        calls.append((screening, validation, pipeline, output))
        return _fake_output(
            output,
            "design-pipeline-smoke--design",
            "fake-design",
            ("report.html", "report.md", "pipeline_manifest.json", "recommendation.json"),
        )

    monkeypatch.setattr(workflow_app, "run_design_application", fake_design)
    app = workflow_app.create_preview_app(_repo_root() / "scenarios", tmp_path)
    client = TestClient(app)
    response = client.post(
        "/api/design-runs",
        json={
            "screening_scenario_name": "design_pipeline_screening_smoke.yaml",
            "validation_scenario_name": "design_pipeline_validation_smoke.yaml",
            "pipeline_config_name": "design_pipeline_smoke.yaml",
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["workflow"] == "design"
    assert "orekit-numerical" in payload["authority"]
    assert len(calls) == 1
    screening, validation, pipeline, output = calls[0]
    assert screening.name == "design_pipeline_screening_smoke.yaml"
    assert validation.name == "design_pipeline_validation_smoke.yaml"
    assert pipeline.name == "design_pipeline_smoke.yaml"
    assert output == tmp_path
    assert client.get(payload["artifacts"]["report.html"]).status_code == 200
    assert client.get(payload["artifacts"]["pipeline_manifest.json"]).status_code == 200


def test_robustness_endpoint_routes_exact_inputs_to_existing_application(monkeypatch, tmp_path: Path) -> None:
    calls: list[tuple[Path, Path, Path]] = []

    def fake_robustness(validation: Path, campaign: Path, output: Path) -> Path:
        calls.append((validation, campaign, output))
        return _fake_output(
            output,
            "orekit-validation-smoke--robustness",
            "fake-robustness",
            ("report.html", "report.md", "campaign_manifest.json", "summary.json"),
        )

    monkeypatch.setattr(workflow_app, "run_robustness_application", fake_robustness)
    app = workflow_app.create_preview_app(_repo_root() / "scenarios", tmp_path)
    client = TestClient(app)
    response = client.post(
        "/api/robustness-runs",
        json={
            "validation_scenario_name": "orekit_validation_smoke.yaml",
            "campaign_config_name": "robustness_campaign_smoke.yaml",
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["workflow"] == "robustness"
    assert payload["authority"] == "orekit-numerical robustness campaign"
    assert len(calls) == 1
    validation, campaign, output = calls[0]
    assert validation.name == "orekit_validation_smoke.yaml"
    assert campaign.name == "robustness_campaign_smoke.yaml"
    assert output == tmp_path
    assert client.get(payload["artifacts"]["report.html"]).status_code == 200
    assert client.get(payload["artifacts"]["summary.json"]).status_code == 200


def test_wrong_workflow_config_kind_fails_before_application(monkeypatch, tmp_path: Path) -> None:
    called = False

    def forbidden(*args: object, **kwargs: object) -> Path:
        nonlocal called
        called = True
        raise AssertionError("application runner must not be called")

    monkeypatch.setattr(workflow_app, "run_design_application", forbidden)
    app = workflow_app.create_preview_app(_repo_root() / "scenarios", tmp_path)
    client = TestClient(app)
    response = client.post(
        "/api/design-runs",
        json={
            "screening_scenario_name": "design_pipeline_screening_smoke.yaml",
            "validation_scenario_name": "design_pipeline_validation_smoke.yaml",
            "pipeline_config_name": "robustness_campaign_smoke.yaml",
        },
    )
    assert response.status_code == 422
    assert "wrong input kind" in response.json()["detail"]
    assert called is False


def test_wrong_scenario_authority_fails_before_application(monkeypatch, tmp_path: Path) -> None:
    called = False

    def forbidden(*args: object, **kwargs: object) -> Path:
        nonlocal called
        called = True
        raise AssertionError("application runner must not be called")

    monkeypatch.setattr(workflow_app, "run_robustness_application", forbidden)
    app = workflow_app.create_preview_app(_repo_root() / "scenarios", tmp_path)
    client = TestClient(app)
    response = client.post(
        "/api/robustness-runs",
        json={
            "validation_scenario_name": "mvp_45deg.yaml",
            "campaign_config_name": "robustness_campaign_smoke.yaml",
        },
    )
    assert response.status_code == 422
    assert "VALIDATION force mode" in response.json()["detail"]
    assert called is False


def test_workflow_page_is_bilingual_and_catalog_driven(tmp_path: Path) -> None:
    app = workflow_app.create_preview_app(_repo_root() / "scenarios", tmp_path)
    client = TestClient(app)
    assert client.get("/health").json() == {"status": "ok", "preview": "0.1.6"}
    page = client.get("/").text
    assert "Engineering Preview 0.1.6" in page
    assert "Design / Robustness workflows — Проектирование / Робастность" in page
    assert "run_design_application" not in page
    assert "catalog.other_inputs" in page
    assert "design_pipeline_config" in page
    assert "robustness_campaign_config" in page
    assert "Existing authoritative application workflows" in page
