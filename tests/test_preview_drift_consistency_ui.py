from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from constellation_control.preview.consolidated_release_app import create_preview_app, render_preview_page_for_test


def _write_drift_evidence(output_root: Path) -> tuple[str, str]:
    scenario_id = "glo-drift-test"
    run_id = "11111111-2222-3333-4444-555555555555"
    run_dir = output_root / scenario_id / run_id
    run_dir.mkdir(parents=True)
    rows = [
        {
            "pair_id": "GLO-17/GLO-01",
            "reference_initial_a_mean_m": 25510000.0,
            "deputy_initial_a_mean_m": 25510001.6,
            "reference_time_mean_a_mean_m": 25510000.2,
            "deputy_time_mean_a_mean_m": 25510001.7,
            "reference_initial_kepler_period_s": 40544.0,
            "deputy_initial_kepler_period_s": 40544.0038,
            "initial_period_difference_s": 0.0038,
            "reference_time_mean_kepler_period_s": 40544.0005,
            "deputy_time_mean_kepler_period_s": 40544.0041,
            "time_mean_period_difference_s": 0.0036,
            "initial_kepler_delta_n_rad_s": -5.37e-11,
            "initial_kepler_delta_n_deg_day": -0.0002658,
            "time_mean_kepler_delta_n_rad_s": -5.04e-11,
            "time_mean_kepler_delta_n_deg_day": -0.0002495,
            "measured_delta_lambda_rate_rad_s": -1.02e-10,
            "measured_delta_lambda_rate_deg_day": -0.000505,
            "measured_delta_u_rate_rad_s": -9.8e-11,
            "measured_delta_u_rate_deg_day": -0.000485,
            "delta_lambda_minus_kepler_rad_s": -5.16e-11,
            "delta_lambda_minus_kepler_deg_day": -0.0002555,
            "delta_u_minus_kepler_rad_s": -4.76e-11,
            "delta_u_minus_kepler_deg_day": -0.0002355,
            "semantics": "central-field baseline only",
        }
    ]
    (run_dir / "kepler_drift_consistency.json").write_text(json.dumps(rows), encoding="utf-8")
    (run_dir / "kepler_drift_consistency.html").write_text("<html>drift</html>", encoding="utf-8")
    return scenario_id, run_id


def test_packaged_page_contains_physical_drift_panel() -> None:
    page = render_preview_page_for_test()
    assert 'id="driftConsistencyCard"' in page
    assert 'id="driftPair"' in page
    assert "Kepler Δn time-mean, deg/day" in page
    assert "Measured Orekit Δλ, deg/day" in page
    assert "Measured Orekit Δu=λ−Ω, deg/day" in page
    assert "Δλ − Kepler, deg/day" in page
    assert "Δu − Kepler, deg/day" in page
    assert "/api/drift-consistency/" in page


def test_drift_consistency_endpoint_exposes_pair_chain(tmp_path: Path) -> None:
    output_root = tmp_path / "runs"
    scenario_id, run_id = _write_drift_evidence(output_root)
    app = create_preview_app(scenario_root=tmp_path / "scenarios", output_root=output_root)
    client = TestClient(app)

    response = client.get(f"/api/drift-consistency/{scenario_id}/{run_id}")
    assert response.status_code == 200
    payload = response.json()
    assert payload["rows"][0]["pair_id"] == "GLO-17/GLO-01"
    assert payload["rows"][0]["time_mean_kepler_delta_n_deg_day"] == -0.0002495
    assert payload["rows"][0]["delta_u_minus_kepler_deg_day"] == -0.0002355
    assert payload["report_url"].endswith("/kepler_drift_consistency.html")


def test_drift_consistency_endpoint_fails_closed_without_evidence(tmp_path: Path) -> None:
    app = create_preview_app(scenario_root=tmp_path / "scenarios", output_root=tmp_path / "runs")
    client = TestClient(app)
    response = client.get("/api/drift-consistency/missing/run")
    assert response.status_code == 422
    assert "not found" in response.json()["detail"]
