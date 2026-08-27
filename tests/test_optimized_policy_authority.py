from __future__ import annotations

from pathlib import Path

import pytest

from constellation_control.application.run import load_scenario
from constellation_control.control.execution import MPCExecutionPolicy
from constellation_control.control.optimized_policy import evaluate_optimized_correction_policy
from constellation_control.control.phase_target import delta_u_from_damico_roe
from constellation_control.control.policies import CorrectionPolicy, evaluate_correction_policy
from constellation_control.control.policy_execution import build_policy_execution_target
from constellation_control.domain.models import PropagationRequest
from constellation_control.mean_elements.roe import damico_roe
from constellation_control.optimization.operational_policy_search import OperationalPolicyParameters


def _request() -> tuple[PropagationRequest, object]:
    scenario = load_scenario(Path(__file__).parents[1] / "scenarios" / "mvp_45deg.yaml")
    reference = next(sat for sat in scenario.constellation.satellites if sat.role == "reference")
    deputy = next(sat for sat in scenario.constellation.satellites if sat.role == "additional")
    request = PropagationRequest(
        scenario_id=scenario.scenario_id,
        epoch=scenario.epoch,
        frame=scenario.frame,
        time_scale=scenario.time_scale,
        satellites=(reference, deputy),
        maneuvers=(),
        duration_s=scenario.duration_s,
        output_step_s=scenario.output_step_s,
        force_model=scenario.force_model,
        integrator=scenario.integrator,
        seed=scenario.seed,
    )
    return request, scenario.constraints


def _base_policy() -> MPCExecutionPolicy:
    return MPCExecutionPolicy(
        max_abs_impulse_rtn_m_s=(0.2, 0.2, 0.2),
        min_impulse_bit_m_s=1.0e-3,
        trust_tolerances_roe=(1.0e-6, 1.0e-3, 1.0e-6, 1.0e-6, 1.0e-6, 1.0e-6),
        target_roe=(0.0, 0.0, 0.0, 0.0, 0.0, 0.0),
        w_tracking=10.0,
        w_max=0.5,
    )


def _current_delta_u(request: PropagationRequest) -> float:
    reference = next(sat for sat in request.satellites if sat.role == "reference")
    deputy = next(sat for sat in request.satellites if sat.role == "additional")
    return delta_u_from_damico_roe(reference.mean_orbit, damico_roe(reference.mean_orbit, deputy.mean_orbit))


def test_optimized_trigger_can_fire_inside_hard_corridor_without_relabeling() -> None:
    parameters = OperationalPolicyParameters(trigger_fraction=0.5, target_fraction=0.25)
    evidence, next_state = evaluate_optimized_correction_policy(
        "candidate-1",
        parameters,
        delta_u_rad=0.6,
        hard_corridor_half_width_rad=1.0,
    )
    assert evidence.trigger_half_width_rad == pytest.approx(0.5)
    assert evidence.decision.correction_requested is True
    assert evidence.decision.policy == CorrectionPolicy.OPTIMIZED
    assert evidence.decision.corridor_half_width_rad == pytest.approx(1.0)
    assert evidence.decision.crossed_boundary_sign == 1
    assert evidence.decision.guidance_target_delta_u_rad == pytest.approx(-0.25)
    assert next_state.armed is False


def test_optimized_target_fraction_zero_and_one_match_guidance_geometry_not_policy_identity() -> None:
    center, _ = evaluate_optimized_correction_policy(
        "center-like",
        OperationalPolicyParameters(trigger_fraction=0.5, target_fraction=0.0),
        0.6,
        1.0,
    )
    opposite, _ = evaluate_optimized_correction_policy(
        "boundary-like",
        OperationalPolicyParameters(trigger_fraction=0.5, target_fraction=1.0),
        -0.6,
        1.0,
    )
    assert center.decision.guidance_target_delta_u_rad == pytest.approx(0.0)
    assert opposite.decision.guidance_target_delta_u_rad == pytest.approx(1.0)
    assert center.decision.policy == CorrectionPolicy.OPTIMIZED
    assert opposite.decision.policy == CorrectionPolicy.OPTIMIZED


def test_optimized_disarm_and_rearm_use_trigger_threshold_not_hard_corridor() -> None:
    parameters = OperationalPolicyParameters(trigger_fraction=0.5, target_fraction=0.2)
    first, state = evaluate_optimized_correction_policy("candidate", parameters, 0.5, 1.0)
    assert first.decision.correction_requested
    assert state.armed is False

    duplicate, state = evaluate_optimized_correction_policy("candidate", parameters, 0.8, 1.0, state)
    assert duplicate.decision.correction_requested is False
    assert duplicate.decision.reason == "optimized_disarmed_waiting_for_trigger_reentry"
    assert state.armed is False

    rearmed, state = evaluate_optimized_correction_policy("candidate", parameters, 0.49, 1.0, state)
    assert rearmed.decision.reason == "optimized_rearmed_inside_trigger"
    assert state.armed is True


def test_p2_evaluator_refuses_optimized_identity_and_baseline_semantics_remain_available() -> None:
    with pytest.raises(ValueError, match="dedicated optimized"):
        evaluate_correction_policy(CorrectionPolicy.OPTIMIZED, 0.0, 1.0)

    rtc, _ = evaluate_correction_policy(CorrectionPolicy.RETURN_TO_CENTER, 1.0, 1.0)
    b2b, _ = evaluate_correction_policy(CorrectionPolicy.BOUNDARY_TO_BOUNDARY, 1.0, 1.0)
    assert rtc.guidance_target_delta_u_rad == pytest.approx(0.0)
    assert b2b.guidance_target_delta_u_rad == pytest.approx(-1.0)


def test_existing_execution_target_bridge_accepts_optimized_decision_with_hard_corridor() -> None:
    request, constraints = _request()
    current_delta_u = _current_delta_u(request)
    evidence, _ = evaluate_optimized_correction_policy(
        "candidate-existing-bridge",
        OperationalPolicyParameters(trigger_fraction=0.5, target_fraction=0.3),
        current_delta_u,
        constraints.phase_corridor_rad,
    )
    assert evidence.decision.correction_requested
    target = build_policy_execution_target(
        request,
        constraints,
        evidence.decision,
        _base_policy(),
    )
    assert target.guidance_target_delta_u_rad == pytest.approx(evidence.decision.guidance_target_delta_u_rad)
    assert target.execution_policy.target_roe == target.adapted_target_roe


def test_execution_target_bridge_still_rejects_hard_corridor_mismatch() -> None:
    request, constraints = _request()
    current_delta_u = _current_delta_u(request)
    evidence, _ = evaluate_optimized_correction_policy(
        "candidate-mismatch",
        OperationalPolicyParameters(trigger_fraction=0.5, target_fraction=0.3),
        current_delta_u,
        constraints.phase_corridor_rad * 2.0,
    )
    with pytest.raises(ValueError, match="corridor does not match"):
        build_policy_execution_target(request, constraints, evidence.decision, _base_policy())
