import json
from pathlib import Path

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
    )
    for name in required:
        path = run_dir / name
        assert path.exists(), name
        assert path.stat().st_size > 0, name

    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
    assert manifest["force_model_mode"] == "screening"
    assert summary["mean_element_rule"] == (
        "all secular drift metrics use force-model-consistent mean elements; osculating a is excluded"
    )
