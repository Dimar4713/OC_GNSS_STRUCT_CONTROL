from pathlib import Path

from constellation_control.application.run import run_scenario


def test_end_to_end_small_scenario(tmp_path: Path) -> None:
    scenario = Path(__file__).parents[1] / "scenarios" / "mvp_45deg.yaml"
    run_dir = run_scenario(scenario, tmp_path)
    assert (run_dir / "manifest.json").exists()
    assert (run_dir / "summary.json").exists()
    assert (run_dir / "timeseries.csv").exists()
    assert (run_dir / "timeseries.parquet").exists()
    assert (run_dir / "report.md").exists()
    assert (run_dir / "01_delta_lambda.png").exists()
