from __future__ import annotations

import json
from pathlib import Path

from constellation_control.application.run import load_scenario
from constellation_control.application.run_duration import run_scenario_with_duration


def test_duration_override_uses_existing_pipeline_and_persists_effective_scenario(tmp_path: Path) -> None:
    scenario_path = Path(__file__).parents[1] / "scenarios" / "mvp_45deg.yaml"
    source_text = scenario_path.read_text(encoding="utf-8")
    source = load_scenario(scenario_path)

    result = run_scenario_with_duration(
        scenario_path,
        tmp_path,
        preset="custom",
        custom_duration_s=21600.0,
    )

    assert result.duration_s == 21600.0
    assert result.output_step_s == source.output_step_s
    assert result.predicted_sample_count == 13
    assert scenario_path.read_text(encoding="utf-8") == source_text

    normalized = json.loads((result.run_dir / "scenario.normalized.json").read_text(encoding="utf-8"))
    manifest = json.loads((result.run_dir / "manifest.json").read_text(encoding="utf-8"))
    timeseries = (result.run_dir / "timeseries.csv").read_text(encoding="utf-8")

    assert normalized["duration_s"] == 21600.0
    assert normalized["output_step_s"] == source.output_step_s
    assert normalized["force_model"] == source.force_model.model_dump(mode="json")
    assert normalized["integrator"] == source.integrator.model_dump(mode="json")
    assert manifest["force_model_fingerprint"] == source.force_model.fingerprint()
    assert timeseries


def test_scenario_duration_path_keeps_original_effective_duration(tmp_path: Path) -> None:
    scenario_path = Path(__file__).parents[1] / "scenarios" / "mvp_45deg.yaml"
    source = load_scenario(scenario_path)

    result = run_scenario_with_duration(scenario_path, tmp_path, preset="scenario")

    assert result.duration_s == source.duration_s
    assert result.output_step_s == source.output_step_s
    assert result.predicted_sample_count == 97
