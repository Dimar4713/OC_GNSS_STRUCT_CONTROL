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
        "interactive_delta_u_mean.html",
    )
    for name in required:
        path = run_dir / name
        assert path.exists(), name
        assert path.stat().st_size > 0, name

    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
    timeseries = pd.read_csv(run_dir / "timeseries.csv")
    ground_track = json.loads((run_dir / "ground_track.json").read_text(encoding="utf-8"))
    resources = json.loads((run_dir / "resources.json").read_text(encoding="utf-8"))
    assert manifest["force_model_mode"] == "screening"
    assert manifest["algorithm_versions"]["relative_mean_phase"] == "u-mean-lambda-minus-raan-v1"
    assert ground_track
    assert resources
    assert summary["relative_operations"]
    first_relative = summary["relative_operations"][0]
    assert first_relative["phase_coordinate"] == "u_mean=lambda-Omega"
    assert "not osculating argument of latitude" in first_relative["phase_semantics"]
    assert "not Cartesian separation" in first_relative["along_track_semantics"]
    assert {
        "delta_u_mean_rad",
        "delta_u_mean_deg",
        "along_track_mean_arc_proxy_m",
    }.issubset(timeseries.columns)
    assert summary["mean_element_rule"] == (
        "all secular drift metrics use force-model-consistent mean elements; osculating a is excluded"
    )
