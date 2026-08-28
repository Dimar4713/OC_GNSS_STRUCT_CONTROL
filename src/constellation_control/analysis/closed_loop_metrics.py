from __future__ import annotations

from statistics import mean, median

from pydantic import BaseModel, ConfigDict, Field

from constellation_control.control.campaign import ClosedLoopCampaignResult

DAY_S = 86_400.0
JULIAN_YEAR_S = 365.25 * DAY_S


class ScalarDistribution(BaseModel):
    model_config = ConfigDict(frozen=True)

    count: int = Field(ge=0)
    minimum: float | None
    median: float | None
    mean: float | None
    maximum: float | None


class CorrectionIntervalMetrics(BaseModel):
    model_config = ConfigDict(frozen=True)

    seconds: ScalarDistribution
    hours: ScalarDistribution
    days: ScalarDistribution


class AnnualizedOperationsMetrics(BaseModel):
    model_config = ConfigDict(frozen=True)

    available: bool
    unavailable_reason: str | None
    evidence_correction_count: int = Field(ge=0)
    evidence_span_s: float = Field(ge=0.0)
    evidence_span_days: float = Field(ge=0.0)
    delta_v_m_s_per_day: float | None
    delta_v_m_s_per_julian_year: float | None
    propellant_kg_per_day: float | None
    propellant_kg_per_julian_year: float | None
    corrections_per_julian_year: float | None
    lifetime_projection_available: bool
    lifetime_projection_reason: str | None
    usable_propellant_above_reserve_kg: float = Field(ge=0.0)
    projected_years_to_reserve: float | None
    projected_remaining_corrections_to_reserve: float | None


class ClosedLoopOperationalMetrics(BaseModel):
    model_config = ConfigDict(frozen=True)

    policy: str
    corridor_half_width_rad: float = Field(gt=0.0)
    correction_count: int = Field(ge=0)
    observed_elapsed_s: float = Field(ge=0.0)
    observed_elapsed_days: float = Field(ge=0.0)
    correction_intervals: CorrectionIntervalMetrics
    rearm_settling_intervals: CorrectionIntervalMetrics
    post_rearm_coast_intervals: CorrectionIntervalMetrics
    delta_v_per_correction_m_s: ScalarDistribution
    propellant_per_correction_kg: ScalarDistribution
    cumulative_delta_v_m_s: float = Field(ge=0.0)
    cumulative_propellant_used_kg: float = Field(ge=0.0)
    propellant_remaining_kg: float = Field(ge=0.0)
    required_reserve_kg: float = Field(ge=0.0)
    rearm_settling_available: bool
    rearm_settling_reason: str | None
    annualized: AnnualizedOperationsMetrics


def _distribution(values: tuple[float, ...]) -> ScalarDistribution:
    if not values:
        return ScalarDistribution(count=0, minimum=None, median=None, mean=None, maximum=None)
    return ScalarDistribution(
        count=len(values),
        minimum=min(values),
        median=float(median(values)),
        mean=float(mean(values)),
        maximum=max(values),
    )


def _scaled_distribution(values: tuple[float, ...], scale: float) -> ScalarDistribution:
    return _distribution(tuple(value / scale for value in values))


def _interval_metrics(values: tuple[float, ...]) -> CorrectionIntervalMetrics:
    return CorrectionIntervalMetrics(
        seconds=_distribution(values),
        hours=_scaled_distribution(values, 3600.0),
        days=_scaled_distribution(values, DAY_S),
    )


def _correction_intervals(campaign: ClosedLoopCampaignResult) -> tuple[float, ...]:
    times = tuple(record.event_time_s for record in campaign.resource_ledger)
    return tuple(right - left for left, right in zip(times, times[1:], strict=False))


def _rearm_intervals(
    campaign: ClosedLoopCampaignResult,
) -> tuple[tuple[float, ...], tuple[float, ...]]:
    correction_times = tuple(record.event_time_s for record in campaign.resource_ledger)
    rearm_times = tuple(
        record.elapsed_time_s
        for record in campaign.policy_trace
        if record.decision_reason == "rearmed_inside_corridor"
    )
    settling: list[float] = []
    post_rearm: list[float] = []
    rearm_cursor = 0
    for index, correction_time in enumerate(correction_times):
        next_correction = correction_times[index + 1] if index + 1 < len(correction_times) else None
        while rearm_cursor < len(rearm_times) and rearm_times[rearm_cursor] <= correction_time:
            rearm_cursor += 1
        if rearm_cursor >= len(rearm_times):
            break
        rearm_time = rearm_times[rearm_cursor]
        if next_correction is not None and rearm_time >= next_correction:
            continue
        settling.append(rearm_time - correction_time)
        if next_correction is not None:
            post_rearm.append(next_correction - rearm_time)
        rearm_cursor += 1
    return tuple(settling), tuple(post_rearm)


def analyze_closed_loop_operations(campaign: ClosedLoopCampaignResult) -> ClosedLoopOperationalMetrics:
    """Derive observed and explicitly-projected operations metrics without new propagation."""

    ledger = campaign.resource_ledger
    correction_count = len(ledger)
    intervals_s = _correction_intervals(campaign)
    settling_s, post_rearm_s = _rearm_intervals(campaign)
    delta_v_values = tuple(record.delta_v_m_s for record in ledger)
    propellant_values = tuple(record.propellant_used_kg for record in ledger)
    elapsed_s = float(campaign.elapsed_time_s)
    elapsed_days = elapsed_s / DAY_S
    remaining = float(campaign.controlled_propellant_remaining_kg)
    reserve = float(campaign.controlled_required_reserve_kg)
    usable = max(0.0, remaining - reserve)

    annualized_available = correction_count >= 2 and elapsed_s > 0.0
    unavailable_reason: str | None = None
    dv_day: float | None = None
    dv_year: float | None = None
    prop_day: float | None = None
    prop_year: float | None = None
    corrections_year: float | None = None
    lifetime_available = False
    lifetime_reason: str | None = None
    years_to_reserve: float | None = None
    corrections_to_reserve: float | None = None

    if not annualized_available:
        if correction_count < 2:
            unavailable_reason = "annualization-requires-at-least-two-authorized-corrections"
        else:
            unavailable_reason = "annualization-requires-positive-observed-span"
        lifetime_reason = unavailable_reason
    else:
        dv_rate_s = campaign.cumulative_delta_v_m_s / elapsed_s
        propellant_rate_s = campaign.cumulative_propellant_used_kg / elapsed_s
        correction_rate_s = correction_count / elapsed_s
        dv_day = dv_rate_s * DAY_S
        dv_year = dv_rate_s * JULIAN_YEAR_S
        prop_day = propellant_rate_s * DAY_S
        prop_year = propellant_rate_s * JULIAN_YEAR_S
        corrections_year = correction_rate_s * JULIAN_YEAR_S

        if usable <= 0.0:
            lifetime_reason = "no-usable-propellant-above-configured-reserve"
        elif prop_year is None or prop_year <= 0.0:
            lifetime_reason = "zero-observed-propellant-consumption-rate"
        else:
            lifetime_available = True
            years_to_reserve = usable / prop_year
            mean_propellant_per_correction = campaign.cumulative_propellant_used_kg / correction_count
            if mean_propellant_per_correction > 0.0:
                corrections_to_reserve = usable / mean_propellant_per_correction
            else:
                lifetime_available = False
                lifetime_reason = "zero-observed-propellant-per-correction"
                years_to_reserve = None

    settling_available = bool(settling_s)
    if settling_available:
        settling_reason = None
    elif not campaign.policy_trace:
        settling_reason = "campaign-evidence-has-no-policy-scan-trace"
    elif correction_count == 0:
        settling_reason = "no-authorized-corrections-to-match-with-rearm-events"
    else:
        settling_reason = "no-strict-inside-rearm-observed-after-authorized-correction"

    return ClosedLoopOperationalMetrics(
        policy=campaign.policy.value,
        corridor_half_width_rad=campaign.corridor_half_width_rad,
        correction_count=correction_count,
        observed_elapsed_s=elapsed_s,
        observed_elapsed_days=elapsed_days,
        correction_intervals=_interval_metrics(intervals_s),
        rearm_settling_intervals=_interval_metrics(settling_s),
        post_rearm_coast_intervals=_interval_metrics(post_rearm_s),
        delta_v_per_correction_m_s=_distribution(delta_v_values),
        propellant_per_correction_kg=_distribution(propellant_values),
        cumulative_delta_v_m_s=campaign.cumulative_delta_v_m_s,
        cumulative_propellant_used_kg=campaign.cumulative_propellant_used_kg,
        propellant_remaining_kg=remaining,
        required_reserve_kg=reserve,
        rearm_settling_available=settling_available,
        rearm_settling_reason=settling_reason,
        annualized=AnnualizedOperationsMetrics(
            available=annualized_available,
            unavailable_reason=unavailable_reason,
            evidence_correction_count=correction_count,
            evidence_span_s=elapsed_s,
            evidence_span_days=elapsed_days,
            delta_v_m_s_per_day=dv_day,
            delta_v_m_s_per_julian_year=dv_year,
            propellant_kg_per_day=prop_day,
            propellant_kg_per_julian_year=prop_year,
            corrections_per_julian_year=corrections_year,
            lifetime_projection_available=lifetime_available,
            lifetime_projection_reason=lifetime_reason,
            usable_propellant_above_reserve_kg=usable,
            projected_years_to_reserve=years_to_reserve,
            projected_remaining_corrections_to_reserve=corrections_to_reserve,
        ),
    )
