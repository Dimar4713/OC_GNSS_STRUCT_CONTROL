from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from constellation_control.optimization.operations import CredibilityState, HardConstraintEvidence


class ScreeningEventKind(StrEnum):
    PHASE_BOUNDARY = "phase-boundary"
    OPTIMIZED_TRIGGER = "optimized-trigger"
    REARM = "rearm"
    SAFETY_MARGIN = "safety-margin"
    RESOURCE_MARGIN = "resource-margin"
    CANDIDATE_CORRECTION = "candidate-correction"


class StateAnchorKind(StrEnum):
    AUTHORITATIVE_SNAPSHOT = "authoritative-snapshot"
    AUTHORITATIVE_REPLAY = "authoritative-replay"
    SCREENING_STATE = "screening-state"


class ValidationOutcomeKind(StrEnum):
    CONFIRMED = "confirmed"
    SHIFTED = "shifted"
    EVENT_ABSENT = "event-absent"
    INVALID_STATE_ANCHOR = "invalid-state-anchor"
    HARD_CONSTRAINT_REJECTED = "hard-constraint-rejected"


class ScreeningEventBracket(BaseModel):
    """Screening-only event hypothesis; it never constitutes maneuver authority."""

    model_config = ConfigDict(frozen=True)

    strategy_id: str
    event_id: str
    event_kind: ScreeningEventKind
    predicted_time_s: float = Field(ge=0.0)
    bracket_start_s: float = Field(ge=0.0)
    bracket_end_s: float = Field(ge=0.0)
    predicted_boundary_sign: int | None = None
    predicted_state_coordinate: float | None = None
    screening_backend: str
    screening_force_model_fingerprint: str
    screening_output_step_s: float = Field(gt=0.0)
    screening_config_identity: str
    semantics: str = "screening-only; not maneuver authority"

    @model_validator(mode="after")
    def validate_bracket(self) -> ScreeningEventBracket:
        if self.bracket_end_s < self.bracket_start_s:
            raise ValueError("screening bracket end must not precede start")
        if not self.bracket_start_s <= self.predicted_time_s <= self.bracket_end_s:
            raise ValueError("predicted event time must lie inside screening bracket")
        if self.predicted_boundary_sign not in {None, -1, 1}:
            raise ValueError("predicted_boundary_sign must be -1, +1 or absent")
        if "screening-only" not in self.semantics:
            raise ValueError("screening bracket semantics must remain explicitly screening-only")
        return self


class AuthoritativeStateAnchor(BaseModel):
    """Accepted provenance for the initial state of a high-fidelity validation window."""

    model_config = ConfigDict(frozen=True)

    anchor_id: str
    kind: StateAnchorKind
    anchor_time_s: float = Field(ge=0.0)
    source_evidence_id: str
    backend: str
    force_model_fingerprint: str
    state_digest: str

    @model_validator(mode="after")
    def validate_authority(self) -> AuthoritativeStateAnchor:
        if self.kind == StateAnchorKind.SCREENING_STATE:
            raise ValueError("screening-only state is not a valid high-fidelity authority anchor")
        return self


class EventValidationEvidence(BaseModel):
    """Authoritative validation result for exactly one screening event hypothesis."""

    model_config = ConfigDict(frozen=True)

    strategy_id: str
    event_id: str
    outcome: ValidationOutcomeKind
    screening: ScreeningEventBracket
    state_anchor: AuthoritativeStateAnchor | None
    validation_start_s: float = Field(ge=0.0)
    validation_end_s: float = Field(ge=0.0)
    validation_output_step_s: float = Field(gt=0.0)
    authority_backend: str
    authority_force_model_fingerprint: str
    authority_config_identity: str
    authoritative_event_time_s: float | None = Field(default=None, ge=0.0)
    authoritative_boundary_sign: int | None = None
    authoritative_state_coordinate: float | None = None
    timing_error_s: float | None = None
    hard_constraints: tuple[HardConstraintEvidence, ...] = ()
    authority_evidence_id: str | None = None

    @model_validator(mode="after")
    def validate_evidence(self) -> EventValidationEvidence:
        if self.strategy_id != self.screening.strategy_id or self.event_id != self.screening.event_id:
            raise ValueError("validation must refer to the exact screening strategy/event")
        if self.validation_end_s < self.validation_start_s:
            raise ValueError("validation window end must not precede start")
        if self.outcome == ValidationOutcomeKind.INVALID_STATE_ANCHOR:
            if self.state_anchor is not None:
                raise ValueError("invalid-state-anchor outcome must not carry an accepted authority anchor")
            if self.authoritative_event_time_s is not None:
                raise ValueError("invalid state anchor cannot produce an authoritative event")
            return self
        if self.state_anchor is None:
            raise ValueError("authoritative validation requires an accepted state anchor")
        if self.outcome in {ValidationOutcomeKind.CONFIRMED, ValidationOutcomeKind.SHIFTED}:
            if self.authoritative_event_time_s is None or self.authority_evidence_id is None:
                raise ValueError("confirmed/shifted event requires authoritative time and evidence id")
            if not self.validation_start_s <= self.authoritative_event_time_s <= self.validation_end_s:
                raise ValueError("authoritative event time must lie inside validation window")
            expected_error = self.authoritative_event_time_s - self.screening.predicted_time_s
            if self.timing_error_s is None or abs(self.timing_error_s - expected_error) > 1.0e-9:
                raise ValueError("timing_error_s must equal authoritative minus screening event time")
            if self.outcome == ValidationOutcomeKind.CONFIRMED and abs(expected_error) > 1.0e-9:
                raise ValueError("confirmed event cannot have a shifted authoritative time")
            if self.outcome == ValidationOutcomeKind.SHIFTED and abs(expected_error) <= 1.0e-9:
                raise ValueError("shifted event requires a non-zero timing shift")
        else:
            if self.authoritative_event_time_s is not None or self.timing_error_s is not None:
                raise ValueError("absent/rejected event must not fabricate authoritative event timing")
        if self.outcome == ValidationOutcomeKind.EVENT_ABSENT and self.authority_evidence_id is None:
            raise ValueError("event-absent outcome still requires authoritative validation evidence id")
        if self.outcome == ValidationOutcomeKind.HARD_CONSTRAINT_REJECTED:
            if not self.hard_constraints or all(item.passed for item in self.hard_constraints):
                raise ValueError("hard-constraint-rejected outcome requires at least one failed hard margin")
        if self.outcome in {ValidationOutcomeKind.CONFIRMED, ValidationOutcomeKind.SHIFTED} and any(
            not item.passed for item in self.hard_constraints
        ):
            raise ValueError("confirmed/shifted event cannot carry a failed hard constraint")
        return self


class HybridValidationCoverage(BaseModel):
    model_config = ConfigDict(frozen=True)

    strategy_id: str
    required_event_ids: tuple[str, ...]
    validations: tuple[EventValidationEvidence, ...]
    resulting_credibility_state: CredibilityState
    complete: bool
    rejection_reason: str | None = None


def assess_hybrid_validation_coverage(
    strategy_id: str,
    required_events: tuple[ScreeningEventBracket, ...],
    validations: tuple[EventValidationEvidence, ...],
) -> HybridValidationCoverage:
    """Reduce event-window evidence to a candidate credibility transition without propagation."""

    required = tuple(event.event_id for event in required_events)
    if len(required) != len(set(required)):
        raise ValueError("required screening event ids must be unique")
    if any(event.strategy_id != strategy_id for event in required_events):
        raise ValueError("all required events must belong to the requested strategy")
    by_id: dict[str, EventValidationEvidence] = {}
    for validation in validations:
        if validation.strategy_id != strategy_id:
            raise ValueError("validation belongs to a different strategy")
        if validation.event_id in by_id:
            raise ValueError("duplicate/conflicting validation for required event")
        by_id[validation.event_id] = validation
    unknown = set(by_id) - set(required)
    if unknown:
        raise ValueError("validation contains event ids outside the required screening set")
    missing = [event_id for event_id in required if event_id not in by_id]
    if missing:
        return HybridValidationCoverage(
            strategy_id=strategy_id,
            required_event_ids=required,
            validations=validations,
            resulting_credibility_state=CredibilityState.CANDIDATE_AWAITING_VALIDATION,
            complete=False,
            rejection_reason=f"missing-authoritative-validation:{','.join(missing)}",
        )
    ordered = tuple(by_id[event_id] for event_id in required)
    rejected = next(
        (
            item
            for item in ordered
            if item.outcome
            in {
                ValidationOutcomeKind.EVENT_ABSENT,
                ValidationOutcomeKind.INVALID_STATE_ANCHOR,
                ValidationOutcomeKind.HARD_CONSTRAINT_REJECTED,
            }
            or any(not constraint.passed for constraint in item.hard_constraints)
        ),
        None,
    )
    if rejected is not None:
        return HybridValidationCoverage(
            strategy_id=strategy_id,
            required_event_ids=required,
            validations=ordered,
            resulting_credibility_state=CredibilityState.REJECTED_BY_AUTHORITY,
            complete=True,
            rejection_reason=f"{rejected.event_id}:{rejected.outcome.value}",
        )
    if not all(
        item.outcome in {ValidationOutcomeKind.CONFIRMED, ValidationOutcomeKind.SHIFTED}
        for item in ordered
    ):
        raise ValueError("unsupported validation outcome in complete event set")
    return HybridValidationCoverage(
        strategy_id=strategy_id,
        required_event_ids=required,
        validations=ordered,
        resulting_credibility_state=CredibilityState.AUTHORITATIVELY_VALIDATED_CANDIDATE,
        complete=True,
        rejection_reason=None,
    )