from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from constellation_control.control.closed_loop import (
    CoastPolicyEvent,
    continuation_request_from_snapshot,
    scan_coast_for_policy_event,
)
from constellation_control.control.policies import CorrectionPolicy, CorrectionPolicyState
from constellation_control.control.transition import AuthoritativeTransitionSnapshot
from constellation_control.domain.models import PropagationRequest, PropagationResult
from constellation_control.domain.protocols import Propagator
from constellation_control.optimization.hybrid import (
    AuthoritativeStateAnchor,
    EventValidationEvidence,
    ScreeningEventBracket,
    ScreeningEventKind,
    StateAnchorKind,
    ValidationOutcomeKind,
)


@dataclass(frozen=True)
class AuthoritativePhaseWindowResult:
    """One high-fidelity window result retaining exact event state for downstream authority."""

    evidence: EventValidationEvidence
    validation_request: PropagationRequest
    event: CoastPolicyEvent | None


def _digest_payload(payload: object) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def transition_state_digest(snapshot: AuthoritativeTransitionSnapshot) -> str:
    """Return a deterministic digest of the complete accepted transition snapshot."""

    return _digest_payload(snapshot.model_dump(mode="json"))


def authoritative_anchor_from_transition(
    snapshot: AuthoritativeTransitionSnapshot,
    *,
    anchor_time_s: float,
    source_evidence_id: str,
) -> AuthoritativeStateAnchor:
    """Wrap one accepted P2 transition as an immutable hybrid validation anchor."""

    return AuthoritativeStateAnchor(
        anchor_id=_digest_payload(
            {
                "source_evidence_id": source_evidence_id,
                "anchor_time_s": float(anchor_time_s),
                "snapshot_digest": transition_state_digest(snapshot),
            }
        )[:24],
        kind=StateAnchorKind.AUTHORITATIVE_SNAPSHOT,
        anchor_time_s=anchor_time_s,
        source_evidence_id=source_evidence_id,
        backend=snapshot.backend,
        force_model_fingerprint=snapshot.force_model_fingerprint,
        state_digest=transition_state_digest(snapshot),
    )


def _screening_event_id(
    strategy_id: str,
    result: PropagationResult,
    event_time_s: float,
    boundary_sign: int | None,
) -> str:
    return _digest_payload(
        {
            "strategy_id": strategy_id,
            "kind": ScreeningEventKind.PHASE_BOUNDARY.value,
            "screening_backend": result.backend,
            "screening_force_model_fingerprint": result.force_model_fingerprint,
            "event_time_s": float(event_time_s),
            "boundary_sign": boundary_sign,
        }
    )[:24]


def discover_phase_boundary_bracket(
    result: PropagationResult,
    *,
    strategy_id: str,
    reference_id: str,
    deputy_id: str,
    policy: CorrectionPolicy,
    corridor_half_width_rad: float,
    initial_policy_state: CorrectionPolicyState,
    output_step_s: float,
    screening_config_identity: str,
    bracket_padding_steps: int = 1,
) -> ScreeningEventBracket | None:
    """Discover one screening-only boundary bracket using accepted policy-grid semantics."""

    if bracket_padding_steps < 0:
        raise ValueError("bracket_padding_steps must be non-negative")
    scan = scan_coast_for_policy_event(
        result,
        reference_id=reference_id,
        deputy_id=deputy_id,
        policy=policy,
        corridor_half_width_rad=corridor_half_width_rad,
        initial_state=initial_policy_state,
        output_step_s=output_step_s,
    )
    if scan.event is None:
        return None
    event = scan.event
    times = tuple(float(value) for value in result.times_s)
    bracket_start = times[event.sample_index - 1] if event.sample_index > 0 else event.time_s
    bracket_end = event.time_s + float(bracket_padding_steps) * float(output_step_s)
    return ScreeningEventBracket(
        strategy_id=strategy_id,
        event_id=_screening_event_id(
            strategy_id,
            result,
            event.time_s,
            event.decision.crossed_boundary_sign,
        ),
        event_kind=ScreeningEventKind.PHASE_BOUNDARY,
        predicted_time_s=event.time_s,
        bracket_start_s=bracket_start,
        bracket_end_s=bracket_end,
        predicted_boundary_sign=event.decision.crossed_boundary_sign,
        predicted_state_coordinate=event.decision.observed_delta_u_rad,
        screening_backend=result.backend,
        screening_force_model_fingerprint=result.force_model_fingerprint,
        screening_output_step_s=output_step_s,
        screening_config_identity=screening_config_identity,
        semantics=(
            "screening-only; first policy correction request on screening output grid; "
            "bracket spans previous sample through configured post-event padding"
        ),
    )


def _validate_transition_anchor(
    source_request: PropagationRequest,
    snapshot: AuthoritativeTransitionSnapshot,
    anchor: AuthoritativeStateAnchor,
) -> None:
    if anchor.kind != StateAnchorKind.AUTHORITATIVE_SNAPSHOT:
        raise ValueError("transition replay requires an authoritative-snapshot anchor")
    if anchor.state_digest != transition_state_digest(snapshot):
        raise ValueError("authoritative anchor state digest does not match transition snapshot")
    if anchor.backend != snapshot.backend:
        raise ValueError("authoritative anchor backend does not match transition snapshot")
    if anchor.force_model_fingerprint != snapshot.force_model_fingerprint:
        raise ValueError("authoritative anchor force fingerprint does not match transition snapshot")
    if snapshot.force_model_fingerprint != source_request.force_model.fingerprint():
        raise ValueError("transition snapshot force fingerprint does not match source request")
    if snapshot.frame != source_request.frame or snapshot.time_scale != source_request.time_scale:
        raise ValueError("transition snapshot frame/time scale does not match source request")
    if snapshot.integrator != source_request.integrator:
        raise ValueError("transition snapshot integrator does not match source request")


def _authority_evidence_id(
    result: PropagationResult,
    screening: ScreeningEventBracket,
    authoritative_event_time_s: float | None,
) -> str:
    return _digest_payload(
        {
            "event_id": screening.event_id,
            "backend": result.backend,
            "backend_version": result.backend_version,
            "force_model_fingerprint": result.force_model_fingerprint,
            "times_s": list(result.times_s),
            "authoritative_event_time_s": authoritative_event_time_s,
        }
    )[:24]


def validate_phase_boundary_window_with_state(
    propagator: Propagator,
    source_request: PropagationRequest,
    snapshot: AuthoritativeTransitionSnapshot,
    anchor: AuthoritativeStateAnchor,
    screening: ScreeningEventBracket,
    *,
    reference_id: str,
    deputy_id: str,
    policy: CorrectionPolicy,
    corridor_half_width_rad: float,
    initial_policy_state: CorrectionPolicyState,
    validation_output_step_s: float,
    authority_config_identity: str,
) -> AuthoritativePhaseWindowResult:
    """Replay one bracket and retain the exact high-fidelity event state without extra propagation."""

    _validate_transition_anchor(source_request, snapshot, anchor)
    if anchor.anchor_time_s > screening.bracket_start_s + 1.0e-9:
        raise ValueError("authoritative anchor must not start after screening bracket start")
    duration_s = screening.bracket_end_s - anchor.anchor_time_s
    if duration_s <= 0.0:
        raise ValueError("authoritative validation window must have positive duration")
    request = continuation_request_from_snapshot(
        source_request,
        snapshot,
        duration_s=duration_s,
        output_step_s=min(float(validation_output_step_s), duration_s),
    )
    result = propagator.propagate(request)
    if not result.backend.startswith("orekit-numerical"):
        raise ValueError("hybrid authoritative event validation requires orekit-numerical backend")
    if result.force_model_fingerprint != request.force_model.fingerprint():
        raise ValueError("authoritative validation result force fingerprint does not match request")
    scan = scan_coast_for_policy_event(
        result,
        reference_id=reference_id,
        deputy_id=deputy_id,
        policy=policy,
        corridor_half_width_rad=corridor_half_width_rad,
        initial_state=initial_policy_state,
        output_step_s=request.output_step_s,
    )
    validation_start = anchor.anchor_time_s
    validation_end = anchor.anchor_time_s + duration_s
    if scan.event is None:
        evidence = EventValidationEvidence(
            strategy_id=screening.strategy_id,
            event_id=screening.event_id,
            outcome=ValidationOutcomeKind.EVENT_ABSENT,
            screening=screening,
            state_anchor=anchor,
            validation_start_s=validation_start,
            validation_end_s=validation_end,
            validation_output_step_s=request.output_step_s,
            authority_backend=result.backend,
            authority_force_model_fingerprint=result.force_model_fingerprint,
            authority_config_identity=authority_config_identity,
            authority_evidence_id=_authority_evidence_id(result, screening, None),
        )
        return AuthoritativePhaseWindowResult(evidence=evidence, validation_request=request, event=None)

    event = scan.event
    authoritative_time = anchor.anchor_time_s + event.time_s
    timing_error = authoritative_time - screening.predicted_time_s
    outcome = (
        ValidationOutcomeKind.CONFIRMED
        if abs(timing_error) <= 1.0e-9
        else ValidationOutcomeKind.SHIFTED
    )
    evidence = EventValidationEvidence(
        strategy_id=screening.strategy_id,
        event_id=screening.event_id,
        outcome=outcome,
        screening=screening,
        state_anchor=anchor,
        validation_start_s=validation_start,
        validation_end_s=validation_end,
        validation_output_step_s=request.output_step_s,
        authority_backend=result.backend,
        authority_force_model_fingerprint=result.force_model_fingerprint,
        authority_config_identity=authority_config_identity,
        authoritative_event_time_s=authoritative_time,
        authoritative_boundary_sign=event.decision.crossed_boundary_sign,
        authoritative_state_coordinate=event.decision.observed_delta_u_rad,
        timing_error_s=timing_error,
        authority_evidence_id=_authority_evidence_id(result, screening, authoritative_time),
    )
    return AuthoritativePhaseWindowResult(evidence=evidence, validation_request=request, event=event)


def validate_phase_boundary_window(
    propagator: Propagator,
    source_request: PropagationRequest,
    snapshot: AuthoritativeTransitionSnapshot,
    anchor: AuthoritativeStateAnchor,
    screening: ScreeningEventBracket,
    *,
    reference_id: str,
    deputy_id: str,
    policy: CorrectionPolicy,
    corridor_half_width_rad: float,
    initial_policy_state: CorrectionPolicyState,
    validation_output_step_s: float,
    authority_config_identity: str,
) -> EventValidationEvidence:
    """Compatibility wrapper returning only immutable event evidence."""

    return validate_phase_boundary_window_with_state(
        propagator,
        source_request,
        snapshot,
        anchor,
        screening,
        reference_id=reference_id,
        deputy_id=deputy_id,
        policy=policy,
        corridor_half_width_rad=corridor_half_width_rad,
        initial_policy_state=initial_policy_state,
        validation_output_step_s=validation_output_step_s,
        authority_config_identity=authority_config_identity,
    ).evidence
