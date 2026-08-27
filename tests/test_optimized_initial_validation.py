from __future__ import annotations

from pathlib import Path

import pytest

from constellation_control.application.run import load_scenario
from constellation_control.control.policies import CorrectionPolicyState
from constellation_control.domain.models import PropagationRequest, PropagationResult
from constellation_control.optimization.hybrid import StateAnchorKind, ValidationOutcomeKind
from constellation_control.optimization.operational_policy_search import OperationalPolicyParameters
from constellation_control.optimization.optimized_hybrid_execution import discover_optimized_trigger_bracket
from constellation_control.optimization.optimized_initial_validation import validate_initial_optimized_trigger_replay


def _scenario_path() -> Path:
    return Path(__file__).parents[1] / "scenarios" / "orekit_validation_smoke.yaml"


def _request() -> PropagationRequest:
    scenario = load_scenario(_scenario_path())
    return PropagationRequest(
        scenario_id=scenario.scenario_id,
        epoch=scenario.epoch,
        frame=scenario.frame,
        time_scale=scenario.time_scale,
        satellites=scenario.constellation.satellites,
        maneuvers=(),
        duration_s=120.0,
        output_step_s=60.0,
        force_model=scenario.force_model,
        integrator=scenario.integrator,
        seed=42,
    )


def _result(*, backend: str, inside_trigger: bool = False, fingerprint: str | None = None) -> PropagationResult:
    scenario = load_scenario(_scenario_path())
    ref, dep = scenario.constellation.satellites
    deputy = dep.mean_orbit.model_copy(update={"lambda_rad": 0.05}) if inside_trigger else dep.mean_orbit
    return PropagationResult(
        backend=backend,
        backend_version="test",
        force_model_fingerprint=fingerprint or scenario.force_model.fingerprint(),
        times_s=(0.0, 60.0),
        mean_orbits={
            ref.satellite_id: (ref.mean_orbit, ref.mean_orbit),
            dep.satellite_id: (deputy, deputy),
        },
        cartesian_states={},
    )


def _screening():
    parameters = OperationalPolicyParameters(trigger_fraction=0.5, target_fraction=0.0)
    bracket = discover_optimized_trigger_bracket(
        _result(backend="synthetic-screening-test"),
        strategy_id="optimized-candidate-test",
        candidate_id="candidate-test",
        parameters=parameters,
        reference_id="SYNTH-REF",
        deputy_id="SYNTH-ADD-45",
        hard_corridor_half_width_rad=0.2,
        initial_policy_state=CorrectionPolicyState(),
        output_step_s=60.0,
        screening_config_identity="screening-config-test",
    )
    assert bracket is not None
    return parameters, bracket


class StubPropagator:
    def __init__(self, result: PropagationResult) -> None:
        self.result = result
        self.requests: list[PropagationRequest] = []

    def propagate(self, request: PropagationRequest) -> PropagationResult:
        self.requests.append(request)
        return self.result


def test_first_optimized_event_uses_authoritative_replay_anchor() -> None:
    parameters, screening = _screening()
    propagator = StubPropagator(_result(backend="orekit-numerical-test"))
    result = validate_initial_optimized_trigger_replay(
        propagator,
        _request(),
        screening,
        reference_id="SYNTH-REF",
        deputy_id="SYNTH-ADD-45",
        parameters=parameters,
        initial_policy_state=CorrectionPolicyState(),
        validation_output_step_s=60.0,
        authority_config_identity="authority-config-test",
    )

    assert result.evidence.outcome == ValidationOutcomeKind.CONFIRMED
    assert result.evidence.state_anchor is not None
    assert result.evidence.state_anchor.kind == StateAnchorKind.AUTHORITATIVE_REPLAY
    assert result.evidence.state_anchor.anchor_time_s == 0.0
    assert result.event is not None
    assert result.optimized_decision is not None
    assert len(propagator.requests) == 1
    assert propagator.requests[0].maneuvers == ()


def test_initial_numerical_replay_can_reject_screening_event_as_absent() -> None:
    parameters, screening = _screening()
    result = validate_initial_optimized_trigger_replay(
        StubPropagator(_result(backend="orekit-numerical-test", inside_trigger=True)),
        _request(),
        screening,
        reference_id="SYNTH-REF",
        deputy_id="SYNTH-ADD-45",
        parameters=parameters,
        initial_policy_state=CorrectionPolicyState(),
        validation_output_step_s=60.0,
        authority_config_identity="authority-config-test",
    )

    assert result.evidence.outcome == ValidationOutcomeKind.EVENT_ABSENT
    assert result.evidence.state_anchor is not None
    assert result.evidence.state_anchor.kind == StateAnchorKind.AUTHORITATIVE_REPLAY
    assert result.event is None
    assert result.optimized_decision is None


def test_initial_numerical_replay_rejects_fingerprint_mismatch() -> None:
    parameters, screening = _screening()
    with pytest.raises(ValueError, match="fingerprint does not match"):
        validate_initial_optimized_trigger_replay(
            StubPropagator(_result(backend="orekit-numerical-test", fingerprint="0" * 64)),
            _request(),
            screening,
            reference_id="SYNTH-REF",
            deputy_id="SYNTH-ADD-45",
            parameters=parameters,
            initial_policy_state=CorrectionPolicyState(),
            validation_output_step_s=60.0,
            authority_config_identity="authority-config-test",
        )
