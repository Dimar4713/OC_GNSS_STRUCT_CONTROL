import json
from pathlib import Path

import pandas as pd

from constellation_control.application.run import run_scenario


def test_end_to_end_small_scenario(tmp_path: Path) -> None:
    scenario = Path(__file__).parents[1] / "scenarios" / "mvp_45deg.yaml"
    run_dir = run_scenario(scenario, tmp_path)

    required = (
        "manifest.json",
        "summary.json",
        "timeseries.csv",
        "timeseries.parquet",
        "ground_track.csv",
        "ground_track.parquet",
        "ground_track.json",
        "resources.csv",
        "resources.parquet",
        "resources.json",
        "report.md",
        "report.html",
        "01_delta_lambda.png",
        "02_delta_a_mean.png",
        "03_eccentricity_vector.png",
        "04_inclination_vector.png",
        "05_minimum_distance.png",
        "06_delta_raan.png",
        "07_ground_track.png",
        "09_maneuver_delta_v.png",
        "10_propellant_reserve.png",
        "11_delta_u_mean.png",
        "12_along_track_mean_arc_proxy.png",
        "13_delta_u_rate.png",
        "14_along_track_proxy_rate.png",
        "15_delta_u_periodic.png",
        "interactive_delta_u_mean.html",
    )
    for name in required:
        path = run_dir / name
        assert path.exists(), name
        assert path.stat().st_size > 0, name

    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
    report = (run_dir / "report.md").read_text(encoding="utf-8")
    timeseries = pd.read_csv(run_dir / "timeseries.csv")
    ground_track = json.loads((run_dir / "ground_track.json").read_text(encoding="utf-8"))
    resources = json.loads((run_dir / "resources.json").read_text(encoding="utf-8"))

    assert manifest["force_model_mode"] == "screening"
    assert manifest["algorithm_versions"]["relative_mean_phase"] == "u-mean-lambda-minus-raan-v1"
    assert manifest["algorithm_versions"]["phase_corridor_forecast"] == "linear-secular-rate-v1"
    assert manifest["algorithm_versions"]["kepler_relative_drift_consistency"] == "mean-a-central-field-v1"
    assert ground_track
    assert resources
    assert summary["relative_operations"]
    assert summary["kepler_drift_consistency"]

    first_relative = summary["relative_operations"][0]
    assert first_relative["phase_coordinate"] == "u_mean=lambda-Omega"
    assert "not osculating argument of latitude" in first_relative["phase_semantics"]
    assert "not Cartesian separation" in first_relative["along_track_semantics"]

    corridor = first_relative["phase_corridor"]
    assert corridor["half_width_rad"] == summary["constraints"]["phase_corridor_rad"]
    assert corridor["time_to_boundary_s"] is None or corridor["time_to_boundary_s"] >= 0.0

    kepler = first_relative["kepler_drift_consistency"]
    assert kepler["authority"] == "independent-central-field-consistency-diagnostic-v1"
    assert kepler["osculating_a_used"] is False
    assert "force-model-consistent mean semi-major-axis" in kepler["source_elements"]
    assert "central-field baseline" in kepler["interpretation"]
    assert kepler["mu_m3_s2"] > 0.0
    assert kepler["reference_initial_a_mean_m"] > 0.0
    assert kepler["deputy_initial_a_mean_m"] > 0.0
    assert kepler["reference_time_mean_a_mean_m"] > 0.0
    assert kepler["deputy_time_mean_a_mean_m"] > 0.0
    assert kepler["reference_initial_kepler_period_s"] > 0.0
    assert kepler["deputy_initial_kepler_period_s"] > 0.0
    assert (
        kepler["delta_lambda_minus_kepler_residual_rad_s"]
        == kepler["measured_harmonic_delta_lambda_rad_s"] - kepler["time_mean_kepler_delta_n_rad_s"]
    )
    assert (
        kepler["delta_u_minus_kepler_residual_rad_s"]
        == kepler["measured_harmonic_delta_u_rad_s"] - kepler["time_mean_kepler_delta_n_rad_s"]
    )
    assert summary["kepler_drift_consistency"][0]["pair_id"] == first_relative["pair_id"]

    periodic = first_relative["periodic_delta_u"]
    assert "root-sum-square of fitted component amplitudes" in periodic["rss_semantics"]
    assert "no single period" in periodic["rss_semantics"]
    assert len(periodic["components"]) == 4
    assert [item["basis"] for item in periodic["components"]] == [
        "orbital",
        "sidereal_day",
        "lunar",
        "sidereal_year",
    ]
    for component in periodic["components"]:
        assert component["period_s"] > 0.0
        assert component["amplitude_rad"] >= 0.0
        assert component["peak_to_peak_rad"] == 2.0 * component["amplitude_rad"]
        assert component["peak_to_peak_deg"] == 2.0 * component["amplitude_deg"]

    assert {
        "delta_u_mean_rad",
        "delta_u_mean_deg",
        "delta_u_trend_rad",
        "delta_u_harmonic_deg",
        "secular_delta_u_rate_deg_day",
        "secular_along_track_proxy_rate_m_s",
        "phase_corridor_upper_deg",
        "phase_corridor_lower_deg",
        "along_track_mean_arc_proxy_m",
        "reference_a_mean_m",
        "deputy_a_mean_m",
        "reference_kepler_period_s",
        "deputy_kepler_period_s",
        "kepler_period_difference_s",
        "reference_kepler_mean_motion_rad_s",
        "deputy_kepler_mean_motion_rad_s",
        "kepler_delta_n_rad_s",
        "kepler_delta_n_deg_day",
        "measured_harmonic_delta_lambda_rad_s",
        "measured_harmonic_delta_lambda_deg_day",
        "measured_harmonic_delta_u_rad_s",
        "measured_harmonic_delta_u_deg_day",
        "delta_lambda_minus_kepler_residual_rad_s",
        "delta_lambda_minus_kepler_residual_deg_day",
        "delta_u_minus_kepler_residual_rad_s",
        "delta_u_minus_kepler_residual_deg_day",
    }.issubset(timeseries.columns)

    assert report.index("## Operational relative diagnostics") < report.index("## Secondary diagnostics")
    assert "Amplitude means center-to-peak" in report
    assert "Peak-to-peak is exactly 2 x amplitude" in report
    assert "multi-frequency aggregate, no single period" in report
    assert "Kepler Delta n is a central-field baseline" in report
    assert "Pair distance, navigation DOP and ground-track closure are retained as secondary evidence" in report

    assert summary["mean_element_rule"] == (
        "all secular drift metrics use force-model-consistent mean elements; osculating a is excluded"
    )
