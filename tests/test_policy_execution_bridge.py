from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from constellation_control.application.run import load_scenario
from constellation_control.control.execution import MPCExecutionPolicy, ManeuverAuthorityEvidence
from constellation_control.control.phase_target import delta_u_from_damico_roe
from constellation_control.control.policies import CorrectionPolicy, evaluate_correction_policy
from constellation_control.control.policy_execution import (
    authorize_policy_correction,
    build_policy_execution_target,
)
from constellation_control.domain.models import PropagationRequest
from constellation_control.mean_elements.roe import RelativeOrbitalElements, damico_roe, mean_from_damico_roe


def _request(*, nonzero_nodal_offset: bool = False) -> tuple[PropagationRequest, object]:
    scenario = load_scenario(Path(__file__).parents[1] / "scenarios" / "mvp_45deg.yaml")
    reference = next(sat for sat in scenario.constellation.satellites if sat.role == "reference")
    deputy = next(sat for sat in scenario.constellation.satellites if sat.role == "additional")
    if nonzero_nodal_offset:
        relative = RelativeOrbitalElements(
            delta_a=1.0e-4,
            delta_lambda_rad=0.30,
            delta_ex=2.0e-4,
            delta_ey=-3.0e-4,
            delta_ix=4.0e-4,
            delta_iy=0.04,
        )
        deputy = deputy.model_copy(
            update={"mean_orbit": mean_from_damico_roe(reference.mean_orbit, relative)}
        )
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
        target_roe=(9.0, 9.0, 9.0, 9.0, 9.0, 9.0),
        w_tracking=10.0,
        w_max=0.5,
    )


def _current_delta_u(request: PropagationRequest) -> float:
    reference = next(sat for sat in request.satellites if sat.role == "reference")
    deputy = next(sat for sat in request.satellites if sat.role == "additional")
    relative = damico_roe(reference.mean_orbit, deputy.mean_orbit)
    return delta_u_from_damico_roe(reference.mean_orbit, relative)


def _authority(authorized: bool, reason: str) -> ManeuverAuthorityEvidence:
    return ManeuverAuthorityEvidence(
        authorized=authorized,
        reason=reason,
        deputy_id="DEP",
        reference_id="REF",
        first_maneuver=None,
        predicted_next_roe=None,
        replay_next_roe=None,
        trust_error_ratio=None,
        replay_min_pair_distance_m=None,
        propellant_used_kg=0.0,
        propellant_remaining_kg=50.0,
        required_reserve_kg=5.0,
        replay_backend=None,
        replay_backend_metadata={},
        a_matrices=(),
        b_matrices=(),
        disturbances=(),
        mpc_states=(),
        mpc_impulses=(),
        mpc_objective=0.0,
    )


def test_return_to_center_builds_adapted_phase_only_execution_target() -> None:
    request, constraints = _request(nonzero_nodal_offset=True)
    current_delta_u = _current_delta_u(request)
    decision, _ = evaluate_correction_policy(
        CorrectionPolicy.RETURN_TO_CENTER,
        current_delta_u,
        constraints.phase_corridor_rad,
    )
    assert decision.correction_requested

    target = build_policy_execution_target(request, constraints, decision, _base_policy())
    current = target.current_roe
    adapted = target.adapted_target_roe

    assert adapted[0] == current[0]
    assert adapted[2:] == current[2:]
    assert adapted[1] != pytest.approx(decision.guidance_target_delta_u_rad)
    reference = next(sat for sat in request.satellites if sat.role == "reference")
    recovered = delta_u_from_damico_roe(
        reference.mean_orbit,
        RelativeOrbitalElements(*adapted),
    )
    assert recovered == pytest.approx(0.0)
    assert target.execution_policy.target_roe == adapted
    assert target.execution_policy.w_tracking == _base_policy().w_tracking
    assert target.execution_policy.max_abs_impulse_rtn_m_s == _base_policy().max_abs_impulse_rtn_m_s


def test_boundary_to_boundary_preserves_non_phase_coordinates_and_targets_opposite_boundary() -> None:
    request, constraints = _request(nonzero_nodal_offset=True)
    current_delta_u = _current_delta_u(request)
    sign = 1 if current_delta_u >= 0.0 else -1
    observed = sign * max(abs(current_delta_u), constraints.phase_corridor_rad)
    decision, _ = evaluate_correction_policy(
        CorrectionPolicy.BOUNDARY_TO_BOUNDARY,
        observed,
        constraints.phase_corridor_rad,
    )
    if observed != pytest.approx(current_delta_u):
        decision = decision.__class__(
            **{**decision.__dict__, "observed_delta_u_rad": current_delta_u}
        )
    target = build_policy_execution_target(request, constraints, decision, _base_policy())
    reference = next(sat for sat in request.satellites if sat.role == "reference")
    recovered = delta_u_from_damico_roe(
        reference.mean_orbit,
        RelativeOrbitalElements(*target.adapted_target_roe),
    )
    assert recovered == pytest.approx(-sign * constraints.phase_corridor_rad)
    assert target.adapted_target_roe[0] == target.current_roe[0]
    assert target.adapted_target_roe[2:] == target.current_roe[2:]


def test_no_control_never_calls_execution_authority() -> None:
    request, constraints = _request()
    decision, _ = evaluate_correction_policy(
        CorrectionPolicy.NO_CONTROL,
        _current_delta_u(request),
        constraints.phase_corridor_rad,
    )

    class BombPropagator:
        def propagate(self, request):
            raise AssertionError("NO_CONTROL must not call propagation or maneuver authority")

    evidence = authorize_policy_correction(
        BombPropagator(),
        request,
        constraints,
        decision,
        _base_policy(),
        np.asarray([0.0, 60.0]),
        np.asarray([True]),
    )
    assert evidence.sizing_attempted is False
    assert evidence.target is None
    assert evidence.authority is None


def test_bridge_records_rejected_authority_without_authorized_maneuver(monkeypatch) -> None:
    request, constraints = _request(nonzero_nodal_offset=True)
    decision, _ = evaluate_correction_policy(
        CorrectionPolicy.RETURN_TO_CENTER,
        _current_delta_u(request),
        constraints.phase_corridor_rad,
    )
    calls = []

    class FakeController:
        def __init__(self, propagator, policy, *, deputy_id=None):
            calls.append((propagator, policy, deputy_id))

        def authorize_first_maneuver(self, request, constraints, times_s, maneuver_windows):
            return _authority(False, "propellant-reserve-violation")

    monkeypatch.setattr(
        "constellation_control.control.policy_execution.RecedingHorizonMPCController",
        FakeController,
    )
    evidence = authorize_policy_correction(
        object(),
        request,
        constraints,
        decision,
        _base_policy(),
        np.asarray([0.0, 60.0]),
        np.asarray([True]),
    )
    assert evidence.sizing_attempted is True
    assert evidence.target is not None
    assert evidence.authority is not None
    assert evidence.authority.authorized is False
    assert evidence.authority.reason == "propellant-reserve-violation"
    assert evidence.authority.first_maneuver is None
    assert len(calls) == 1


def test_bridge_preserves_authorized_execution_evidence(monkeypatch) -> None:
    request, constraints = _request(nonzero_nodal_offset=True)
    decision, _ = evaluate_correction_policy(
        CorrectionPolicy.RETURN_TO_CENTER,
        _current_delta_u(request),
        constraints.phase_corridor_rad,
    )

    class FakeController:
        def __init__(self, propagator, policy, *, deputy_id=None):
            self.policy = policy

        def authorize_first_maneuver(self, request, constraints, times_s, maneuver_windows):
            return _authority(True, "authorized-by-numerical-replay")

    monkeypatch.setattr(
        "constellation_control.control.policy_execution.RecedingHorizonMPCController",
        FakeController,
    )
    evidence = authorize_policy_correction(
        object(),
        request,
        constraints,
        decision,
        _base_policy(),
        np.asarray([0.0, 60.0]),
        np.asarray([True]),
    )
    assert evidence.sizing_attempted is True
    assert evidence.authority is not None
    assert evidence.authority.authorized is True
    assert evidence.authority.reason == "authorized-by-numerical-replay"


def test_bridge_rejects_stale_policy_decision() -> None:
    request, constraints = _request(nonzero_nodal_offset=True)
    current = _current_delta_u(request)
    decision, _ = evaluate_correction_policy(
        CorrectionPolicy.RETURN_TO_CENTER,
        current,
        constraints.phase_corridor_rad,
    )
    stale = decision.__class__(**{**decision.__dict__, "observed_delta_u_rad": current + 1.0e-3})
    with pytest.raises(ValueError, match="does not match current request mean phase"):
        build_policy_execution_target(request, constraints, stale, _base_policy())
