from __future__ import annotations

import hashlib
import json

from constellation_control.control.policies import CorrectionPolicyState
from constellation_control.domain.models import ForceMode, PropagationRequest
from constellation_control.domain.protocols import Propagator
from constellation_control.optimization.hybrid import (
    AuthoritativeStateAnchor,
    EventValidationEvidence,
    StateAnchorKind,
    ValidationOutcomeKind,
)
from constellation_control.optimization.hybrid_execution import _authority_evidence_id
from constellation_control.optimization.operational_policy_search import OperationalPolicyParameters
from constellation_control.optimization.optimized_hybrid_execution import (
    AuthoritativeOptimizedWindowResult,
    OptimizedTriggerBracketEvidence,
    _scan_optimized_trigger,
)


def _digest(payload: object) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def validate_initial_optimized_trigger_replay(
    propagator: Propagator,
    source_request: PropagationRequest,
    screening: OptimizedTriggerBracketEvidence,
    *,
    reference_id: str,
    deputy_id: str,
    parameters: OperationalPolicyParameters,
    initial_policy_state: CorrectionPolicyState,
    validation_output_step_s: float,
    authority_config_identity: str,
) -> AuthoritativeOptimizedWindowResult:
    """Validate the first optimized trigger from the authoritative initial state.

    This path intentionally does not construct a fake post-maneuver transition.
    The high-fidelity window is replayed directly from the validated source initial
    condition and recorded as an AUTHORITATIVE_REPLAY anchor.
    """

    if source_request.force_model.mode != ForceMode.VALIDATION:
        raise ValueError("initial optimized authority replay requires VALIDATION force mode")
    if source_request.maneuvers:
        raise ValueError("initial optimized authority replay source must not contain maneuvers")
    if parameters.trigger_fraction != screening.trigger_fraction or parameters.target_fraction != screening.target_fraction:
        raise ValueError("initial optimized validation parameters do not match screening evidence")
    if screening.bracket.bracket_end_s <= 0.0:
        raise ValueError("initial optimized validation requires a positive bracket end")

    duration_s = screening.bracket.bracket_end_s
    request = source_request.model_copy(
        update={
            "duration_s": duration_s,
            "output_step_s": min(float(validation_output_step_s), duration_s),
        }
    )
    result = propagator.propagate(request)
    if not result.backend.startswith("orekit-numerical"):
        raise ValueError("initial optimized validation requires orekit-numerical backend")
    expected_fingerprint = request.force_model.fingerprint()
    if result.force_model_fingerprint != expected_fingerprint:
        raise ValueError("initial optimized validation result fingerprint does not match source request")

    state_digest = _digest(
        {
            "scenario_id": request.scenario_id,
            "epoch": request.epoch.isoformat(),
            "frame": request.frame.value,
            "time_scale": request.time_scale.value,
            "satellites": [sat.model_dump(mode="json") for sat in request.satellites],
            "force_model_fingerprint": expected_fingerprint,
            "integrator": request.integrator.model_dump(mode="json"),
            "seed": request.seed,
        }
    )
    source_evidence_id = _digest(
        {
            "backend": result.backend,
            "backend_version": result.backend_version,
            "force_model_fingerprint": result.force_model_fingerprint,
            "times_s": list(result.times_s),
            "initial_state_digest": state_digest,
        }
    )[:24]
    anchor = AuthoritativeStateAnchor(
        anchor_id=_digest(
            {
                "kind": StateAnchorKind.AUTHORITATIVE_REPLAY.value,
                "source_evidence_id": source_evidence_id,
                "state_digest": state_digest,
            }
        )[:24],
        kind=StateAnchorKind.AUTHORITATIVE_REPLAY,
        anchor_time_s=0.0,
        source_evidence_id=source_evidence_id,
        backend=result.backend,
        force_model_fingerprint=result.force_model_fingerprint,
        state_digest=state_digest,
    )

    scan, optimized = _scan_optimized_trigger(
        result,
        candidate_id=screening.candidate_id,
        parameters=parameters,
        reference_id=reference_id,
        deputy_id=deputy_id,
        hard_corridor_half_width_rad=screening.hard_corridor_half_width_rad,
        initial_state=initial_policy_state,
        output_step_s=request.output_step_s,
    )
    bracket = screening.bracket
    if scan.event is None or optimized is None:
        evidence = EventValidationEvidence(
            strategy_id=bracket.strategy_id,
            event_id=bracket.event_id,
            outcome=ValidationOutcomeKind.EVENT_ABSENT,
            screening=bracket,
            state_anchor=anchor,
            validation_start_s=0.0,
            validation_end_s=duration_s,
            validation_output_step_s=request.output_step_s,
            authority_backend=result.backend,
            authority_force_model_fingerprint=result.force_model_fingerprint,
            authority_config_identity=authority_config_identity,
            authority_evidence_id=_authority_evidence_id(result, bracket, None),
        )
        return AuthoritativeOptimizedWindowResult(evidence, request, None, None)

    event = scan.event
    authoritative_time = event.time_s
    timing_error = authoritative_time - bracket.predicted_time_s
    outcome = ValidationOutcomeKind.CONFIRMED if abs(timing_error) <= 1.0e-9 else ValidationOutcomeKind.SHIFTED
    evidence = EventValidationEvidence(
        strategy_id=bracket.strategy_id,
        event_id=bracket.event_id,
        outcome=outcome,
        screening=bracket,
        state_anchor=anchor,
        validation_start_s=0.0,
        validation_end_s=duration_s,
        validation_output_step_s=request.output_step_s,
        authority_backend=result.backend,
        authority_force_model_fingerprint=result.force_model_fingerprint,
        authority_config_identity=authority_config_identity,
        authoritative_event_time_s=authoritative_time,
        authoritative_boundary_sign=event.decision.crossed_boundary_sign,
        authoritative_state_coordinate=event.decision.observed_delta_u_rad,
        timing_error_s=timing_error,
        authority_evidence_id=_authority_evidence_id(result, bracket, authoritative_time),
    )
    return AuthoritativeOptimizedWindowResult(evidence, request, event, optimized)
