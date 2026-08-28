from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory

import yaml

from constellation_control.application.run import load_scenario, run_scenario
from constellation_control.preview.duration import (
    effective_scenario_with_duration,
    predicted_output_sample_count,
    resolve_duration_s,
)


@dataclass(frozen=True)
class DurationRunResult:
    run_dir: Path
    duration_s: float
    output_step_s: float
    predicted_sample_count: int
    preset: str


def run_scenario_with_duration(
    scenario_path: Path,
    output_root: Path,
    *,
    preset: str | None = "scenario",
    custom_duration_s: float | None = None,
) -> DurationRunResult:
    """Execute the existing scenario pipeline with a validated duration-only override."""

    source = load_scenario(scenario_path)
    duration_s = resolve_duration_s(
        preset,
        custom_duration_s,
        scenario_duration_s=source.duration_s,
    )
    effective = effective_scenario_with_duration(source, duration_s)
    sample_count = predicted_output_sample_count(effective.duration_s, effective.output_step_s)
    resolved_preset = "scenario" if preset is None else preset

    if effective.duration_s == source.duration_s and resolved_preset == "scenario":
        run_dir = run_scenario(scenario_path, output_root)
    else:
        with TemporaryDirectory(prefix="oc-gnss-effective-scenario-") as temporary:
            effective_path = Path(temporary) / scenario_path.name
            effective_path.write_text(
                yaml.safe_dump(
                    effective.model_dump(mode="json"),
                    sort_keys=False,
                    allow_unicode=True,
                ),
                encoding="utf-8",
            )
            run_dir = run_scenario(effective_path, output_root)

    return DurationRunResult(
        run_dir=run_dir,
        duration_s=effective.duration_s,
        output_step_s=effective.output_step_s,
        predicted_sample_count=sample_count,
        preset=resolved_preset,
    )
