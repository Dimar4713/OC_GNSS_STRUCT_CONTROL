from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from constellation_control.application.run import load_scenario
from constellation_control.control.campaign import (
    CampaignPolicyEventRecord,
    CampaignPolicyTraceRecord,
    ClosedLoopCampaignResult,
)
from constellation_control.control.checkpoint import (
    CHECKPOINT_SCHEMA_VERSION,
    ClosedLoopCampaignCheckpoint,
    campaign_progress,
    create_campaign_checkpoint,
    pending_decision_from_campaign,
)
from constellation_control.control.execution import MPCExecutionPolicy
from constellation_control.control.policies import CorrectionPolicy
from constellation_control.domain.models import ConstraintConfig, PropagationRequest


def _scenario():
    return load_scenario(Path(__file__).parents[1] / "scenarios" / "mvp_45deg.yaml")


def _request() -> PropagationRequest:
    scenario = _scenario()
    return PropagationRequest(
        scenario_id=scenario.scenario_id,
        epoch=scenario.epoch,
        frame=scenario.frame,
        time_scale=scenario.time_scale,
        satellites=scenario.constellation.satellites,
        maneuvers=(),
        duration_s=60.0,
        output_step_s=60.0,
        force_model=scenario.force_model,
        integrator=scenario.integrator,
        seed=scenario.seed,
    )


def _constraints() -> ConstraintConfig:
    return _scenario().constraints


def _execution_policy() -> MPCExecutionPolicy:
    return MPCExecutionPolicy(
        max_abs_impulse_rtn_m_s=(0.2, 0.2, 0.2),
        min_impulse_bit_m_s=1.0e-3,
        trust_tolerances_roe=(1.0e-6, 1.0e-3, 1.0e-6, 1.0e-6, 1.0e-6, 1.0e-6),
        w_tracking=10.0,
        w_max=0.5,
    )


def _boundary_event(elapsed_s: float) -> CampaignPolicyEventRecord:
    return CampaignPolicyEventRecord(
        elapsed_time_s=elapsed_s,
        source="coast-grid",
        local_sample_index=2,
        local_time_s=120.0,
        observed_delta_u_rad=-0.1,
        decision_reason="phase_boundary_reached_coast_to_opposite_boundary",
        crossed_boundary_sign=-1,
        guidance_target_delta_u_rad=0.1,
        armed_before=True,
        armed_after=False,
    )


def _trace(elapsed_s: float, reason: str) -> CampaignPolicyTraceRecord:
    return CampaignPolicyTraceRecord(
        elapsed_time_s=elapsed_s,
        local_sample_index=1,
        local_time_s=60.0,
        delta_u_rad=0.0,
        decision_reason=reason,
        correction_requested=False,
        crossed_boundary_sign=None,
        guidance_target_delta_u_rad=None,
        armed_before=False,
        armed_after=True,
        grid_resolution_s=60.0,
        timing_semantics="authoritative propagation output grid; no interpolation",
    )


def _campaign(*, elapsed_s: float, event_elapsed_s: float) -> ClosedLoopCampaignResult:
    request = _request()
    return ClosedLoopCampaignResult(
        policy=CorrectionPolicy.BOUNDARY_TO_BOUNDARY,
        corridor_half_width_rad=0.1,
        initial_epoch_iso=request.epoch.isoformat(),
        final_epoch_iso=request.epoch.isoformat(),
        elapsed_time_s=elapsed_s,
        correction_count=2,
        coast_propagation_calls=3,
        termination_reason="max-corrections-reached",
        final_policy_armed=False,
        policy_events=(_boundary_event(event_elapsed_s),),
        policy_trace=(_trace(max(0.0, event_elapsed_s - 60.0), "rearmed_inside_corridor"),),
        authority_attempts=(),
        transitions=(),
        resource_ledger=(),
        cumulative_delta_v_m_s=0.25,
        cumulative_propellant_used_kg=3.0,
        controlled_propellant_remaining_kg=40.0,
        controlled_required_reserve_kg=10.0,
        final_request=request,
    )


def _checkpoint(campaign: ClosedLoopCampaignResult, *, sequence: int = 0) -> ClosedLoopCampaignCheckpoint:
    return create_campaign_checkpoint(
        campaign,
        constraints=_constraints(),
        base_execution_policy=_execution_policy(),
        campaign_horizon_s=720.0,
        coast_horizon_s=120.0,
        coast_output_step_s=60.0,
        authority_times_s=np.asarray([0.0, 60.0]),
        maneuver_windows=np.asarray([True]),
        max_corrections=4,
        checkpoint_sequence=sequence,
    )


def test_boundary_before_authority_checkpoint_retains_exact_pending_decision() -> None:
    campaign = _campaign(elapsed_s=360.0, event_elapsed_s=360.0)
    pending = pending_decision_from_campaign(campaign)

    assert pending is not None
    assert pending.policy == CorrectionPolicy.BOUNDARY_TO_BOUNDARY
    assert pending.reason == "phase_boundary_reached_coast_to_opposite_boundary"
    assert pending.observed_delta_u_rad == pytest.approx(-0.1)
    assert pending.corridor_half_width_rad == pytest.approx(0.1)
    assert pending.crossed_boundary_sign == -1
    assert pending.guidance_target_delta_u_rad == pytest.approx(0.1)
    assert pending.armed_before is True
    assert pending.armed_after is False


def test_non_boundary_terminal_state_does_not_fabricate_pending_decision() -> None:
    campaign = _campaign(elapsed_s=420.0, event_elapsed_s=360.0)
    assert pending_decision_from_campaign(campaign) is None


def test_checkpoint_json_round_trip_preserves_continuation_identity_and_evidence() -> None:
    campaign = _campaign(elapsed_s=360.0, event_elapsed_s=360.0)
    checkpoint = _checkpoint(campaign, sequence=2)

    restored = ClosedLoopCampaignCheckpoint.model_validate_json(checkpoint.model_dump_json())
    assert restored == checkpoint
    assert restored.schema_version == CHECKPOINT_SCHEMA_VERSION
    assert restored.campaign_initial_epoch_iso == campaign.initial_epoch_iso
    assert restored.current_request == campaign.final_request
    assert restored.force_model_fingerprint == campaign.final_request.force_model.fingerprint()
    assert restored.frame == campaign.final_request.frame.value
    assert restored.time_scale == campaign.final_request.time_scale.value
    assert restored.integrator == campaign.final_request.integrator
    assert restored.constraints == _constraints()
    assert restored.base_execution_policy == _execution_policy()
    assert restored.authority_times_s == (0.0, 60.0)
    assert restored.maneuver_windows == (True,)
    assert restored.pending_decision is not None
    assert restored.policy_trace == campaign.policy_trace


def test_progress_reports_simulated_fraction_remaining_and_usable_fuel_without_runtime_eta() -> None:
    campaign = _campaign(elapsed_s=360.0, event_elapsed_s=360.0)
    progress = campaign_progress(
        campaign,
        campaign_horizon_s=720.0,
        max_corrections=4,
        checkpoint_sequence=3,
    )

    assert progress.simulated_progress_fraction == pytest.approx(0.5)
    assert progress.remaining_simulated_s == pytest.approx(360.0)
    assert progress.correction_progress_fraction == pytest.approx(0.5)
    assert progress.cumulative_delta_v_m_s == pytest.approx(0.25)
    assert progress.cumulative_propellant_used_kg == pytest.approx(3.0)
    assert progress.usable_propellant_above_reserve_kg == pytest.approx(30.0)
    assert progress.last_policy_reason == "phase_boundary_reached_coast_to_opposite_boundary"
    assert progress.checkpoint_sequence == 3
    assert progress.runtime_eta_available is False
    assert "not inferred from simulated time" in progress.runtime_eta_reason


def test_checkpoint_creation_is_pure_evidence_construction() -> None:
    campaign = _campaign(elapsed_s=360.0, event_elapsed_s=360.0)

    class BombPropagator:
        def propagate(self, request):
            raise AssertionError("checkpoint creation must not invoke propagation")

    bomb = BombPropagator()
    del bomb
    checkpoint = _checkpoint(campaign)
    assert checkpoint.current_request == campaign.final_request


def test_checkpoint_rejects_mismatched_phase_corridor() -> None:
    campaign = _campaign(elapsed_s=360.0, event_elapsed_s=360.0)
    constraints = _constraints().model_copy(update={"phase_corridor_rad": 0.2})
    with pytest.raises(ValueError, match="phase corridor does not match"):
        create_campaign_checkpoint(
            campaign,
            constraints=constraints,
            base_execution_policy=_execution_policy(),
            campaign_horizon_s=720.0,
            coast_horizon_s=120.0,
            coast_output_step_s=60.0,
            authority_times_s=np.asarray([0.0, 60.0]),
            maneuver_windows=np.asarray([True]),
            max_corrections=4,
        )
