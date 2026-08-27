from __future__ import annotations

from pathlib import Path

import pytest

from constellation_control.application.run import load_scenario
from constellation_control.control.policies import CorrectionPolicy, CorrectionPolicyState
from constellation_control.control.transition import (
    AuthoritativeTransitionSnapshot,
    TransitionSpacecraftState,
)
from constellation_control.domain.models import PropagationRequest, PropagationResult
from constellation_control.mean_elements.roe import RelativeOrbitalElements, mean_from_damico_roe
from constellation_control.optimization.hybrid import ValidationOutcomeKind
from constellation_control.optimization.hybrid_execution import (
    authoritative_anchor_from_transition,
    discover_phase_boundary_bracket,
    validate_phase_boundary_window,
)


def _request() -> tuple[PropagationRequest, object]:
    scenario = load_scenario(Path(__file__).parents[1] / "scenarios" / "mvp_45deg.yaml")
    request = PropagationRequest(
        scenario_id=scenario.scenario_id,
        epoch=scenario.epoch,
        frame=scenario.frame,
        time_scale=scenario.time_scale,
        satellites=scenario.constellation.satellites,
        maneuvers=(),
        duration_s=180.0,
        output_step_s=60.0,
        force_model=scenario.force_model,
        integrator=scenario.integrator,
        seed=scenario.seed,
    )
    return request, scenario.constraints


def _phase_result(
    request: PropagationRequest,
    phases: tuple[float, ...],
    *,
    backend: str,
) -> PropagationResult:
    reference = next(sat for sat in request.satellites if sat.role == "reference")
    deputy = next(sat for sat in request.satellites if sat.role == "additional")
    return PropagationResult(
        backend=backend,
        backend_version="test",
        force_model_fingerprint=request.force_model.fingerprint(),
        backend_metadata={},
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
        spacecraft_states=(
            TransitionSpacecraftState(
                satellite_id=reference.satellite_id,
                mean_orbit=reference.mean_orbit,
            ),
            TransitionSpacecraftState(
                satellite_id=deputy.satellite_id,
                mean_orbit=deputy.mean_orbit,
            ),
        ),
        controlled_propellant_remaining_kg=deputy.spacecraft.propellant_mass_kg,
        controlled_total_mass_kg=deputy.spacecraft.initial_mass_kg,
        event_delta_v_m_s=0.01,
        event_propellant_used_kg=0.0,
        force_model_fingerprint=request.force_model.fingerprint(),
        backend="orekit-numerical-validation",
        backend_version="13.1.7",
        backend_metadata={"authority": "synthetic-test"},
        frame=request.frame,
        time_scale=request.time_scale,
        integrator=request.integrator,
    )


def _pair_ids(request: PropagationRequest) -> tuple[str, str]:
    deputy = next(sat for sat in request.satellites if sat.role == "additional")
    assert deputy.reference_id is not None
    return deputy.reference_id, deputy.satellite_id


def test_screening_t120_is_authoritatively_shifted_to_t180_with_one_replay() -> None:
    request, constraints = _request()
    reference_id, deputy_id = _pair_ids(request)
    half_width = constraints.phase_corridor_rad
    screening_result = _phase_result(
        request,
        (0.0, 0.0, half_width),
        backend="mean-screening",
    )
    bracket = discover_phase_boundary_bracket(
        screening_result,
        strategy_id="candidate-A",
        reference_id=reference_id,
        deputy_id=deputy_id,
        policy=CorrectionPolicy.BOUNDARY_TO_BOUNDARY,
        corridor_half_width_rad=half_width,
        initial_policy_state=CorrectionPolicyState(),
        output_step_s=60.0,
        screening_config_identity="screen-v1",
    )
    assert bracket is not None
    assert bracket.predicted_time_s == pytest.approx(120.0)
    assert bracket.bracket_start_s == pytest.approx(60.0)
    assert bracket.bracket_end_s == pytest.approx(180.0)

    transition = _transition(request)
    anchor = authoritative_anchor_from_transition(
        transition,
        anchor_time_s=60.0,
        source_evidence_id="transition-1",
    )

    class OneReplayPropagator:
        def __init__(self) -> None:
            self.calls = 0

        def propagate(self, validation_request: PropagationRequest) -> PropagationResult:
            self.calls += 1
            assert validation_request.duration_s == pytest.approx(120.0)
            return _phase_result(
                validation_request,
                (0.0, 0.0, half_width),
                backend="orekit-numerical-validation",
            )

    propagator = OneReplayPropagator()
    evidence = validate_phase_boundary_window(
        propagator,
        request,
        transition,
        anchor,
        bracket,
        reference_id=reference_id,
        deputy_id=deputy_id,
        policy=CorrectionPolicy.BOUNDARY_TO_BOUNDARY,
        corridor_half_width_rad=half_width,
        initial_policy_state=CorrectionPolicyState(),
        validation_output_step_s=60.0,
        authority_config_identity="hf-v1",
    )

    assert propagator.calls == 1
    assert evidence.outcome == ValidationOutcomeKind.SHIFTED
    assert evidence.screening.predicted_time_s == pytest.approx(120.0)
    assert evidence.authoritative_event_time_s == pytest.approx(180.0)
    assert evidence.timing_error_s == pytest.approx(60.0)
    assert evidence.authority_backend == "orekit-numerical-validation"


def test_authoritative_window_can_report_screened_event_absent() -> None:
    request, constraints = _request()
    reference_id, deputy_id = _pair_ids(request)
    half_width = constraints.phase_corridor_rad
    bracket = discover_phase_boundary_bracket(
        _phase_result(request, (0.0, 0.0, half_width), backend="mean-screening"),
        strategy_id="candidate-A",
        reference_id=reference_id,
        deputy_id=deputy_id,
        policy=CorrectionPolicy.RETURN_TO_CENTER,
        corridor_half_width_rad=half_width,
        initial_policy_state=CorrectionPolicyState(),
        output_step_s=60.0,
        screening_config_identity="screen-v1",
    )
    assert bracket is not None
    transition = _transition(request)
    anchor = authoritative_anchor_from_transition(
        transition,
        anchor_time_s=60.0,
        source_evidence_id="transition-1",
    )

    class NoEventPropagator:
        def __init__(self) -> None:
            self.calls = 0

        def propagate(self, validation_request: PropagationRequest) -> PropagationResult:
            self.calls += 1
            return _phase_result(
                validation_request,
                (0.0, 0.0, 0.0),
                backend="orekit-numerical-validation",
            )

    propagator = NoEventPropagator()
    evidence = validate_phase_boundary_window(
        propagator,
        request,
        transition,
        anchor,
        bracket,
        reference_id=reference_id,
        deputy_id=deputy_id,
        policy=CorrectionPolicy.RETURN_TO_CENTER,
        corridor_half_width_rad=half_width,
        initial_policy_state=CorrectionPolicyState(),
        validation_output_step_s=60.0,
        authority_config_identity="hf-v1",
    )

    assert propagator.calls == 1
    assert evidence.outcome == ValidationOutcomeKind.EVENT_ABSENT
    assert evidence.authoritative_event_time_s is None
    assert evidence.timing_error_s is None
    assert evidence.authority_evidence_id is not None


def test_tampered_anchor_fails_before_authoritative_propagation() -> None:
    request, constraints = _request()
    reference_id, deputy_id = _pair_ids(request)
    half_width = constraints.phase_corridor_rad
    bracket = discover_phase_boundary_bracket(
        _phase_result(request, (0.0, 0.0, half_width), backend="mean-screening"),
        strategy_id="candidate-A",
        reference_id=reference_id,
        deputy_id=deputy_id,
        policy=CorrectionPolicy.BOUNDARY_TO_BOUNDARY,
        corridor_half_width_rad=half_width,
        initial_policy_state=CorrectionPolicyState(),
        output_step_s=60.0,
        screening_config_identity="screen-v1",
    )
    assert bracket is not None
    transition = _transition(request)
    anchor = authoritative_anchor_from_transition(
        transition,
        anchor_time_s=60.0,
        source_evidence_id="transition-1",
    ).model_copy(update={"state_digest": "tampered"})

    class BombPropagator:
        def propagate(self, validation_request: PropagationRequest) -> PropagationResult:
            raise AssertionError("tampered anchor must fail before propagation")

    with pytest.raises(ValueError, match="state digest"):
        validate_phase_boundary_window(
            BombPropagator(),
            request,
            transition,
            anchor,
            bracket,
            reference_id=reference_id,
            deputy_id=deputy_id,
            policy=CorrectionPolicy.BOUNDARY_TO_BOUNDARY,
            corridor_half_width_rad=half_width,
            initial_policy_state=CorrectionPolicyState(),
            validation_output_step_s=60.0,
            authority_config_identity="hf-v1",
        )
