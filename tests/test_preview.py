from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from constellation_control.application.run import load_scenario
from constellation_control.preview.app import (
    _safe_result_file,
    _safe_scenario_path,
    authority_preflight,
    create_preview_app,
    list_preview_scenarios,
    preview_catalog,
    render_preview_page_for_test,
    scenario_preview_payload,
)


def _repo_root() -> Path:
    return Path(__file__).parents[1]


def test_preview_lists_only_runnable_scenarios_and_exposes_explicit_authority() -> None:
    scenario_root = _repo_root() / "scenarios"
    names = list_preview_scenarios(scenario_root)
    assert "mvp_45deg.yaml" in names
    assert "design_pipeline_screening_smoke.yaml" in names
    assert "design_pipeline_validation_smoke.yaml" in names
    assert "design_pipeline_smoke.yaml" not in names
    assert "robustness_campaign_smoke.yaml" not in names

    catalog = preview_catalog(scenario_root)
    other = {item["name"]: item for item in catalog["other_inputs"]}
    assert other["design_pipeline_smoke.yaml"]["kind"] == "design_pipeline_config"
    assert other["robustness_campaign_smoke.yaml"]["kind"] == "robustness_campaign_config"

    payload = scenario_preview_payload(scenario_root, "mvp_45deg.yaml")
    assert payload["force_mode"] == "screening"
    assert payload["authority"] == "SCREENING — analytical/synthetic mean-element authority"
    assert payload["satellites"]
    assert payload["yaml_text"]
    assert "osculating semi-major axis is not a secular control criterion" in payload["mean_element_rule"]


def test_non_scenario_yaml_returns_domain_message_not_pydantic_field_spam() -> None:
    app = create_preview_app(_repo_root() / "scenarios", _repo_root() / ".preview-test-unused")
    client = TestClient(app)
    response = client.get("/api/scenarios/design_pipeline_smoke.yaml")
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert "design_pipeline_config" in detail
    assert "Design pipeline configuration" in detail
    assert "11 validation errors" not in detail
    assert "scenario_id Field required" not in detail


def test_screening_preflight_is_ready_without_orekit() -> None:
    scenario = load_scenario(_repo_root() / "scenarios" / "mvp_45deg.yaml")
    result = authority_preflight(scenario)
    assert result["ready"] is True
    assert result["authority"] == "SCREENING — analytical/synthetic mean-element authority"
    assert "does not require the Orekit sidecar" in str(result["reason"])


def test_high_fidelity_preflight_fails_closed_without_sidecar_url() -> None:
    scenario = load_scenario(_repo_root() / "scenarios" / "orekit_validation_smoke.yaml")
    without_sidecar = scenario.model_copy(update={"orekit_sidecar_url": None})
    result = authority_preflight(without_sidecar)
    assert result["ready"] is False
    assert result["authority"] == "VALIDATION — Orekit numerical authority required"
    assert result["reason"] == "orekit_sidecar_url is not configured"


def test_preview_http_shell_runs_screening_and_serves_report(tmp_path: Path) -> None:
    app = create_preview_app(_repo_root() / "scenarios", tmp_path)
    client = TestClient(app)

    health = client.get("/health")
    assert health.status_code == 200
    assert health.json() == {"status": "ok", "preview": "0.1"}

    catalog = client.get("/api/scenarios")
    assert catalog.status_code == 200
    assert "design_pipeline_smoke.yaml" not in catalog.json()["scenarios"]

    preflight = client.get("/api/preflight/mvp_45deg.yaml")
    assert preflight.status_code == 200
    assert preflight.json()["ready"] is True

    response = client.post("/api/runs", json={"scenario_name": "mvp_45deg.yaml"})
    assert response.status_code == 200
    payload = response.json()
    run_dir = Path(payload["run_dir"])
    assert run_dir.is_dir()
    assert (run_dir / "manifest.json").is_file()
    assert (run_dir / "report.html").is_file()

    report = client.get(payload["report_url"])
    assert report.status_code == 200
    assert "Constellation Control run" in report.text


def test_preview_rejects_path_escape_and_non_yaml_inputs(tmp_path: Path) -> None:
    (tmp_path / "valid.yaml").write_text("scenario_id: placeholder\n", encoding="utf-8")
    with pytest.raises(ValueError, match="without path components"):
        _safe_scenario_path(tmp_path, "../valid.yaml")
    with pytest.raises(ValueError, match="must end with"):
        _safe_scenario_path(tmp_path, "valid.txt")


def test_preview_result_access_stays_inside_output_root(tmp_path: Path) -> None:
    report = tmp_path / "scenario" / "run" / "report.html"
    report.parent.mkdir(parents=True)
    report.write_text("ok", encoding="utf-8")
    assert _safe_result_file(tmp_path, "scenario", "run", "report.html") == report.resolve()

    with pytest.raises(ValueError, match="invalid components"):
        _safe_result_file(tmp_path, "../scenario", "run", "report.html")
    with pytest.raises(ValueError, match="invalid components"):
        _safe_result_file(tmp_path, "..", "run", "report.html")


def test_preview_page_contains_expert_authority_report_and_other_input_surfaces() -> None:
    page = render_preview_page_for_test()
    assert "OC GNSS STRUCT CONTROL — Engineering Preview 0.1" in page
    assert "Expert / YAML" in page
    assert "Authority" in page
    assert "Run selected scenario" in page
    assert "Open engineering report" in page
    assert "Other YAML inputs" in page
