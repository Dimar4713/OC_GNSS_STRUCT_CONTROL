from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from math import isfinite

import numpy as np
from pydantic import BaseModel, ConfigDict, Field

from constellation_control.analysis.relative_operations import mean_phase_rad
from constellation_control.control.closed_loop import (
    CoastPolicyEvent,
    continuation_request_from_snapshot,
    event_request_from_coast,
    scan_coast_for_policy_event,
)
from constellation_control.control.execution import MPCExecutionPolicy, ManeuverAuthorityEvidence
from constellation_control.control.policies import (
    CorrectionDecision,
    CorrectionPolicy,
    CorrectionPolicyState,
    evaluate_correction_policy,
)
from constellation_control.control.policy_execution import (
    PolicyManeuverAttemptEvidence,
    append_authorized_resource_record,
    authorize_policy_correction,
)
from constellation_control.control.transition import (
    AuthoritativeTransitionSnapshot,
    CorrectionResourceRecord,
)
from constellation_control.domain.models import ConstraintConfig, PropagationRequest, PropagationResult
from constellation_control.domain.protocols import Propagator
from constellation_control.dynamics.orbits import wrap_pi


class CampaignPolicyEventRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    elapsed_time_s: float = Field(ge=0.0)
    source: str
    local_sample_index: int = Field(ge=0)
    local_time_s: float = Field(ge=0.0)
    observed_delta_u_rad: float
    decision_reason: str
    crossed_boundary_sign: int | None
    guidance_target_delta_u_rad: float | None
    armed_before: bool
    armed_after: bool


class CampaignAuthorityRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    elapsed_time_s: float = Field(ge=0.0)
    authorized: bool
    reason: str
    sizing_attempted: bool
    adapted_target_roe: tuple[float, ...] | None
    dv_rtn_m_s: tuple[float, float, float] | None
    propellant_used_kg: float = Field(ge=0.0)
    propellant_remaining_kg: float = Field(ge=0.0)
    required_reserve_kg: float = Field(ge=0.0)
    replay_backend: str | None
    trust_error_ratio: float | None
    replay_min_pair_distance_m: float | None


class ClosedLoopCampaignResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    policy: CorrectionPolicy
    corridor_half_width_rad: float = Field(gt=0.0)
    initial_epoch_iso: str
    final_epoch_iso: str
    elapsed_time_s: float = Field(ge=0.0)
    correction_count: int = Field(ge=0)
    coast_propagation_calls: int = Field(ge=0)
    termination_reason: str
    final_policy_armed: bool
    policy_events: tuple[CampaignPolicyEventRecord, ...]
    authority_attempts: tuple[CampaignAuthorityRecord, ...]
    transitions: tuple[AuthoritativeTransitionSnapshot, ...]
    resource_ledger: tuple[CorrectionResourceRecord, ...]
    cumulative_delta_v_m_s: float = Field(ge=0.0)
    cumulative_propellant_used_kg: float = Field(ge=0.0)
    controlled_propellant_remaining_kg: float = Field(ge=0.0)
    controlled_required_reserve_kg: float = Field(ge=0.0)
    final_request: PropagationRequest


@dataclass(frozen=True)
class _AuthorityGrid:
    times_s: np.ndarray
    maneuver_windows: np.ndarray
    duration_s: float
    output_step_s: float


def _validate_authority_grid(times_s: np.ndarray, maneuver_windows: np.ndarray) -> _AuthorityGrid:
    times = np.asarray(times_s, dtype=float)
    windows = np.asarray(maneuver_windows, dtype=bool)
    if times.ndim != 1 or times.size < 2 or np.any(~np.isfinite(times)):
        raise ValueError("authority_times_s must be a finite one-dimensional grid with at least two samples")
    if abs(float(times[0])) > 1.0e-9:
        raise ValueError("authority_times_s must start at zero")
    intervals = np.diff(times)
    if np.any(intervals <= 0.0):
        raise ValueError("authority_times_s must be strictly increasing")
    step = float(intervals[0])
    if not np.allclose(intervals, step, rtol=0.0, atol=1.0e-9):
        raise ValueError("authority_times_s must use a uniform output grid")
    if windows.shape != (times.size - 1,):
        raise ValueError("maneuver_windows must have one entry per authority interval")
    return _AuthorityGrid(times, windows, float(times[-1]), step)


def _validate_campaign_limits(
    campaign_horizon_s: float,
    coast_horizon_s: float,
    coast_output_step_s: float,
    max_corrections: int,
) -> tuple[float, float, float]:
    campaign = float(campaign_horizon_s)
    coast = float(coast_horizon_s)
    step = float(coast_output_step_s)
    if not isfinite(campaign) or campaign <= 0.0:
        raise ValueError("campaign_horizon_s must be finite and positive")
    if not isfinite(coast) or coast <= 0.0:
        raise ValueError("coast_horizon_s must be finite and positive")
    if not isfinite(step) or step <= 0.0:
        raise ValueError("coast_output_step_s must be finite and positive")
    if max_corrections <= 0:
        raise ValueError("max_corrections must be positive")
    return campaign, coast, step


def _resolve_pair_ids(request: PropagationRequest, deputy_id: str | None) -> tuple[str, str]:
    by_id = {sat.satellite_id: sat for sat in request.satellites}
    additional = [sat for sat in request.satellites if sat.role == "additional"]
    if deputy_id is None:
        if len(additional) != 1:
            raise ValueError("deputy_id is required unless exactly one additional satellite is present")
        deputy = additional[0]
    else:
        matches = [sat for sat in additional if sat.satellite_id == deputy_id]
        if len(matches) != 1:
            raise ValueError(f"unknown or non-additional deputy_id: {deputy_id}")
        deputy = matches[0]
    if deputy.reference_id is None or deputy.reference_id not in by_id:
        raise ValueError("controlled deputy requires a valid reference_id")
    return deputy.satellite_id, deputy.reference_id


def _request_delta_u(request: PropagationRequest, deputy_id: str, reference_id: str) -> float:
    by_id = {sat.satellite_id: sat for sat in request.satellites}
    return wrap_pi(
        mean_phase_rad(by_id[deputy_id].mean_orbit)
        - mean_phase_rad(by_id[reference_id].mean_orbit)
    )


def _request_from_result_sample(
    source: PropagationRequest,
    result: PropagationResult,
    index: int,
) -> PropagationRequest:
    """Advance an immutable baseline request to one authoritative result sample."""

    if result.force_model_fingerprint != source.force_model.fingerprint():
        raise ValueError("coast result force-model fingerprint does not match source request")
    if not result.times_s:
        raise ValueError("coast result must contain at least one time sample")
    resolved_index = index if index >= 0 else len(result.times_s) + index
    if resolved_index < 0 or resolved_index >= len(result.times_s):
        raise IndexError("coast result sample index is outside the time grid")
    rebuilt = []
    for satellite in source.satellites:
        history = result.mean_orbits.get(satellite.satellite_id)
        if history is None or len(history) <= resolved_index:
            raise ValueError(f"coast result lacks mean state for {satellite.satellite_id} at terminal sample")
        rebuilt.append(satellite.model_copy(update={"mean_orbit": history[resolved_index]}))
    return source.model_copy(
        update={
            "epoch": source.epoch + timedelta(seconds=float(result.times_s[resolved_index])),
            "satellites": tuple(rebuilt),
            "maneuvers": (),
        }
    )


def _event_record(
    decision: CorrectionDecision,
    *,
    elapsed_time_s: float,
    source: str,
    local_sample_index: int,
    local_time_s: float,
) -> CampaignPolicyEventRecord:
    return CampaignPolicyEventRecord(
        elapsed_time_s=elapsed_time_s,
        source=source,
        local_sample_index=local_sample_index,
        local_time_s=local_time_s,
        observed_delta_u_rad=decision.observed_delta_u_rad,
        decision_reason=decision.reason,
        crossed_boundary_sign=decision.crossed_boundary_sign,
        guidance_target_delta_u_rad=decision.guidance_target_delta_u_rad,
        armed_before=decision.armed_before,
        armed_after=decision.armed_after,
    )


def _authority_record(
    attempt: PolicyManeuverAttemptEvidence,
    *,
    elapsed_time_s: float,
) -> CampaignAuthorityRecord:
    authority = attempt.authority
    if authority is None:
        return CampaignAuthorityRecord(
            elapsed_time_s=elapsed_time_s,
            authorized=False,
            reason="authority-not-attempted",
            sizing_attempted=attempt.sizing_attempted,
            adapted_target_roe=None if attempt.target is None else attempt.target.adapted_target_roe,
            dv_rtn_m_s=None,
            propellant_used_kg=0.0,
            propellant_remaining_kg=0.0,
            required_reserve_kg=0.0,
            replay_backend=None,
            trust_error_ratio=None,
            replay_min_pair_distance_m=None,
        )
    maneuver = authority.first_maneuver
    return CampaignAuthorityRecord(
        elapsed_time_s=elapsed_time_s,
        authorized=authority.authorized,
        reason=authority.reason,
        sizing_attempted=attempt.sizing_attempted,
        adapted_target_roe=None if attempt.target is None else attempt.target.adapted_target_roe,
        dv_rtn_m_s=None if maneuver is None else maneuver.dv_rtn_m_s,
        propellant_used_kg=authority.propellant_used_kg,
        propellant_remaining_kg=authority.propellant_remaining_kg,
        required_reserve_kg=authority.required_reserve_kg,
        replay_backend=authority.replay_backend,
        trust_error_ratio=authority.trust_error_ratio,
        replay_min_pair_distance_m=authority.replay_min_pair_distance_m,
    )


def _termination_from_authority(authority: ManeuverAuthorityEvidence | None) -> str:
    if authority is None:
        return "maneuver-authority-rejected:missing-authority-evidence"
    if authority.reason == "no-maneuver-required":
        return "maneuver-not-required"
    if authority.reason == "propellant-reserve-violation":
        return "propellant-reserve-reached"
    return f"maneuver-authority-rejected:{authority.reason}"


def _final_result(
    *,
    policy: CorrectionPolicy,
    constraints: ConstraintConfig,
    initial_request: PropagationRequest,
    current_request: PropagationRequest,
    elapsed_time_s: float,
    coast_calls: int,
    termination_reason: str,
    policy_state: CorrectionPolicyState,
    events: list[CampaignPolicyEventRecord],
    attempts: list[CampaignAuthorityRecord],
    transitions: list[AuthoritativeTransitionSnapshot],
    ledger: tuple[CorrectionResourceRecord, ...],
    deputy_id: str,
) -> ClosedLoopCampaignResult:
    deputy = next(sat for sat in current_request.satellites if sat.satellite_id == deputy_id)
    cumulative_dv = ledger[-1].cumulative_delta_v_m_s if ledger else 0.0
    cumulative_propellant = ledger[-1].cumulative_propellant_used_kg if ledger else 0.0
    reserve = deputy.spacecraft.propellant_mass_kg * constraints.propellant_reserve_fraction
    return ClosedLoopCampaignResult(
        policy=policy,
        corridor_half_width_rad=constraints.phase_corridor_rad,
        initial_epoch_iso=initial_request.epoch.isoformat(),
        final_epoch_iso=current_request.epoch.isoformat(),
        elapsed_time_s=elapsed_time_s,
        correction_count=len(ledger),
        coast_propagation_calls=coast_calls,
        termination_reason=termination_reason,
        final_policy_armed=policy_state.armed,
        policy_events=tuple(events),
        authority_attempts=tuple(attempts),
        transitions=tuple(transitions),
        resource_ledger=ledger,
        cumulative_delta_v_m_s=cumulative_dv,
        cumulative_propellant_used_kg=cumulative_propellant,
        controlled_propellant_remaining_kg=deputy.spacecraft.propellant_mass_kg,
        controlled_required_reserve_kg=reserve,
        final_request=current_request,
    )


def run_closed_loop_campaign(
    propagator: Propagator,
    initial_request: PropagationRequest,
    constraints: ConstraintConfig,
    policy: CorrectionPolicy,
    base_execution_policy: MPCExecutionPolicy,
    authority_times_s: np.ndarray,
    maneuver_windows: np.ndarray,
    *,
    campaign_horizon_s: float,
    coast_horizon_s: float,
    coast_output_step_s: float,
    max_corrections: int,
    initial_policy_state: CorrectionPolicyState | None = None,
    deputy_id: str | None = None,
) -> ClosedLoopCampaignResult:
    """Run deterministic grid-resolved correction/coast cycles using existing authority primitives."""

    authority_grid = _validate_authority_grid(authority_times_s, maneuver_windows)
    campaign_horizon, coast_horizon, coast_step = _validate_campaign_limits(
        campaign_horizon_s,
        coast_horizon_s,
        coast_output_step_s,
        max_corrections,
    )
    controlled_id, reference_id = _resolve_pair_ids(initial_request, deputy_id)
    current_request = initial_request
    policy_state = CorrectionPolicyState() if initial_policy_state is None else initial_policy_state
    elapsed = 0.0
    coast_calls = 0
    events: list[CampaignPolicyEventRecord] = []
    attempts: list[CampaignAuthorityRecord] = []
    transitions: list[AuthoritativeTransitionSnapshot] = []
    ledger: tuple[CorrectionResourceRecord, ...] = ()

    current_delta_u = _request_delta_u(current_request, controlled_id, reference_id)
    decision, policy_state = evaluate_correction_policy(
        policy,
        current_delta_u,
        constraints.phase_corridor_rad,
        policy_state,
    )
    if policy == CorrectionPolicy.NO_CONTROL:
        return _final_result(
            policy=policy,
            constraints=constraints,
            initial_request=initial_request,
            current_request=current_request,
            elapsed_time_s=elapsed,
            coast_calls=coast_calls,
            termination_reason="no-control-policy",
            policy_state=policy_state,
            events=events,
            attempts=attempts,
            transitions=transitions,
            ledger=ledger,
            deputy_id=controlled_id,
        )

    pending_decision: CorrectionDecision | None = decision if decision.correction_requested else None
    if pending_decision is not None:
        events.append(
            _event_record(
                pending_decision,
                elapsed_time_s=elapsed,
                source="initial-state",
                local_sample_index=0,
                local_time_s=0.0,
            )
        )

    while True:
        if elapsed >= campaign_horizon - 1.0e-9:
            reason = "campaign-horizon-reached"
            break

        if pending_decision is not None:
            if len(ledger) >= max_corrections:
                reason = "max-corrections-reached"
                break
            authority_request = current_request.model_copy(
                update={
                    "duration_s": authority_grid.duration_s,
                    "output_step_s": authority_grid.output_step_s,
                    "maneuvers": (),
                }
            )
            attempt = authorize_policy_correction(
                propagator,
                authority_request,
                constraints,
                pending_decision,
                base_execution_policy,
                authority_grid.times_s,
                authority_grid.maneuver_windows,
                deputy_id=controlled_id,
            )
            attempts.append(_authority_record(attempt, elapsed_time_s=elapsed))
            authority = attempt.authority
            if authority is None or not authority.authorized or attempt.transition is None:
                reason = _termination_from_authority(authority)
                break

            ledger = append_authorized_resource_record(ledger, attempt, event_time_s=elapsed)
            transitions.append(attempt.transition)
            elapsed += attempt.transition.continuation_time_s
            remaining = campaign_horizon - elapsed
            if remaining <= 1.0e-9:
                current_request = continuation_request_from_snapshot(
                    authority_request,
                    attempt.transition,
                    duration_s=coast_step,
                    output_step_s=coast_step,
                )
                reason = "campaign-horizon-reached"
                break
            local_coast = min(coast_horizon, remaining)
            current_request = continuation_request_from_snapshot(
                authority_request,
                attempt.transition,
                duration_s=local_coast,
                output_step_s=min(coast_step, local_coast),
            )
            pending_decision = None

        remaining = campaign_horizon - elapsed
        if remaining <= 1.0e-9:
            reason = "campaign-horizon-reached"
            break
        local_coast = min(coast_horizon, remaining)
        if current_request.duration_s != local_coast or current_request.output_step_s > local_coast:
            current_request = current_request.model_copy(
                update={
                    "duration_s": local_coast,
                    "output_step_s": min(coast_step, local_coast),
                    "maneuvers": (),
                }
            )
        coast_result = propagator.propagate(current_request)
        coast_calls += 1
        scan = scan_coast_for_policy_event(
            coast_result,
            reference_id=reference_id,
            deputy_id=controlled_id,
            policy=policy,
            corridor_half_width_rad=constraints.phase_corridor_rad,
            initial_state=policy_state,
            output_step_s=current_request.output_step_s,
        )
        policy_state = scan.final_policy_state
        if scan.event is None:
            coast_elapsed = float(coast_result.times_s[-1])
            current_request = _request_from_result_sample(current_request, coast_result, -1)
            elapsed += coast_elapsed
            reason = (
                "campaign-horizon-reached"
                if elapsed >= campaign_horizon - 1.0e-9
                else "no-next-policy-event-in-coast-horizon"
            )
            break

        event: CoastPolicyEvent = scan.event
        elapsed += event.time_s
        events.append(
            _event_record(
                event.decision,
                elapsed_time_s=elapsed,
                source="coast-grid",
                local_sample_index=event.sample_index,
                local_time_s=event.time_s,
            )
        )
        pending_decision = event.decision
        current_request = event_request_from_coast(
            current_request,
            event,
            duration_s=authority_grid.duration_s,
            output_step_s=authority_grid.output_step_s,
        )

    return _final_result(
        policy=policy,
        constraints=constraints,
        initial_request=initial_request,
        current_request=current_request,
        elapsed_time_s=elapsed,
        coast_calls=coast_calls,
        termination_reason=reason,
        policy_state=policy_state,
        events=events,
        attempts=attempts,
        transitions=transitions,
        ledger=ledger,
        deputy_id=controlled_id,
    )
