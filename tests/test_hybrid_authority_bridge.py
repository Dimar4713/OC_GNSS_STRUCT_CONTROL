from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from constellation_control.application.run import load_scenario
from constellation_control.control.execution import MPCExecutionPolicy, ManeuverAuthorityEvidence
from constellation_control.control.policies import CorrectionPolicy, CorrectionPolicyState
from constellation_control.control.policy_execution import PolicyManeuverAttemptEvidence
from constellation_control.control.transition import (
    AuthoritativeTransitionSnapshot,
    TransitionSpacecraftState,
)
from constellation_control.domain.models import Maneuver, PropagationRequest, PropagationResult
from constellation_control.mean_elements.roe import RelativeOrbitalElements, mean_from_damico_roe
from constellation_control.optimization.hybrid import ValidationOutcomeKind
from constellation_control.optimization.hybrid_authority import authorize_validated_phase_event
from constellation_control.optimization.hybrid_execution import (
    authoritative_anchor_from_transition,
    discover_phase_boundary_bracket,
    validate_phase_boundary_window_with_state,
)
from constellation_control.optimization.operations import CredibilityState


def _request() -> tuple[PropagationRequest, object]:
    scenario = load_scenario(Path(__file__).parents[1] / "scenarios" / "mvp_45deg.yaml")
    return PropagationRequest(
        scenario_id=scenario.scenario_id,
        epoch=scenario.epoch,
        frame=scenario.frame,
        time_scale=scenario.time_scale,
        satellites=scenario.constellation.satellites,
        duration_s=180.0,
        output_step_s=60.0,
        force_model=scenario.force_model,
        integrator=scenario.integrator,
        seed=scenario.seed,
    ), scenario.constraints


def _phase_result(request: PropagationRequest, phases: tuple[float, ...], backend: str) -> PropagationResult:
    reference = next(sat for sat in request.satellites if sat.role == "reference")
    deputy = next(sat for sat in request.satellites if sat.role == "additional")
    return PropagationResult(
        backend=backend,
        backend_version="test",
        force_model_fingerprint=request.force_model.fingerprint(),
        times_s=tuple(float(index * 60) for index in range(len(phases))),
        mean_orbits={
            reference.satellite_id: tuple(reference.mean_orbit for _ in phases),
            deputy.satellite_id: tuple(
                mean_from_damico_roe(
                    reference.mean_orbit,
                    RelativeOrbitalElements(0.0, phase, 0.0, 0.0, 0.0, 0.0),
                )
                for phase in phases
            ),
        },
        cartesian_states={},
    )


def _transition(request: PropagationRequest) -> AuthoritativeTransitionSnapshot:
    reference = next(sat for sat in request.satellites if sat.role == "reference")
    deputy = next(sat for sat in request.satellites if sat.role == "additional")
    return AuthoritativeTransitionSnapshot(
        continuation_sample_index=1,
        continuation_time_s=60.0,
        source_replay_times_s=(0.0, 60.0),
        controlled_satellite_id=deputy.satellite_id,
        reference_id=reference.satellite_id,
        spacecraft_states=tuple(
            TransitionSpacecraftState(satellite_id=sat.satellite_id, mean_orbit=sat.mean_orbit)
            for sat in request.satellites
        ),
        controlled_propellant_remaining_kg=deputy.spacecraft.propellant_mass_kg,
        controlled_total_mass_kg=deputy.spacecraft.initial_mass_kg,
        event_delta_v_m_s=0.01,
        event_propellant_used_kg=0.0,
        force_model_fingerprint=request.force_model.fingerprint(),
        backend="orekit-numerical-validation",
        backend_version="13.1.7",
        backend_metadata={},
        frame=request.frame,
        time_scale=request.time_scale,
        integrator=request.integrator,
    )


def _window(*, event_present: bool = True):
    request, constraints = _request()
    deputy = next(sat for sat in request.satellites if sat.role == "additional")
    assert deputy.reference_id is not None
    half = constraints.phase_corridor_rad
    screening = discover_phase_boundary_bracket(
        _phase_result(request, (0.0, 0.0, half), "mean-screening"),
        strategy_id="candidate-A",
        reference_id=deputy.reference_id,
        deputy_id=deputy.satellite_id,
        policy=CorrectionPolicy.BOUNDARY_TO_BOUNDARY,
        corridor_half_width_rad=half,
        initial_policy_state=CorrectionPolicyState(),
        output_step_s=60.0,
        screening_config_identity="screen-v1",
    )
    assert screening is not None
    transition = _transition(request)
    anchor = authoritative_anchor_from_transition(
        transition,
        anchor_time_s=60.0,
        source_evidence_id="transition-1",
    )

    class WindowPropagator:
        def propagate(self, validation_request: PropagationRequest) -> PropagationResult:
            phases = (0.0, 0.0, half) if event_present else (0.0, 0.0, 0.0)
            return _phase_result(validation_request, phases, "orekit-numerical-validation")

    window = validate_phase_boundary_window_with_state(
        WindowPropagator(),
        request,
        transition,
        anchor,
        screening,
        reference_id=deputy.reference_id,
        deputy_id=deputy.satellite_id,
        policy=CorrectionPolicy.BOUNDARY_TO_BOUNDARY,
        corridor_half_width_rad=half,
        initial_policy_state=CorrectionPolicyState(),
        validation_output_step_s=60.0,
        authority_config_identity="hf-v1",
    )
    return window, constraints, deputy.satellite_id


def _execution_policy() -> MPCExecutionPolicy:
    return MPCExecutionPolicy(
        max_abs_impulse_rtn_m_s=(0.2, 0.2, 0.2),
        min_impulse_bit_m_s=1.0e-3,
        trust_tolerances_roe=(1.0e-6, 1.0e-3, 1.0e-6, 1.0e-6, 1.0e-6, 1.0e-6),
    )


def _attempt(request: PropagationRequest, decision, constraints, *, authorized: bool):
    deputy = next(sat for sat in request.satellites if sat.role == "additional")
    reference = next(sat for sat in request.satellites if sat.role == "reference")
    remaining = 40.0 if authorized else 9.0
    reserve = 10.0
    maneuver = Maneuver(
        satellite_id=deputy.satellite_id,
        time_s=0.0,
        dv_rtn_m_s=(0.0, 0.02, 0.0),
    )
    authority = ManeuverAuthorityEvidence(
        authorized=authorized,
        reason="authorized-by-numerical-replay" if authorized else "propellant-reserve-violation",
        deputy_id=deputy.satellite_id,
        reference_id=reference.satellite_id,
        first_maneuver=maneuver if authorized else None,
        predicted_next_roe=None,
        replay_next_roe=None,
        trust_error_ratio=0.2,
        replay_min_pair_distance_m=constraints.min_pair_distance_m + 1000.0,
        propellant_used_kg=1.0,
        propellant_remaining_kg=remaining,
        required_reserve_kg=reserve,
        replay_backend="orekit-numerical-validation",
        replay_backend_metadata={},
        a_matrices=(),
        b_matrices=(),
        disturbances=(),
        mpc_states=(),
        mpc_impulses=(),
        mpc_objective=1.0,
    )
    transition = None
    if authorized:
        transition = AuthoritativeTransitionSnapshot(
            continuation_sample_index=1,
            continuation_time_s=60.0,
            source_replay_times_s=(0.0, 60.0),
            controlled_satellite_id=deputy.satellite_id,
            reference_id=reference.satellite_id,
            spacecraft_states=tuple(
                TransitionSpacecraftState(satellite_id=sat.satellite_id, mean_orbit=sat.mean_orbit)
                for sat in request.satellites
            ),
            controlled_propellant_remaining_kg=remaining,
            controlled_total_mass_kg=deputy.spacecraft.dry_mass_kg + remaining,
            event_delta_v_m_s=0.02,
            event_propellant_used_kg=1.0,
            force_model_fingerprint=request.force_model.fingerprint(),
            backend="orekit-numerical-validation",
            backend_version="13.1.7",
            backend_metadata={},
            frame=request.frame,
            time_scale=request.time_scale,
            integrator=request.integrator,
        )
    return PolicyManeuverAttemptEvidence(decision, True, None, authority, transition)


def test_authorized_event_uses_existing_bridge_and_exposes_positive_hard_margins(monkeypatch) -> None:
    window, constraints, deputy_id = _window()
    calls = []

    def fake_authorize(propagator, request, constraints_arg, decision, base_policy, times, windows, *, deputy_id=None):
        del propagator, base_policy, times, windows
        calls.append((request, decision, deputy_id))
        return _attempt(request, decision, constraints_arg, authorized=True)

    monkeypatch.setattr(
        "constellation_control.optimization.hybrid_authority.authorize_policy_correction",
        fake_authorize,
    )
    result = authorize_validated_phase_event(
        object(),
        window,
        constraints,
        _execution_policy(),
        np.asarray([0.0, 60.0]),
        np.asarray([True]),
        deputy_id=deputy_id,
    )

    assert len(calls) == 1
    assert result.receipt.authorized
    assert result.receipt.resulting_credibility_state == CredibilityState.AUTHORITATIVELY_VALIDATED_CANDIDATE
    margins = {item.name: item.margin for item in result.receipt.hard_constraints}
    assert margins["propellant_reserve_margin"] == pytest.approx(30.0)
    assert margins["fleet_minimum_distance_margin"] == pytest.approx(1000.0)
    assert margins["numerical_trust_margin"] == pytest.approx(0.8)
    assert margins["numerical_authority_authorized"] == pytest.approx(0.0)
    assert result.receipt.event_validation.outcome == ValidationOutcomeKind.SHIFTED
    assert result.receipt.event_validation.authoritative_event_time_s == pytest.approx(180.0)
    assert result.attempt is not None
    assert result.event_request is not None


def test_real_shifted_event_is_retained_when_propellant_margin_rejects_candidate(monkeypatch) -> None:
    window, constraints, deputy_id = _window()

    def fake_authorize(propagator, request, constraints_arg, decision, base_policy, times, windows, *, deputy_id=None):
        del propagator, base_policy, times, windows, deputy_id
        return _attempt(request, decision, constraints_arg, authorized=False)

    monkeypatch.setattr(
        "constellation_control.optimization.hybrid_authority.authorize_policy_correction",
        fake_authorize,
    )
    result = authorize_validated_phase_event(
        object(),
        window,
        constraints,
        _execution_policy(),
        np.asarray([0.0, 60.0]),
        np.asarray([True]),
        deputy_id=deputy_id,
    )

    assert result.receipt.event_validation.outcome == ValidationOutcomeKind.SHIFTED
    assert result.receipt.event_validation.authoritative_event_time_s == pytest.approx(180.0)
    assert result.receipt.resulting_credibility_state == CredibilityState.REJECTED_BY_AUTHORITY
    margins = {item.name: item.margin for item in result.receipt.hard_constraints}
    assert margins["propellant_reserve_margin"] == pytest.approx(-1.0)
    assert margins["numerical_authority_authorized"] < 0.0
    restored = type(result.receipt).model_validate_json(result.receipt.model_dump_json())
    assert restored == result.receipt


def test_absent_authoritative_event_does_not_call_mpc_authority(monkeypatch) -> None:
    window, constraints, deputy_id = _window(event_present=False)

    def bomb(*args, **kwargs):
        raise AssertionError("event-absent validation must not call correction authority")

    monkeypatch.setattr(
        "constellation_control.optimization.hybrid_authority.authorize_policy_correction",
        bomb,
    )
    result = authorize_validated_phase_event(
        object(),
        window,
        constraints,
        _execution_policy(),
        np.asarray([0.0, 60.0]),
        np.asarray([True]),
        deputy_id=deputy_id,
    )

    assert not result.receipt.authority_attempted
    assert not result.receipt.authorized
    assert result.receipt.resulting_credibility_state == CredibilityState.REJECTED_BY_AUTHORITY
    assert result.receipt.event_validation.outcome == ValidationOutcomeKind.EVENT_ABSENT
