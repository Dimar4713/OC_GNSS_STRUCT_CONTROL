from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from math import isfinite

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, model_validator

from constellation_control.analysis.relative_operations import mean_phase_rad
from constellation_control.control.closed_loop import (
    CoastPolicyEvent,
    CoastScanResult,
    _sample_states,
    continuation_request_from_snapshot,
)
from constellation_control.control.optimized_policy import (
    OptimizedPolicyDecisionEvidence,
    evaluate_optimized_correction_policy,
)
from constellation_control.control.policies import CorrectionPolicyState
from constellation_control.control.transition import AuthoritativeTransitionSnapshot
from constellation_control.domain.models import PropagationRequest, PropagationResult
from constellation_control.domain.protocols import Propagator
from constellation_control.dynamics.orbits import wrap_pi
from constellation_control.optimization.hybrid import (
    AuthoritativeStateAnchor,
    EventValidationEvidence,
    ScreeningEventBracket,
    ScreeningEventKind,
    ValidationOutcomeKind,
)
from constellation_control.optimization.hybrid_execution import (
    _authority_evidence_id,
    _validate_transition_anchor,
)
from constellation_control.optimization.operational_policy_search import OperationalPolicyParameters


class OptimizedTriggerBracketEvidence(BaseModel):
    model_config = ConfigDict(frozen=True)

    candidate_id: str = Field(min_length=1)
    trigger_fraction: float = Field(gt=0.0, le=1.0)
    trigger_half_width_rad: float = Field(gt=0.0)
    target_fraction: float = Field(ge=-1.0, le=1.0)
    hard_corridor_half_width_rad: float = Field(gt=0.0)
    bracket: ScreeningEventBracket

    @model_validator(mode="after")
    def validate_kind_and_threshold(self) -> OptimizedTriggerBracketEvidence:
        if self.bracket.event_kind != ScreeningEventKind.OPTIMIZED_TRIGGER:
            raise ValueError("optimized trigger evidence requires optimized-trigger bracket kind")
        expected = self.trigger_fraction * self.hard_corridor_half_width_rad
        if abs(self.trigger_half_width_rad - expected) > 1.0e-12:
            raise ValueError("optimized trigger threshold does not match fraction of hard corridor")
        return self


@dataclass(frozen=True)
class AuthoritativeOptimizedWindowResult:
    evidence: EventValidationEvidence
    validation_request: PropagationRequest
    event: CoastPolicyEvent | None
    optimized_decision: OptimizedPolicyDecisionEvidence | None


def _digest(payload: object) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _scan_optimized_trigger(
    result: PropagationResult,
    *,
    candidate_id: str,
    parameters: OperationalPolicyParameters,
    reference_id: str,
    deputy_id: str,
    hard_corridor_half_width_rad: float,
    initial_state: CorrectionPolicyState,
    output_step_s: float,
) -> tuple[CoastScanResult, OptimizedPolicyDecisionEvidence | None]:
    step = float(output_step_s)
    if not isfinite(step) or step <= 0.0:
        raise ValueError("output_step_s must be finite and positive")
    times = np.asarray(result.times_s, dtype=float)
    if times.ndim != 1 or times.size == 0 or np.any(~np.isfinite(times)):
        raise ValueError("optimized trigger result times must be a non-empty finite one-dimensional grid")
    if abs(float(times[0])) > 1.0e-9:
        raise ValueError("optimized trigger result time grid must start at zero")
    intervals = np.diff(times)
    if np.any(intervals <= 0.0):
        raise ValueError("optimized trigger result times must be strictly increasing")
    if intervals.size and np.any(intervals > step + 1.0e-9):
        raise ValueError("optimized trigger result intervals exceed declared output_step_s")
    if reference_id not in result.mean_orbits or deputy_id not in result.mean_orbits:
        raise ValueError("optimized trigger result does not contain requested reference/deputy pair")
    ref_history = result.mean_orbits[reference_id]
    dep_history = result.mean_orbits[deputy_id]
    if len(ref_history) != times.size or len(dep_history) != times.size:
        raise ValueError("optimized trigger mean histories must match result time grid")

    state = initial_state
    for index, (time_s, ref_mean, dep_mean) in enumerate(zip(times, ref_history, dep_history, strict=True)):
        delta_u = wrap_pi(mean_phase_rad(dep_mean) - mean_phase_rad(ref_mean))
        state_before = state
        optimized, state = evaluate_optimized_correction_policy(
            candidate_id,
            parameters,
            delta_u,
            hard_corridor_half_width_rad,
            state,
        )
        if optimized.decision.correction_requested:
            event = CoastPolicyEvent(
                sample_index=index,
                time_s=float(time_s),
                grid_resolution_s=step,
                timing_semantics="first optimized trigger request on propagation output grid; no interpolation",
                decision=optimized.decision,
                state_before=state_before,
                state_after=state,
                spacecraft_states=_sample_states(result, index),
                source_backend=result.backend,
                source_force_model_fingerprint=result.force_model_fingerprint,
            )
            return CoastScanResult(event=event, final_policy_state=state, samples_evaluated=index + 1), optimized
    return CoastScanResult(event=None, final_policy_state=state, samples_evaluated=int(times.size)), None


def discover_optimized_trigger_bracket(
    result: PropagationResult,
    *,
    strategy_id: str,
    candidate_id: str,
    parameters: OperationalPolicyParameters,
    reference_id: str,
    deputy_id: str,
    hard_corridor_half_width_rad: float,
    initial_policy_state: CorrectionPolicyState,
    output_step_s: float,
    screening_config_identity: str,
    bracket_padding_steps: int = 1,
) -> OptimizedTriggerBracketEvidence | None:
    if bracket_padding_steps < 0:
        raise ValueError("bracket_padding_steps must be non-negative")
    scan, optimized = _scan_optimized_trigger(
        result,
        candidate_id=candidate_id,
        parameters=parameters,
        reference_id=reference_id,
        deputy_id=deputy_id,
        hard_corridor_half_width_rad=hard_corridor_half_width_rad,
        initial_state=initial_policy_state,
        output_step_s=output_step_s,
    )
    if scan.event is None or optimized is None:
        return None
    event = scan.event
    times = tuple(float(value) for value in result.times_s)
    start = times[event.sample_index - 1] if event.sample_index > 0 else event.time_s
    end = event.time_s + bracket_padding_steps * float(output_step_s)
    event_id = _digest(
        {
            "strategy_id": strategy_id,
            "candidate_id": candidate_id,
            "kind": ScreeningEventKind.OPTIMIZED_TRIGGER.value,
            "trigger_fraction": parameters.trigger_fraction,
            "target_fraction": parameters.target_fraction,
            "event_time_s": event.time_s,
            "sign": event.decision.crossed_boundary_sign,
            "backend": result.backend,
            "fingerprint": result.force_model_fingerprint,
        }
    )[:24]
    bracket = ScreeningEventBracket(
        strategy_id=strategy_id,
        event_id=event_id,
        event_kind=ScreeningEventKind.OPTIMIZED_TRIGGER,
        predicted_time_s=event.time_s,
        bracket_start_s=start,
        bracket_end_s=end,
        predicted_boundary_sign=event.decision.crossed_boundary_sign,
        predicted_state_coordinate=event.decision.observed_delta_u_rad,
        screening_backend=result.backend,
        screening_force_model_fingerprint=result.force_model_fingerprint,
        screening_output_step_s=output_step_s,
        screening_config_identity=screening_config_identity,
        semantics="screening-only; optimized trigger hypothesis on direct mean-phase output grid; no maneuver authority",
    )
    return OptimizedTriggerBracketEvidence(
        candidate_id=candidate_id,
        trigger_fraction=parameters.trigger_fraction,
        trigger_half_width_rad=optimized.trigger_half_width_rad,
        target_fraction=parameters.target_fraction,
        hard_corridor_half_width_rad=hard_corridor_half_width_rad,
        bracket=bracket,
    )


def validate_optimized_trigger_window(
    propagator: Propagator,
    source_request: PropagationRequest,
    snapshot: AuthoritativeTransitionSnapshot,
    anchor: AuthoritativeStateAnchor,
    screening: OptimizedTriggerBracketEvidence,
    *,
    reference_id: str,
    deputy_id: str,
    parameters: OperationalPolicyParameters,
    initial_policy_state: CorrectionPolicyState,
    validation_output_step_s: float,
    authority_config_identity: str,
) -> AuthoritativeOptimizedWindowResult:
    bracket = screening.bracket
    if parameters.trigger_fraction != screening.trigger_fraction or parameters.target_fraction != screening.target_fraction:
        raise ValueError("optimized validation parameters do not match screening evidence")
    _validate_transition_anchor(source_request, snapshot, anchor)
    if anchor.anchor_time_s > bracket.bracket_start_s + 1.0e-9:
        raise ValueError("authoritative anchor must not start after optimized trigger bracket start")
    duration_s = bracket.bracket_end_s - anchor.anchor_time_s
    if duration_s <= 0.0:
        raise ValueError("optimized authoritative validation window must have positive duration")
    request = continuation_request_from_snapshot(
        source_request,
        snapshot,
        duration_s=duration_s,
        output_step_s=min(float(validation_output_step_s), duration_s),
    )
    result = propagator.propagate(request)
    if not result.backend.startswith("orekit-numerical"):
        raise ValueError("optimized authoritative validation requires orekit-numerical backend")
    if result.force_model_fingerprint != request.force_model.fingerprint():
        raise ValueError("optimized validation result force fingerprint does not match request")
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
    start = anchor.anchor_time_s
    end = start + duration_s
    if scan.event is None or optimized is None:
        evidence = EventValidationEvidence(
            strategy_id=bracket.strategy_id,
            event_id=bracket.event_id,
            outcome=ValidationOutcomeKind.EVENT_ABSENT,
            screening=bracket,
            state_anchor=anchor,
            validation_start_s=start,
            validation_end_s=end,
            validation_output_step_s=request.output_step_s,
            authority_backend=result.backend,
            authority_force_model_fingerprint=result.force_model_fingerprint,
            authority_config_identity=authority_config_identity,
            authority_evidence_id=_authority_evidence_id(result, bracket, None),
        )
        return AuthoritativeOptimizedWindowResult(evidence, request, None, None)

    event = scan.event
    authoritative_time = start + event.time_s
    timing_error = authoritative_time - bracket.predicted_time_s
    outcome = ValidationOutcomeKind.CONFIRMED if abs(timing_error) <= 1.0e-9 else ValidationOutcomeKind.SHIFTED
    evidence = EventValidationEvidence(
        strategy_id=bracket.strategy_id,
        event_id=bracket.event_id,
        outcome=outcome,
        screening=bracket,
        state_anchor=anchor,
        validation_start_s=start,
        validation_end_s=end,
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
