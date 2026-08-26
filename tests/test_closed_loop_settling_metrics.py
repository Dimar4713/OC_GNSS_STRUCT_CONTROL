from __future__ import annotations

from pathlib import Path

import pytest

from constellation_control.analysis.closed_loop_metrics import analyze_closed_loop_operations
from constellation_control.application.run import load_scenario
from constellation_control.control.campaign import (
    CampaignPolicyTraceRecord,
    ClosedLoopCampaignResult,
)
from constellation_control.control.policies import CorrectionPolicy
from constellation_control.control.transition import CorrectionResourceRecord
from constellation_control.domain.models import PropagationRequest


def _request() -> PropagationRequest:
    scenario = load_scenario(Path(__file__).parents[1] / "scenarios" / "mvp_45deg.yaml")
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


def _resource(event_time_s: float, cumulative_dv: float, cumulative_propellant: float, remaining: float) -> CorrectionResourceRecord:
    request = _request()
    return CorrectionResourceRecord(
        event_time_s=event_time_s,
        policy=CorrectionPolicy.BOUNDARY_TO_BOUNDARY.value,
        policy_reason="phase_boundary_reached_coast_to_opposite_boundary",
        crossed_boundary_sign=1,
        observed_delta_u_rad=0.1,
        guidance_target_delta_u_rad=-0.1,
        dv_rtn_m_s=(0.0, 0.01, 0.0),
        delta_v_m_s=0.01,
        propellant_used_kg=1.0,
        propellant_remaining_kg=remaining,
        required_reserve_kg=10.0,
        cumulative_delta_v_m_s=cumulative_dv,
        cumulative_propellant_used_kg=cumulative_propellant,
        replay_backend="orekit-numerical-validation",
        replay_backend_metadata={"gravity_model": "EIGEN-6S"},
        force_model_fingerprint=request.force_model.fingerprint(),
    )


def _trace(elapsed_time_s: float, reason: str, *, armed_before: bool, armed_after: bool) -> CampaignPolicyTraceRecord:
    return CampaignPolicyTraceRecord(
        elapsed_time_s=elapsed_time_s,
        local_sample_index=1,
        local_time_s=60.0,
        delta_u_rad=0.0,
        decision_reason=reason,
        correction_requested=False,
        crossed_boundary_sign=None,
        guidance_target_delta_u_rad=None,
        armed_before=armed_before,
        armed_after=armed_after,
        grid_resolution_s=60.0,
        timing_semantics="authoritative propagation output grid; no interpolation",
    )


def test_operational_metrics_separate_correction_to_rearm_and_post_rearm_coast() -> None:
    request = _request()
    ledger = (
        _resource(0.0, 0.01, 1.0, 49.0),
        _resource(180.0, 0.02, 2.0, 48.0),
    )
    trace = (
        _trace(120.0, "rearmed_inside_corridor", armed_before=False, armed_after=True),
        _trace(300.0, "rearmed_inside_corridor", armed_before=False, armed_after=True),
    )
    campaign = ClosedLoopCampaignResult(
        policy=CorrectionPolicy.BOUNDARY_TO_BOUNDARY,
        corridor_half_width_rad=0.1,
        initial_epoch_iso=request.epoch.isoformat(),
        final_epoch_iso=request.epoch.isoformat(),
        elapsed_time_s=360.0,
        correction_count=2,
        coast_propagation_calls=2,
        termination_reason="max-corrections-reached",
        final_policy_armed=False,
        policy_events=(),
        policy_trace=trace,
        authority_attempts=(),
        transitions=(),
        resource_ledger=ledger,
        cumulative_delta_v_m_s=0.02,
        cumulative_propellant_used_kg=2.0,
        controlled_propellant_remaining_kg=48.0,
        controlled_required_reserve_kg=10.0,
        final_request=request,
    )

    metrics = analyze_closed_loop_operations(campaign)

    assert metrics.rearm_settling_available
    assert metrics.rearm_settling_reason is None
    assert metrics.rearm_settling_intervals.seconds.count == 2
    assert metrics.rearm_settling_intervals.seconds.minimum == pytest.approx(120.0)
    assert metrics.rearm_settling_intervals.seconds.mean == pytest.approx(120.0)
    assert metrics.rearm_settling_intervals.seconds.maximum == pytest.approx(120.0)
    assert metrics.post_rearm_coast_intervals.seconds.count == 1
    assert metrics.post_rearm_coast_intervals.seconds.mean == pytest.approx(60.0)
    assert metrics.correction_intervals.seconds.mean == pytest.approx(180.0)
    dumped = metrics.model_dump(mode="json")
    assert dumped["rearm_settling_intervals"]["seconds"]["count"] == 2


def test_metrics_keep_explicit_reason_when_authorized_correction_never_rearms() -> None:
    request = _request()
    ledger = (_resource(0.0, 0.01, 1.0, 49.0),)
    campaign = ClosedLoopCampaignResult(
        policy=CorrectionPolicy.RETURN_TO_CENTER,
        corridor_half_width_rad=0.1,
        initial_epoch_iso=request.epoch.isoformat(),
        final_epoch_iso=request.epoch.isoformat(),
        elapsed_time_s=120.0,
        correction_count=1,
        coast_propagation_calls=1,
        termination_reason="no-next-policy-event-in-coast-horizon",
        final_policy_armed=False,
        policy_events=(),
        policy_trace=(
            _trace(60.0, "disarmed_waiting_for_reentry", armed_before=False, armed_after=False),
        ),
        authority_attempts=(),
        transitions=(),
        resource_ledger=ledger,
        cumulative_delta_v_m_s=0.01,
        cumulative_propellant_used_kg=1.0,
        controlled_propellant_remaining_kg=49.0,
        controlled_required_reserve_kg=10.0,
        final_request=request,
    )

    metrics = analyze_closed_loop_operations(campaign)
    assert not metrics.rearm_settling_available
    assert metrics.rearm_settling_reason == "no-strict-inside-rearm-observed-after-authorized-correction"
    assert metrics.rearm_settling_intervals.seconds.count == 0
