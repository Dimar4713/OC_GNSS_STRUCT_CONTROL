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
from constellation_control.optimization.hybrid import ScreeningEventKind, ValidationOutcomeKind
from constellation_control.optimization.hybrid_execution import authoritative_anchor_from_transition
from constellation_control.optimization.operational_policy_search import OperationalPolicyParameters
from constellation_control.optimization.optimized_hybrid_execution import (
    discover_optimized_trigger_bracket,
    validate_optimized_trigger_window,
)


def _request() -> tuple[PropagationRequest, object]:
    scenario = load_scenario(Path(__file__).parents[1] / "scenarios" / "mvp_45deg.yaml")
    return (
        PropagationRequest(
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
        ),
        scenario.constraints,
    )


def _phase_result(request: PropagationRequest, phases: tuple[float, ...], *, backend: str) -> PropagationResult:
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
            TransitionSpacecraftState(satellite_id=reference.satellite_id, mean_orbit=reference.mean_orbit),
            TransitionSpacecraftState(satellite_id=deputy.satellite_id, mean_orbit=deputy.mean_orbit),
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


def _screening(request: PropagationRequest, hard: float):
    reference_id, deputy_id = _pair_ids(request)
    parameters = OperationalPolicyParameters(trigger_fraction=0.5, target_fraction=0.25)
    screening = discover_optimized_trigger_bracket(
        _phase_result(request, (0.0, 0.0, 0.5 * hard), backend="mean-screening"),
        strategy_id="optimized-A",
        candidate_id="candidate-A",
        parameters=parameters,
        reference_id=reference_id,
        deputy_id=deputy_id,
        hard_corridor_half_width_rad=hard,
        initial_policy_state=CorrectionPolicyState(),
        output_step_s=60.0,
        screening_config_identity="optimized-screen-v1",
    )
    assert screening is not None
    return screening, parameters, reference_id, deputy_id


def test_screening_optimized_trigger_is_explicit_and_can_be_inside_hard_corridor() -> None:
    request, constraints = _request()
    hard = constraints.phase_corridor_rad
    screening, _, _, _ = _screening(request, hard)
    assert screening.bracket.event_kind == ScreeningEventKind.OPTIMIZED_TRIGGER
    assert screening.trigger_half_width_rad == pytest.approx(0.5 * hard)
    assert screening.bracket.predicted_state_coordinate == pytest.approx(0.5 * hard)
    assert abs(screening.bracket.predicted_state_coordinate) < hard
    assert "phase-boundary" not in screening.bracket.event_kind.value


def test_screening_t120_optimized_trigger_shifts_to_authoritative_t180_with_one_replay() -> None:
    request, constraints = _request()
    hard = constraints.phase_corridor_rad
    screening, parameters, reference_id, deputy_id = _screening(request, hard)
    assert screening.bracket.predicted_time_s == pytest.approx(120.0)

    transition = _transition(request)
    anchor = authoritative_anchor_from_transition(transition, anchor_time_s=60.0, source_evidence_id="transition-1")

    class OneReplayPropagator:
        def __init__(self) -> None:
            self.calls = 0

        def propagate(self, validation_request: PropagationRequest) -> PropagationResult:
            self.calls += 1
            return _phase_result(
                validation_request,
                (0.0, 0.0, 0.5 * hard),
                backend="orekit-numerical-validation",
            )

    propagator = OneReplayPropagator()
    result = validate_optimized_trigger_window(
        propagator,
        request,
        transition,
        anchor,
        screening,
        reference_id=reference_id,
        deputy_id=deputy_id,
        parameters=parameters,
        initial_policy_state=CorrectionPolicyState(),
        validation_output_step_s=60.0,
        authority_config_identity="optimized-hf-v1",
    )
    assert propagator.calls == 1
    assert result.evidence.outcome == ValidationOutcomeKind.SHIFTED
    assert result.evidence.authoritative_event_time_s == pytest.approx(180.0)
    assert result.evidence.timing_error_s == pytest.approx(60.0)
    assert result.optimized_decision is not None
    assert result.optimized_decision.decision.policy == CorrectionPolicy.OPTIMIZED
    assert result.optimized_decision.decision.corridor_half_width_rad == pytest.approx(hard)


def test_authoritative_optimized_window_can_report_event_absent() -> None:
    request, constraints = _request()
    hard = constraints.phase_corridor_rad
    screening, parameters, reference_id, deputy_id = _screening(request, hard)
    transition = _transition(request)
    anchor = authoritative_anchor_from_transition(transition, anchor_time_s=60.0, source_evidence_id="transition-1")

    class NoEventPropagator:
        def propagate(self, validation_request: PropagationRequest) -> PropagationResult:
            return _phase_result(validation_request, (0.0, 0.0, 0.0), backend="orekit-numerical-validation")

    result = validate_optimized_trigger_window(
        NoEventPropagator(),
        request,
        transition,
        anchor,
        screening,
        reference_id=reference_id,
        deputy_id=deputy_id,
        parameters=parameters,
        initial_policy_state=CorrectionPolicyState(),
        validation_output_step_s=60.0,
        authority_config_identity="optimized-hf-v1",
    )
    assert result.evidence.outcome == ValidationOutcomeKind.EVENT_ABSENT
    assert result.evidence.authoritative_event_time_s is None
    assert result.optimized_decision is None


def test_tampered_anchor_fails_before_optimized_authoritative_propagation() -> None:
    request, constraints = _request()
    screening, parameters, reference_id, deputy_id = _screening(request, constraints.phase_corridor_rad)
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
        validate_optimized_trigger_window(
            BombPropagator(),
            request,
            transition,
            anchor,
            screening,
            reference_id=reference_id,
            deputy_id=deputy_id,
            parameters=parameters,
            initial_policy_state=CorrectionPolicyState(),
            validation_output_step_s=60.0,
            authority_config_identity="optimized-hf-v1",
        )
