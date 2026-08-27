from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from constellation_control.control.policies import CorrectionPolicy
from constellation_control.preview.closed_loop import PreviewClosedLoopProfile
from constellation_control.preview.http_app import create_preview_app


def _repo_root() -> Path:
    return Path(__file__).parents[1]


def _profile(policy: CorrectionPolicy) -> PreviewClosedLoopProfile:
    return PreviewClosedLoopProfile(
        policy=policy,
        campaign_horizon_s=3600.0,
        coast_horizon_s=600.0,
        coast_output_step_s=60.0,
        max_corrections=3,
        authority_times_s=(0.0, 60.0, 120.0),
        maneuver_windows=(True, True),
        max_abs_impulse_rtn_m_s=(0.2, 0.2, 0.2),
        min_impulse_bit_m_s=1.0e-3,
        trust_tolerances_roe=(1.0e-6, 1.0e-3, 1.0e-6, 1.0e-6, 1.0e-6, 1.0e-6),
        target_roe=(0.0, 0.0, 0.0, 0.0, 0.0, 0.0),
        w_tracking=10.0,
        w_max=0.5,
    )


def test_closed_loop_http_no_control_returns_exact_accepted_evidence(tmp_path: Path) -> None:
    app = create_preview_app(_repo_root() / "scenarios", tmp_path)
    client = TestClient(app)
    profile = _profile(CorrectionPolicy.NO_CONTROL)

    response = client.post(
        "/api/closed-loop-runs",
        json={
            "scenario_name": "mvp_45deg.yaml",
            "profile": profile.model_dump(mode="json"),
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["campaign"]["policy"] == CorrectionPolicy.NO_CONTROL.value
    assert payload["campaign"]["termination_reason"] == "no-control-policy"
    assert payload["campaign"]["correction_count"] == 0
    assert payload["campaign"]["authority_attempt_count"] == 0
    assert payload["corrections"] == []

    run_dir = Path(payload["run_dir"])
    persisted_metrics = json.loads(
        (run_dir / "closed_loop_metrics.json").read_text(encoding="utf-8")
    )
    persisted_corrections = json.loads(
        (run_dir / "closed_loop_corrections.json").read_text(encoding="utf-8")
    )
    assert payload["metrics"] == persisted_metrics
    assert payload["corrections"] == persisted_corrections
    assert payload["metrics"]["annualized"]["available"] is False
    assert payload["metrics"]["annualized"]["projected_years_to_reserve"] is None

    for name in (
        "closed_loop_profile.json",
        "closed_loop_campaign.json",
        "closed_loop_metrics.json",
        "closed_loop_corrections.json",
        "closed_loop_corrections.csv",
        "closed_loop_corrections.parquet",
        "report.md",
        "report.html",
    ):
        artifact = client.get(payload["artifacts"][name])
        assert artifact.status_code == 200
        assert artifact.content or name in {"closed_loop_corrections.csv", "closed_loop_corrections.parquet"}


def test_closed_loop_http_correction_on_screening_fails_closed(tmp_path: Path) -> None:
    app = create_preview_app(_repo_root() / "scenarios", tmp_path)
    client = TestClient(app)

    response = client.post(
        "/api/closed-loop-runs",
        json={
            "scenario_name": "mvp_45deg.yaml",
            "profile": _profile(CorrectionPolicy.BOUNDARY_TO_BOUNDARY).model_dump(mode="json"),
        },
    )
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert "VALIDATION force mode" in detail
    assert "Корректирующая политика" in detail
    assert not list(tmp_path.rglob("closed_loop_campaign.json"))


def test_closed_loop_artifact_route_is_allowlisted_and_path_safe(tmp_path: Path) -> None:
    app = create_preview_app(_repo_root() / "scenarios", tmp_path)
    client = TestClient(app)
    response = client.post(
        "/api/closed-loop-runs",
        json={
            "scenario_name": "mvp_45deg.yaml",
            "profile": _profile(CorrectionPolicy.NO_CONTROL).model_dump(mode="json"),
        },
    )
    assert response.status_code == 200
    payload = response.json()
    report_url = payload["artifacts"]["report.html"]
    prefix = report_url.rsplit("/", 1)[0]

    blocked = client.get(prefix + "/scenario.normalized.json")
    assert blocked.status_code == 404
    escaped = client.get(prefix.replace("/closed-loop-", "/../closed-loop-") + "/report.html")
    assert escaped.status_code in {404, 422}


def test_existing_preview_http_surface_remains_available(tmp_path: Path) -> None:
    app = create_preview_app(_repo_root() / "scenarios", tmp_path)
    client = TestClient(app)
    assert client.get("/health").status_code == 200
    assert client.get("/api/scenarios").status_code == 200
    scenario = client.get("/api/scenarios/mvp_45deg.yaml")
    assert scenario.status_code == 200
    assert scenario.json()["scenario_id"]
