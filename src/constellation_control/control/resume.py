from __future__ import annotations

import numpy as np

from constellation_control.control.campaign import (
    CampaignAuthorityRecord,
    CampaignPolicyEventRecord,
    CampaignPolicyTraceRecord,
    ClosedLoopCampaignResult,
    run_closed_loop_campaign,
)
from constellation_control.control.checkpoint import (
    CHECKPOINT_SCHEMA_VERSION,
    ClosedLoopCampaignCheckpoint,
    PendingCorrectionDecisionSnapshot,
)
from constellation_control.control.closed_loop import continuation_request_from_snapshot
from constellation_control.control.execution import ManeuverAuthorityEvidence
from constellation_control.control.policies import CorrectionDecision, CorrectionPolicyState
from constellation_control.control.policy_execution import (
    PolicyManeuverAttemptEvidence,
    append_authorized_resource_record,
    authorize_policy_correction,
)
from constellation_control.control.transition import CorrectionResourceRecord
from constellation_control.domain.protocols import Propagator


def _validate_checkpoint(checkpoint: ClosedLoopCampaignCheckpoint) -> None:
    if checkpoint.schema_version != CHECKPOINT_SCHEMA_VERSION:
        raise ValueError(f"unsupported checkpoint schema: {checkpoint.schema_version}")
    request = checkpoint.current_request
    if request.force_model.fingerprint() != checkpoint.force_model_fingerprint:
        raise ValueError("checkpoint force-model fingerprint does not match current request")
    if request.frame.value != checkpoint.frame:
        raise ValueError("checkpoint frame does not match current request")
    if request.time_scale.value != checkpoint.time_scale:
        raise ValueError("checkpoint time scale does not match current request")
    if request.integrator != checkpoint.integrator:
        raise ValueError("checkpoint integrator does not match current request")
    if checkpoint.constraints.phase_corridor_rad != checkpoint.corridor_half_width_rad:
        raise ValueError("checkpoint constraints phase corridor does not match policy evidence")
    if checkpoint.elapsed_simulated_s > checkpoint.campaign_horizon_s + 1.0e-9:
        raise ValueError("checkpoint elapsed simulated time exceeds campaign horizon")
    if len(checkpoint.resource_ledger) > checkpoint.max_corrections:
        raise ValueError("checkpoint correction ledger exceeds configured max corrections")
    if checkpoint.resource_ledger:
        last = checkpoint.resource_ledger[-1]
        if not np.isclose(
            last.cumulative_delta_v_m_s,
            checkpoint.cumulative_delta_v_m_s,
            rtol=0.0,
            atol=1.0e-12,
        ):
            raise ValueError("checkpoint cumulative delta-V does not match resource ledger")
        if not np.isclose(
            last.cumulative_propellant_used_kg,
            checkpoint.cumulative_propellant_used_kg,
            rtol=0.0,
            atol=1.0e-12,
        ):
            raise ValueError("checkpoint cumulative propellant does not match resource ledger")
    elif checkpoint.cumulative_delta_v_m_s != 0.0 or checkpoint.cumulative_propellant_used_kg != 0.0:
        raise ValueError("checkpoint has cumulative resources without ledger evidence")


def _pending_decision(snapshot: PendingCorrectionDecisionSnapshot) -> CorrectionDecision:
    return CorrectionDecision(
        policy=snapshot.policy,
        correction_requested=True,
        reason=snapshot.reason,
        observed_delta_u_rad=snapshot.observed_delta_u_rad,
        corridor_half_width_rad=snapshot.corridor_half_width_rad,
        crossed_boundary_sign=snapshot.crossed_boundary_sign,
        guidance_target_delta_u_rad=snapshot.guidance_target_delta_u_rad,
        armed_before=snapshot.armed_before,
        armed_after=snapshot.armed_after,
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


def _authority_termination(authority: ManeuverAuthorityEvidence | None) -> str:
    if authority is None:
        return "maneuver-authority-rejected:missing-authority-evidence"
    if authority.reason == "no-maneuver-required":
        return "maneuver-not-required"
    if authority.reason == "propellant-reserve-violation":
        return "propellant-reserve-reached"
    return f"maneuver-authority-rejected:{authority.reason}"


def _shift_event(record: CampaignPolicyEventRecord, offset_s: float) -> CampaignPolicyEventRecord:
    return record.model_copy(update={"elapsed_time_s": record.elapsed_time_s + offset_s})


def _shift_trace(record: CampaignPolicyTraceRecord, offset_s: float) -> CampaignPolicyTraceRecord:
    return record.model_copy(update={"elapsed_time_s": record.elapsed_time_s + offset_s})


def _shift_authority(record: CampaignAuthorityRecord, offset_s: float) -> CampaignAuthorityRecord:
    return record.model_copy(update={"elapsed_time_s": record.elapsed_time_s + offset_s})


def _append_shifted_segment_ledger(
    prefix: tuple[CorrectionResourceRecord, ...],
    segment: tuple[CorrectionResourceRecord, ...],
    *,
    offset_s: float,
) -> tuple[CorrectionResourceRecord, ...]:
    base_dv = prefix[-1].cumulative_delta_v_m_s if prefix else 0.0
    base_propellant = prefix[-1].cumulative_propellant_used_kg if prefix else 0.0
    shifted = tuple(
        record.model_copy(
            update={
                "event_time_s": record.event_time_s + offset_s,
                "cumulative_delta_v_m_s": base_dv + record.cumulative_delta_v_m_s,
                "cumulative_propellant_used_kg": (
                    base_propellant + record.cumulative_propellant_used_kg
                ),
            }
        )
        for record in segment
    )
    return (*prefix, *shifted)


def _full_result_from_segment(
    checkpoint: ClosedLoopCampaignCheckpoint,
    segment: ClosedLoopCampaignResult,
    *,
    segment_offset_s: float,
    prefix_authority: tuple[CampaignAuthorityRecord, ...],
    prefix_transitions: tuple,
    prefix_ledger: tuple[CorrectionResourceRecord, ...],
) -> ClosedLoopCampaignResult:
    ledger = _append_shifted_segment_ledger(
        prefix_ledger,
        segment.resource_ledger,
        offset_s=segment_offset_s,
    )
    cumulative_dv = ledger[-1].cumulative_delta_v_m_s if ledger else 0.0
    cumulative_propellant = ledger[-1].cumulative_propellant_used_kg if ledger else 0.0
    return ClosedLoopCampaignResult(
        policy=checkpoint.policy,
        corridor_half_width_rad=checkpoint.corridor_half_width_rad,
        initial_epoch_iso=checkpoint.campaign_initial_epoch_iso,
        final_epoch_iso=segment.final_epoch_iso,
        elapsed_time_s=segment_offset_s + segment.elapsed_time_s,
        correction_count=len(ledger),
        coast_propagation_calls=(
            checkpoint.coast_propagation_calls + segment.coast_propagation_calls
        ),
        termination_reason=segment.termination_reason,
        final_policy_armed=segment.final_policy_armed,
        policy_events=(
            *checkpoint.policy_events,
            *tuple(_shift_event(record, segment_offset_s) for record in segment.policy_events),
        ),
        policy_trace=(
            *checkpoint.policy_trace,
            *tuple(_shift_trace(record, segment_offset_s) for record in segment.policy_trace),
        ),
        authority_attempts=(
            *prefix_authority,
            *tuple(
                _shift_authority(record, segment_offset_s)
                for record in segment.authority_attempts
            ),
        ),
        transitions=(*prefix_transitions, *segment.transitions),
        resource_ledger=ledger,
        cumulative_delta_v_m_s=cumulative_dv,
        cumulative_propellant_used_kg=cumulative_propellant,
        controlled_propellant_remaining_kg=segment.controlled_propellant_remaining_kg,
        controlled_required_reserve_kg=segment.controlled_required_reserve_kg,
        final_request=segment.final_request,
    )


def _checkpoint_terminal_result(
    checkpoint: ClosedLoopCampaignCheckpoint,
    *,
    termination_reason: str,
    authority_attempts: tuple[CampaignAuthorityRecord, ...] | None = None,
    transitions: tuple | None = None,
    ledger: tuple[CorrectionResourceRecord, ...] | None = None,
    elapsed_time_s: float | None = None,
    final_request=None,
    final_policy_armed: bool | None = None,
) -> ClosedLoopCampaignResult:
    resolved_ledger = checkpoint.resource_ledger if ledger is None else ledger
    cumulative_dv = resolved_ledger[-1].cumulative_delta_v_m_s if resolved_ledger else 0.0
    cumulative_propellant = (
        resolved_ledger[-1].cumulative_propellant_used_kg if resolved_ledger else 0.0
    )
    request = checkpoint.current_request if final_request is None else final_request
    return ClosedLoopCampaignResult(
        policy=checkpoint.policy,
        corridor_half_width_rad=checkpoint.corridor_half_width_rad,
        initial_epoch_iso=checkpoint.campaign_initial_epoch_iso,
        final_epoch_iso=request.epoch.isoformat(),
        elapsed_time_s=(
            checkpoint.elapsed_simulated_s if elapsed_time_s is None else elapsed_time_s
        ),
        correction_count=len(resolved_ledger),
        coast_propagation_calls=checkpoint.coast_propagation_calls,
        termination_reason=termination_reason,
        final_policy_armed=(
            checkpoint.policy_armed if final_policy_armed is None else final_policy_armed
        ),
        policy_events=checkpoint.policy_events,
        policy_trace=checkpoint.policy_trace,
        authority_attempts=(
            checkpoint.authority_attempts
            if authority_attempts is None
            else authority_attempts
        ),
        transitions=checkpoint.transitions if transitions is None else transitions,
        resource_ledger=resolved_ledger,
        cumulative_delta_v_m_s=cumulative_dv,
        cumulative_propellant_used_kg=cumulative_propellant,
        controlled_propellant_remaining_kg=(
            resolved_ledger[-1].propellant_remaining_kg
            if resolved_ledger
            else checkpoint.controlled_propellant_remaining_kg
        ),
        controlled_required_reserve_kg=checkpoint.controlled_required_reserve_kg,
        final_request=request,
    )


def resume_closed_loop_campaign(
    propagator: Propagator,
    checkpoint: ClosedLoopCampaignCheckpoint,
    *,
    deputy_id: str | None = None,
) -> ClosedLoopCampaignResult:
    """Resume from checkpoint using existing authority and campaign primitives."""

    _validate_checkpoint(checkpoint)
    remaining_horizon = checkpoint.campaign_horizon_s - checkpoint.elapsed_simulated_s
    remaining_corrections = checkpoint.max_corrections - len(checkpoint.resource_ledger)
    if remaining_horizon <= 1.0e-9:
        return _checkpoint_terminal_result(
            checkpoint,
            termination_reason="campaign-horizon-reached",
        )
    if remaining_corrections <= 0:
        return _checkpoint_terminal_result(
            checkpoint,
            termination_reason="max-corrections-reached",
        )

    current_request = checkpoint.current_request
    segment_offset = checkpoint.elapsed_simulated_s
    prefix_authority = checkpoint.authority_attempts
    prefix_transitions = checkpoint.transitions
    prefix_ledger = checkpoint.resource_ledger
    policy_state = CorrectionPolicyState(armed=checkpoint.policy_armed)

    if checkpoint.pending_decision is not None:
        decision = _pending_decision(checkpoint.pending_decision)
        authority_times = np.asarray(checkpoint.authority_times_s, dtype=float)
        maneuver_windows = np.asarray(checkpoint.maneuver_windows, dtype=bool)
        authority_request = current_request.model_copy(
            update={
                "duration_s": float(authority_times[-1]),
                "output_step_s": float(authority_times[1] - authority_times[0]),
                "maneuvers": (),
            }
        )
        attempt = authorize_policy_correction(
            propagator,
            authority_request,
            checkpoint.constraints,
            decision,
            checkpoint.base_execution_policy,
            authority_times,
            maneuver_windows,
            deputy_id=deputy_id,
        )
        authority_record = _authority_record(attempt, elapsed_time_s=segment_offset)
        prefix_authority = (*prefix_authority, authority_record)
        authority = attempt.authority
        if authority is None or not authority.authorized or attempt.transition is None:
            return _checkpoint_terminal_result(
                checkpoint,
                termination_reason=_authority_termination(authority),
                authority_attempts=prefix_authority,
            )
        prefix_ledger = append_authorized_resource_record(
            prefix_ledger,
            attempt,
            event_time_s=segment_offset,
        )
        prefix_transitions = (*prefix_transitions, attempt.transition)
        segment_offset += attempt.transition.continuation_time_s
        remaining_horizon = checkpoint.campaign_horizon_s - segment_offset
        if remaining_horizon <= 1.0e-9:
            continuation = continuation_request_from_snapshot(
                authority_request,
                attempt.transition,
                duration_s=checkpoint.coast_output_step_s,
                output_step_s=checkpoint.coast_output_step_s,
            )
            return _checkpoint_terminal_result(
                checkpoint,
                termination_reason="campaign-horizon-reached",
                authority_attempts=prefix_authority,
                transitions=prefix_transitions,
                ledger=prefix_ledger,
                elapsed_time_s=segment_offset,
                final_request=continuation,
                final_policy_armed=decision.armed_after,
            )
        local_coast = min(checkpoint.coast_horizon_s, remaining_horizon)
        current_request = continuation_request_from_snapshot(
            authority_request,
            attempt.transition,
            duration_s=local_coast,
            output_step_s=min(checkpoint.coast_output_step_s, local_coast),
        )
        policy_state = CorrectionPolicyState(armed=decision.armed_after)
        remaining_corrections -= 1
        if remaining_corrections <= 0:
            return _checkpoint_terminal_result(
                checkpoint,
                termination_reason="max-corrections-reached",
                authority_attempts=prefix_authority,
                transitions=prefix_transitions,
                ledger=prefix_ledger,
                elapsed_time_s=segment_offset,
                final_request=current_request,
                final_policy_armed=policy_state.armed,
            )

    segment = run_closed_loop_campaign(
        propagator,
        current_request,
        checkpoint.constraints,
        checkpoint.policy,
        checkpoint.base_execution_policy,
        np.asarray(checkpoint.authority_times_s, dtype=float),
        np.asarray(checkpoint.maneuver_windows, dtype=bool),
        campaign_horizon_s=checkpoint.campaign_horizon_s - segment_offset,
        coast_horizon_s=checkpoint.coast_horizon_s,
        coast_output_step_s=checkpoint.coast_output_step_s,
        max_corrections=remaining_corrections,
        initial_policy_state=policy_state,
        deputy_id=deputy_id,
    )
    return _full_result_from_segment(
        checkpoint,
        segment,
        segment_offset_s=segment_offset,
        prefix_authority=prefix_authority,
        prefix_transitions=prefix_transitions,
        prefix_ledger=prefix_ledger,
    )
