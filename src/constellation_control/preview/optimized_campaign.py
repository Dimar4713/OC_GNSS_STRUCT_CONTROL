from __future__ import annotations

from pathlib import Path

import numpy as np
from pydantic import BaseModel, ConfigDict

from constellation_control.adapters.orekit.adapter import OrekitSidecarPropagator
from constellation_control.analysis.campaign_hard_margins import reduce_trajectory_hard_margins
from constellation_control.analysis.closed_loop_metrics import ClosedLoopOperationalMetrics, analyze_closed_loop_operations
from constellation_control.application.run import load_scenario
from constellation_control.control.campaign import (
    CampaignAuthorityRecord,
    CampaignPolicyEventRecord,
    ClosedLoopCampaignResult,
    _authority_record,
    _event_record,
    _final_result,
    _request_delta_u,
    _request_from_result_sample,
    _resolve_pair_ids,
    _termination_from_authority,
    _validate_authority_grid,
    _validate_campaign_limits,
)
from constellation_control.control.closed_loop import continuation_request_from_snapshot, event_request_from_coast
from constellation_control.control.optimized_policy import evaluate_optimized_correction_policy
from constellation_control.control.policies import CorrectionDecision, CorrectionPolicy, CorrectionPolicyState
from constellation_control.control.policy_execution import append_authorized_resource_record, authorize_policy_correction
from constellation_control.control.transition import AuthoritativeTransitionSnapshot, CorrectionResourceRecord
from constellation_control.domain.models import Maneuver, PropagationRequest, PropagationResult
from constellation_control.domain.protocols import Propagator
from constellation_control.optimization.operational_policy_search import OperationalPolicyParameters
from constellation_control.optimization.optimal_operations_orchestration import AuthoritativeOperationalOutcomeEvidence
from constellation_control.optimization.operations import NamedObjectiveValue
from constellation_control.optimization.optimized_hybrid_execution import _scan_optimized_trigger
from constellation_control.preview.optimal_operations_execution import (
    _hard_constraint,
    _initial_request,
    _objective_value,
    _validate_replay_authority,
)
from constellation_control.preview.optimal_operations_profile import PreviewOptimalOperationsStudyProfile, preflight_optimal_operations_study


class PreviewOptimizedCampaignEvidence(BaseModel):
    model_config = ConfigDict(frozen=True)

    candidate_id: str
    trigger_fraction: float
    target_fraction: float
    campaign: ClosedLoopCampaignResult
    operational_metrics: ClosedLoopOperationalMetrics
    full_horizon_backend: str
    full_horizon_force_model_fingerprint: str
    outcome: AuthoritativeOperationalOutcomeEvidence


def _full_horizon_request(
    initial: PropagationRequest,
    campaign: ClosedLoopCampaignResult,
    profile: PreviewOptimalOperationsStudyProfile,
) -> PropagationRequest:
    maneuvers = tuple(
        Maneuver(
            satellite_id=profile.controlled_deputy_id,
            time_s=item.event_time_s,
            dv_rtn_m_s=item.dv_rtn_m_s,
        )
        for item in campaign.resource_ledger
    )
    return initial.model_copy(
        update={
            "maneuvers": maneuvers,
            "duration_s": profile.campaign_horizon_s,
            "output_step_s": min(profile.coast_output_step_s, profile.campaign_horizon_s),
            "seed": profile.seed,
        }
    )


def run_optimized_closed_loop_campaign(
    propagator: Propagator,
    initial_request: PropagationRequest,
    profile: PreviewOptimalOperationsStudyProfile,
    parameters: OperationalPolicyParameters,
    *,
    candidate_id: str,
    initial_policy_state: CorrectionPolicyState | None = None,
) -> ClosedLoopCampaignResult:
    """Run repeated optimized trigger/coast/correction cycles through accepted P2 numerical authority."""

    scenario = load_scenario(Path(profile.scenario_name)) if Path(profile.scenario_name).exists() else None
    constraints = None if scenario is None else scenario.constraints
    if constraints is None:
        raise ValueError("optimized campaign requires ScenarioConfig constraints resolved by caller path")
    authority_grid = _validate_authority_grid(
        np.asarray(profile.authority_times_s, dtype=float),
        np.asarray(profile.maneuver_windows, dtype=bool),
    )
    campaign_horizon, coast_horizon, coast_step = _validate_campaign_limits(
        profile.campaign_horizon_s,
        profile.coast_horizon_s,
        profile.coast_output_step_s,
        profile.max_corrections,
    )
    controlled_id, reference_id = _resolve_pair_ids(initial_request, profile.controlled_deputy_id)
    if controlled_id != profile.controlled_deputy_id:
        raise ValueError("optimized campaign controlled deputy does not match explicit profile")

    current_request = initial_request
    policy_state = CorrectionPolicyState() if initial_policy_state is None else initial_policy_state
    elapsed = 0.0
    coast_calls = 0
    events: list[CampaignPolicyEventRecord] = []
    attempts: list[CampaignAuthorityRecord] = []
    transitions: list[AuthoritativeTransitionSnapshot] = []
    ledger: tuple[CorrectionResourceRecord, ...] = ()

    current_delta_u = _request_delta_u(current_request, controlled_id, reference_id)
    optimized, policy_state = evaluate_optimized_correction_policy(
        candidate_id,
        parameters,
        current_delta_u,
        constraints.phase_corridor_rad,
        policy_state,
    )
    pending_decision: CorrectionDecision | None = (
        optimized.decision if optimized.decision.correction_requested else None
    )
    if pending_decision is not None:
        events.append(
            _event_record(
                pending_decision,
                elapsed_time_s=0.0,
                source="initial-state-optimized",
                local_sample_index=0,
                local_time_s=0.0,
            )
        )

    while True:
        if elapsed >= campaign_horizon - 1.0e-9:
            reason = "campaign-horizon-reached"
            break

        if pending_decision is not None:
            if len(ledger) >= profile.max_corrections:
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
                profile.execution_policy.backend_policy(),
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
        scan, optimized = _scan_optimized_trigger(
            coast_result,
            candidate_id=candidate_id,
            parameters=parameters,
            reference_id=reference_id,
            deputy_id=controlled_id,
            hard_corridor_half_width_rad=constraints.phase_corridor_rad,
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
                else "no-next-optimized-trigger-in-coast-horizon"
            )
            break

        event = scan.event
        elapsed += event.time_s
        events.append(
            _event_record(
                event.decision,
                elapsed_time_s=elapsed,
                source="optimized-coast-grid",
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
        policy=CorrectionPolicy.OPTIMIZED,
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
        trace=[],
    )


def run_authoritative_optimized_outcome(
    scenario_path: Path,
    profile: PreviewOptimalOperationsStudyProfile,
    parameters: OperationalPolicyParameters,
    *,
    candidate_id: str,
    propagator: Propagator | None = None,
) -> PreviewOptimizedCampaignEvidence:
    """Run one selected optimized candidate and normalize only numerical evidence into the accepted outcome contract."""

    preflight = preflight_optimal_operations_study(scenario_path, profile)
    scenario = load_scenario(scenario_path)
    resolved = propagator
    if resolved is None:
        assert scenario.orekit_sidecar_url is not None
        resolved = OrekitSidecarPropagator(scenario.orekit_sidecar_url)
    initial = _initial_request(scenario_path).model_copy(update={"seed": profile.seed})

    # Resolve constraints from the exact selected path; do not rely on CWD/profile name.
    campaign_profile = profile.model_copy(update={"scenario_name": str(scenario_path)})
    campaign = run_optimized_closed_loop_campaign(
        resolved,
        initial,
        campaign_profile,
        parameters,
        candidate_id=candidate_id,
    )
    if campaign.elapsed_time_s + 1.0e-9 < profile.campaign_horizon_s:
        raise ValueError(
            "optimized campaign did not cover the declared campaign horizon; "
            f"termination={campaign.termination_reason}"
        )
    for record in campaign.resource_ledger:
        if not record.replay_backend.startswith("orekit-numerical"):
            raise ValueError("optimized campaign resource ledger lacks numerical authority")
        if record.force_model_fingerprint != preflight.identity.force_model_fingerprint:
            raise ValueError("optimized campaign resource fingerprint does not match study identity")

    metrics = analyze_closed_loop_operations(campaign)
    replay_request = _full_horizon_request(initial, campaign, profile)
    replay: PropagationResult = resolved.propagate(replay_request)
    _validate_replay_authority(replay, preflight)
    margins = reduce_trajectory_hard_margins(
        replay,
        scenario.constraints,
        reference_id=preflight.reference_id,
        deputy_id=preflight.controlled_deputy_id,
    )
    objectives: tuple[NamedObjectiveValue, ...] = tuple(
        NamedObjectiveValue(
            name=definition.name,
            unit=definition.unit,
            direction=definition.direction,
            value=_objective_value(definition, campaign, metrics),
        )
        for definition in profile.objectives
    )
    hard_constraints = tuple(
        _hard_constraint(definition, campaign, margins) for definition in profile.hard_constraints
    )
    outcome_payload = {
        "candidate_id": candidate_id,
        "parameters": parameters.model_dump(mode="json"),
        "campaign": campaign.model_dump(mode="json"),
        "metrics": metrics.model_dump(mode="json"),
        "margins": margins.model_dump(mode="json"),
        "replay_backend": replay.backend,
        "replay_force_model_fingerprint": replay.force_model_fingerprint,
    }
    import hashlib
    import json

    evidence_id = hashlib.sha256(
        json.dumps(outcome_payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    ).hexdigest()
    outcome = AuthoritativeOperationalOutcomeEvidence(
        campaign_termination_reason=campaign.termination_reason,
        correction_count=campaign.correction_count,
        corrections_per_julian_year=metrics.annualized.corrections_per_julian_year,
        cumulative_delta_v_m_s=campaign.cumulative_delta_v_m_s,
        delta_v_m_s_per_julian_year=metrics.annualized.delta_v_m_s_per_julian_year,
        cumulative_propellant_used_kg=campaign.cumulative_propellant_used_kg,
        propellant_kg_per_julian_year=metrics.annualized.propellant_kg_per_julian_year,
        projected_years_to_reserve=metrics.annualized.projected_years_to_reserve,
        minimum_corridor_margin_rad=margins.phase_corridor_margin_rad,
        minimum_fleet_distance_margin_m=margins.minimum_fleet_distance_margin_m,
        settling_mean_s=metrics.rearm_settling_intervals.seconds.mean,
        coast_mean_s=metrics.post_rearm_coast_intervals.seconds.mean,
        objectives=objectives,
        hard_constraints=hard_constraints,
        evidence_id=evidence_id,
    )
    return PreviewOptimizedCampaignEvidence(
        candidate_id=candidate_id,
        trigger_fraction=parameters.trigger_fraction,
        target_fraction=parameters.target_fraction,
        campaign=campaign,
        operational_metrics=metrics,
        full_horizon_backend=replay.backend,
        full_horizon_force_model_fingerprint=replay.force_model_fingerprint,
        outcome=outcome,
    )
