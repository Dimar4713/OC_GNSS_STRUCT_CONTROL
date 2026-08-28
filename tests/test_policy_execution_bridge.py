from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from constellation_control.application.run import load_scenario
from constellation_control.control.execution import MPCExecutionPolicy, ManeuverAuthorityEvidence
from constellation_control.control.phase_target import delta_u_from_damico_roe
from constellation_control.control.policies import CorrectionPolicy, evaluate_correction_policy
from constellation_control.control.policy_execution import (
    append_authorized_resource_record,
    authorize_policy_correction,
    build_policy_execution_target,
)
from constellation_control.domain.models import (
    ConstraintConfig,
    Maneuver,
    OsculatingState,
    PropagationRequest,
    PropagationResult,
)
from constellation_control.mean_elements.roe import RelativeOrbitalElements, damico_roe, mean_from_damico_roe


def _request(*, nonzero_nodal_offset: bool = False) -> tuple[PropagationRequest, ConstraintConfig]:
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


def _authority(
    authorized: bool,
    reason: str,
    *,
    maneuver: Maneuver | None = None,
) -> ManeuverAuthorityEvidence:
    return ManeuverAuthorityEvidence(
        authorized=authorized,
        reason=reason,
        deputy_id="DEMO-ADD-45",
        reference_id="DEMO-REF",
        first_maneuver=maneuver,
        predicted_next_roe=None,
        replay_next_roe=None,
        trust_error_ratio=0.1 if authorized else None,
        replay_min_pair_distance_m=5000.0 if authorized else None,
        propellant_used_kg=0.025 if authorized else 0.0,
        propellant_remaining_kg=49.975 if authorized else 50.0,
        required_reserve_kg=5.0,
        replay_backend="orekit-numerical-validation" if authorized else None,
        replay_backend_metadata=(
            {
                "orekit_version": "13.1.7",
                "orekit_data_revision": "test-revision",
                "orekit_data_sha256": "1" * 64,
                "gravity_model": "EIGEN-6S",
            }
            if authorized
            else {}
        ),
        a_matrices=(),
        b_matrices=(),
        disturbances=(),
        mpc_states=(),
        mpc_impulses=(),
        mpc_objective=0.0,
    )


class ReplayFixturePropagator:
    def __init__(self) -> None:
        self.calls: list[PropagationRequest] = []

    def propagate(self, request: PropagationRequest) -> PropagationResult:
        self.calls.append(request)
        call_index = len(self.calls)
        mean_orbits = {}
        cartesian_states = {}
        for index, satellite in enumerate(request.satellites):
            second_mean = satellite.mean_orbit.model_copy(
                update={"lambda_rad": satellite.mean_orbit.lambda_rad + call_index * 1.0e-5}
            )
            mean_orbits[satellite.satellite_id] = (satellite.mean_orbit, second_mean)
            offset = 5000.0 * index
            cartesian_states[satellite.satellite_id] = (
                OsculatingState(epoch_s=0.0, r_m=(offset, 0.0, 0.0), v_m_s=(0.0, 0.0, 0.0)),
                OsculatingState(epoch_s=60.0, r_m=(offset, 1.0, 0.0), v_m_s=(0.0, 0.0, 0.0)),
            )
        return PropagationResult(
            backend="orekit-numerical-validation",
            backend_version="13.1.7",
            force_model_fingerprint=request.force_model.fingerprint(),
            backend_metadata={
                "orekit_version": "13.1.7",
                "orekit_data_revision": "test-revision",
                "orekit_data_sha256": "1" * 64,
                "gravity_model": "EIGEN-6S",
            },
            times_s=(0.0, 60.0),
            mean_orbits=mean_orbits,
            cartesian_states=cartesian_states,
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
    decision, _ = evaluate_correction_policy(
        CorrectionPolicy.BOUNDARY_TO_BOUNDARY,
        current_delta_u,
        constraints.phase_corridor_rad,
    )
    assert decision.correction_requested
    target = build_policy_execution_target(request, constraints, decision, _base_policy())
    reference = next(sat for sat in request.satellites if sat.role == "reference")
    recovered = delta_u_from_damico_roe(
        reference.mean_orbit,
        RelativeOrbitalElements(*target.adapted_target_roe),
    )
    expected = -constraints.phase_corridor_rad if current_delta_u > 0.0 else constraints.phase_corridor_rad
    assert recovered == pytest.approx(expected)
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
    assert evidence.transition is None


def test_bridge_records_rejected_authority_without_transition(monkeypatch) -> None:
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
        ReplayFixturePropagator(),
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
    assert evidence.transition is None
    assert len(calls) == 1


def test_authorized_bridge_uses_same_replay_for_continuation_snapshot(monkeypatch) -> None:
    request, constraints = _request(nonzero_nodal_offset=True)
    source_request_dump = request.model_dump(mode="json")
    decision, _ = evaluate_correction_policy(
        CorrectionPolicy.RETURN_TO_CENTER,
        _current_delta_u(request),
        constraints.phase_corridor_rad,
    )
    maneuver = Maneuver(
        satellite_id="DEMO-ADD-45",
        time_s=0.0,
        dv_rtn_m_s=(0.0, -0.02, 0.0),
    )
    probe = Maneuver(
        satellite_id="DEMO-ADD-45",
        time_s=0.0,
        dv_rtn_m_s=(0.0, 0.001, 0.0),
    )

    class FakeController:
        def __init__(self, propagator, policy, *, deputy_id=None):
            self.propagator = propagator

        def authorize_first_maneuver(self, request, constraints, times_s, maneuver_windows):
            # Simulate a finite-difference propagation call first. It must not be
            # mistaken for the final maneuver replay used for continuation.
            self.propagator.propagate(request.model_copy(update={"maneuvers": (probe,)}))
            self.propagator.propagate(request.model_copy(update={"maneuvers": (maneuver,)}))
            return _authority(True, "authorized-by-numerical-replay", maneuver=maneuver)

    monkeypatch.setattr(
        "constellation_control.control.policy_execution.RecedingHorizonMPCController",
        FakeController,
    )
    propagator = ReplayFixturePropagator()
    evidence = authorize_policy_correction(
        propagator,
        request,
        constraints,
        decision,
        _base_policy(),
        np.asarray([0.0, 60.0]),
        np.asarray([True]),
    )

    assert len(propagator.calls) == 2
    assert evidence.authority is not None and evidence.authority.authorized
    assert evidence.transition is not None
    transition = evidence.transition
    assert transition.continuation_sample_index == 1
    assert transition.continuation_time_s == 60.0
    assert transition.source_replay_times_s == (0.0, 60.0)
    assert transition.controlled_propellant_remaining_kg == evidence.authority.propellant_remaining_kg
    controlled = next(sat for sat in request.satellites if sat.satellite_id == transition.controlled_satellite_id)
    assert transition.controlled_total_mass_kg == pytest.approx(
        controlled.spacecraft.dry_mass_kg + evidence.authority.propellant_remaining_kg
    )
    assert transition.event_delta_v_m_s == pytest.approx(0.02)
    assert transition.event_propellant_used_kg == evidence.authority.propellant_used_kg
    assert transition.backend == "orekit-numerical-validation"
    assert transition.force_model_fingerprint == request.force_model.fingerprint()
    assert transition.integrator == request.integrator
    assert transition.frame == request.frame
    assert transition.time_scale == request.time_scale
    assert len(transition.spacecraft_states) == len(request.satellites)

    # The second captured replay is the maneuver authority replay. Its fixture
    # increments lambda by 2e-5, while the first probe call increments by 1e-5.
    for state, source_satellite in zip(transition.spacecraft_states, request.satellites, strict=True):
        assert state.mean_orbit.lambda_rad == pytest.approx(source_satellite.mean_orbit.lambda_rad + 2.0e-5)
        assert state.cartesian_state is not None
        assert state.cartesian_state.epoch_s == 60.0

    assert request.model_dump(mode="json") == source_request_dump
    json.dumps(transition.model_dump(mode="json"))


def test_authorized_attempt_appends_resource_record_without_repropagation(monkeypatch) -> None:
    request, constraints = _request(nonzero_nodal_offset=True)
    decision, _ = evaluate_correction_policy(
        CorrectionPolicy.RETURN_TO_CENTER,
        _current_delta_u(request),
        constraints.phase_corridor_rad,
    )
    maneuver = Maneuver(
        satellite_id="DEMO-ADD-45",
        time_s=0.0,
        dv_rtn_m_s=(0.0, -0.02, 0.0),
    )

    class FakeController:
        def __init__(self, propagator, policy, *, deputy_id=None):
            self.propagator = propagator

        def authorize_first_maneuver(self, request, constraints, times_s, maneuver_windows):
            self.propagator.propagate(request.model_copy(update={"maneuvers": (maneuver,)}))
            return _authority(True, "authorized-by-numerical-replay", maneuver=maneuver)

    monkeypatch.setattr(
        "constellation_control.control.policy_execution.RecedingHorizonMPCController",
        FakeController,
    )
    propagator = ReplayFixturePropagator()
    attempt = authorize_policy_correction(
        propagator,
        request,
        constraints,
        decision,
        _base_policy(),
        np.asarray([0.0, 60.0]),
        np.asarray([True]),
    )
    calls_after_authority = len(propagator.calls)
    ledger = append_authorized_resource_record((), attempt, event_time_s=120.0)

    assert len(propagator.calls) == calls_after_authority == 1
    assert len(ledger) == 1
    record = ledger[0]
    assert record.policy == CorrectionPolicy.RETURN_TO_CENTER.value
    assert record.delta_v_m_s == pytest.approx(0.02)
    assert record.cumulative_delta_v_m_s == pytest.approx(0.02)
    assert record.propellant_used_kg == pytest.approx(0.025)
    assert record.cumulative_propellant_used_kg == pytest.approx(0.025)
    assert record.propellant_remaining_kg == pytest.approx(49.975)
    assert record.replay_backend == "orekit-numerical-validation"
    assert record.force_model_fingerprint == request.force_model.fingerprint()
    json.dumps(record.model_dump(mode="json"))


def test_rejected_attempt_does_not_append_resource_record() -> None:
    request, constraints = _request(nonzero_nodal_offset=True)
    decision, _ = evaluate_correction_policy(
        CorrectionPolicy.RETURN_TO_CENTER,
        _current_delta_u(request),
        constraints.phase_corridor_rad,
    )
    from constellation_control.control.policy_execution import PolicyManeuverAttemptEvidence

    attempt = PolicyManeuverAttemptEvidence(
        decision=decision,
        sizing_attempted=True,
        target=None,
        authority=_authority(False, "propellant-reserve-violation"),
        transition=None,
    )
    assert append_authorized_resource_record((), attempt, event_time_s=0.0) == ()


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
