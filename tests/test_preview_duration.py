from __future__ import annotations

from math import inf, nan
from pathlib import Path

import pytest
from pydantic import ValidationError

from constellation_control.application.run import load_scenario
from constellation_control.domain.models import Maneuver, ScenarioConfig
from constellation_control.preview.duration import (
    DURATION_PRESETS_S,
    effective_scenario_with_duration,
    predicted_output_sample_count,
    resolve_duration_s,
)


def _scenario() -> ScenarioConfig:
    return load_scenario(Path(__file__).parents[1] / "scenarios" / "mvp_45deg.yaml")


@pytest.mark.parametrize(
    ("preset", "expected_s"),
    [
        ("1d", 86400.0),
        ("8d", 691200.0),
        ("30d", 2592000.0),
        ("90d", 7776000.0),
        ("1y", 31557600.0),
        ("5y", 157788000.0),
    ],
)
def test_duration_presets_have_explicit_seconds(preset: str, expected_s: float) -> None:
    assert DURATION_PRESETS_S[preset] == expected_s
    assert resolve_duration_s(preset, None, scenario_duration_s=123.0) == expected_s


def test_scenario_duration_selection_preserves_declared_horizon() -> None:
    assert resolve_duration_s("scenario", None, scenario_duration_s=172800.0) == 172800.0
    assert resolve_duration_s(None, None, scenario_duration_s=172800.0) == 172800.0


def test_custom_duration_requires_positive_finite_value() -> None:
    assert resolve_duration_s("custom", 12345.0, scenario_duration_s=1.0) == 12345.0
    for value in (0.0, -1.0, inf, nan):
        with pytest.raises(ValueError, match="finite and positive"):
            resolve_duration_s("custom", value, scenario_duration_s=1.0)
    with pytest.raises(ValueError, match="required"):
        resolve_duration_s("custom", None, scenario_duration_s=1.0)
    with pytest.raises(ValueError, match="unknown duration preset"):
        resolve_duration_s("2y", None, scenario_duration_s=1.0)


def test_effective_duration_changes_only_duration_and_revalidates() -> None:
    source = _scenario()
    effective = effective_scenario_with_duration(source, 90.0 * 86400.0)

    assert effective.duration_s == 90.0 * 86400.0
    assert source.duration_s == 172800.0
    assert effective.force_model == source.force_model
    assert effective.force_model.mode == source.force_model.mode
    assert effective.force_model.fingerprint() == source.force_model.fingerprint()
    assert effective.integrator == source.integrator
    assert effective.output_step_s == source.output_step_s
    assert effective.epoch == source.epoch
    assert effective.frame == source.frame
    assert effective.time_scale == source.time_scale
    assert effective.constellation == source.constellation
    assert effective.maneuvers == source.maneuvers


def test_shortening_horizon_rejects_maneuver_outside_effective_duration() -> None:
    source = _scenario()
    payload = source.model_dump(mode="python")
    payload["maneuvers"] = (
        Maneuver(satellite_id="DEMO-ADD-45", time_s=100000.0, dv_rtn_m_s=(0.0, 0.01, 0.0)),
    )
    with_maneuver = ScenarioConfig.model_validate(payload)

    with pytest.raises(ValidationError, match="maneuver time_s must lie inside scenario duration"):
        effective_scenario_with_duration(with_maneuver, 86400.0)


def test_predicted_sample_count_matches_exact_final_sample_contract() -> None:
    assert predicted_output_sample_count(7200.0, 1800.0) == 5
    assert predicted_output_sample_count(7201.0, 1800.0) == 6
    assert predicted_output_sample_count(1799.0, 1800.0) == 2
    for duration, step in ((0.0, 1.0), (inf, 1.0), (1.0, 0.0), (1.0, nan)):
        with pytest.raises(ValueError, match="finite and positive"):
            predicted_output_sample_count(duration, step)
