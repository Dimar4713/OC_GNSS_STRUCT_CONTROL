from __future__ import annotations

from math import ceil, isfinite

from constellation_control.domain.models import ScenarioConfig

JULIAN_YEAR_S = 365.25 * 86400.0

DURATION_PRESETS_S: dict[str, float] = {
    "1d": 1.0 * 86400.0,
    "8d": 8.0 * 86400.0,
    "30d": 30.0 * 86400.0,
    "90d": 90.0 * 86400.0,
    "1y": JULIAN_YEAR_S,
    "5y": 5.0 * JULIAN_YEAR_S,
}


def resolve_duration_s(
    preset: str | None,
    custom_duration_s: float | None,
    *,
    scenario_duration_s: float,
) -> float:
    """Resolve an operator-selected propagation horizon without changing any other scenario setting."""

    if preset in (None, "scenario"):
        if custom_duration_s is not None:
            raise ValueError("custom_duration_s requires preset='custom'")
        return float(scenario_duration_s)
    if preset == "custom":
        if custom_duration_s is None:
            raise ValueError("custom duration is required")
        duration = float(custom_duration_s)
        if not isfinite(duration) or duration <= 0.0:
            raise ValueError("custom duration must be finite and positive")
        return duration
    if custom_duration_s is not None:
        raise ValueError("custom_duration_s is only valid with preset='custom'")
    try:
        return DURATION_PRESETS_S[preset]
    except KeyError as exc:
        raise ValueError(f"unknown duration preset: {preset}") from exc


def effective_scenario_with_duration(scenario: ScenarioConfig, duration_s: float) -> ScenarioConfig:
    """Return a fully revalidated scenario differing only in duration_s.

    Full model validation is intentional: shortened horizons must reject configured
    maneuvers whose epochs would fall outside the effective run duration.
    """

    duration = float(duration_s)
    if not isfinite(duration) or duration <= 0.0:
        raise ValueError("duration_s must be finite and positive")
    payload = scenario.model_dump(mode="python")
    payload["duration_s"] = duration
    return ScenarioConfig.model_validate(payload)


def predicted_output_sample_count(duration_s: float, output_step_s: float) -> int:
    """Match the current propagation-grid contract including an exact final sample."""

    duration = float(duration_s)
    step = float(output_step_s)
    if not isfinite(duration) or duration <= 0.0:
        raise ValueError("duration_s must be finite and positive")
    if not isfinite(step) or step <= 0.0:
        raise ValueError("output_step_s must be finite and positive")
    return int(ceil(duration / step)) + 1
