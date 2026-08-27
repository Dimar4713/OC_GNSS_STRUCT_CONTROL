from __future__ import annotations

import pytest
from pydantic import ValidationError

from constellation_control.optimization.hybrid import (
    AuthoritativeStateAnchor,
    EventValidationEvidence,
    ScreeningEventBracket,
    ScreeningEventKind,
    StateAnchorKind,
    ValidationOutcomeKind,
    assess_hybrid_validation_coverage,
)
from constellation_control.optimization.operations import CredibilityState, HardConstraintEvidence


def _screening(event_id: str, predicted_time_s: float = 100.0) -> ScreeningEventBracket:
    return ScreeningEventBracket(
        strategy_id="candidate-A",
        event_id=event_id,
        event_kind=ScreeningEventKind.PHASE_BOUNDARY,
        predicted_time_s=predicted_time_s,
        bracket_start_s=predicted_time_s - 20.0,
        bracket_end_s=predicted_time_s + 20.0,
        predicted_boundary_sign=1,
        predicted_state_coordinate=0.1,
        screening_backend="mean-screening",
        screening_force_model_fingerprint="screen-fp",
        screening_output_step_s=20.0,
        screening_config_identity="screen-config-v1",
    )


def _anchor() -> AuthoritativeStateAnchor:
    return AuthoritativeStateAnchor(
        anchor_id="anchor-1",
        kind=StateAnchorKind.AUTHORITATIVE_SNAPSHOT,
        anchor_time_s=80.0,
        source_evidence_id="transition-7",
        backend="orekit-numerical-validation",
        force_model_fingerprint="hf-fp",
        state_digest="state-sha256",
    )


def _margin(value: float = 5.0) -> HardConstraintEvidence:
    return HardConstraintEvidence(
        name="fleet_distance_margin",
        unit="m",
        margin=value,
        evidence_source="authoritative-window",
    )


def _validated(
    screening: ScreeningEventBracket,
    *,
    outcome: ValidationOutcomeKind = ValidationOutcomeKind.CONFIRMED,
    authoritative_time_s: float | None = None,
    hard_margin: float = 5.0,
) -> EventValidationEvidence:
    if outcome == ValidationOutcomeKind.CONFIRMED:
        event_time = screening.predicted_time_s if authoritative_time_s is None else authoritative_time_s
    elif outcome == ValidationOutcomeKind.SHIFTED:
        event_time = screening.predicted_time_s + 10.0 if authoritative_time_s is None else authoritative_time_s
    else:
        event_time = None
    return EventValidationEvidence(
        strategy_id=screening.strategy_id,
        event_id=screening.event_id,
        outcome=outcome,
        screening=screening,
        state_anchor=_anchor(),
        validation_start_s=screening.bracket_start_s,
        validation_end_s=screening.bracket_end_s,
        validation_output_step_s=5.0,
        authority_backend="orekit-numerical-validation",
        authority_force_model_fingerprint="hf-fp",
        authority_config_identity="hf-config-v1",
        authoritative_event_time_s=event_time,
        authoritative_boundary_sign=1 if event_time is not None else None,
        authoritative_state_coordinate=0.101 if event_time is not None else None,
        timing_error_s=None if event_time is None else event_time - screening.predicted_time_s,
        hard_constraints=(_margin(hard_margin),),
        authority_evidence_id="validation-window-1",
    )


def test_shifted_event_preserves_screening_and_authoritative_times() -> None:
    screening = _screening("event-1")
    validation = _validated(screening, outcome=ValidationOutcomeKind.SHIFTED)

    assert validation.screening.predicted_time_s == pytest.approx(100.0)
    assert validation.authoritative_event_time_s == pytest.approx(110.0)
    assert validation.timing_error_s == pytest.approx(10.0)
    restored = EventValidationEvidence.model_validate_json(validation.model_dump_json())
    assert restored == validation


def test_event_absent_is_explicit_without_fabricated_event_time() -> None:
    screening = _screening("event-absent")
    validation = _validated(screening, outcome=ValidationOutcomeKind.EVENT_ABSENT)

    assert validation.outcome == ValidationOutcomeKind.EVENT_ABSENT
    assert validation.authoritative_event_time_s is None
    assert validation.timing_error_s is None


def test_screening_only_state_is_not_a_valid_authority_anchor() -> None:
    with pytest.raises(ValidationError, match="screening-only state"):
        AuthoritativeStateAnchor(
            anchor_id="bad",
            kind=StateAnchorKind.SCREENING_STATE,
            anchor_time_s=80.0,
            source_evidence_id="screening-run",
            backend="mean-screening",
            force_model_fingerprint="screen-fp",
            state_digest="screen-state",
        )


def test_missing_required_validation_stays_awaiting_validation() -> None:
    first = _screening("event-1", 100.0)
    second = _screening("event-2", 200.0)
    coverage = assess_hybrid_validation_coverage(
        "candidate-A",
        (first, second),
        (_validated(first),),
    )

    assert not coverage.complete
    assert coverage.resulting_credibility_state == CredibilityState.CANDIDATE_AWAITING_VALIDATION
    assert coverage.rejection_reason == "missing-authoritative-validation:event-2"


def test_absent_required_event_rejects_candidate_by_authority() -> None:
    first = _screening("event-1", 100.0)
    second = _screening("event-2", 200.0)
    coverage = assess_hybrid_validation_coverage(
        "candidate-A",
        (first, second),
        (
            _validated(first),
            _validated(second, outcome=ValidationOutcomeKind.EVENT_ABSENT),
        ),
    )

    assert coverage.complete
    assert coverage.resulting_credibility_state == CredibilityState.REJECTED_BY_AUTHORITY
    assert coverage.rejection_reason == "event-2:event-absent"


def test_hard_margin_failure_requires_rejected_outcome_and_rejects_coverage() -> None:
    screening = _screening("event-1")
    rejected = EventValidationEvidence(
        strategy_id=screening.strategy_id,
        event_id=screening.event_id,
        outcome=ValidationOutcomeKind.HARD_CONSTRAINT_REJECTED,
        screening=screening,
        state_anchor=_anchor(),
        validation_start_s=80.0,
        validation_end_s=120.0,
        validation_output_step_s=5.0,
        authority_backend="orekit-numerical-validation",
        authority_force_model_fingerprint="hf-fp",
        authority_config_identity="hf-config-v1",
        hard_constraints=(_margin(-0.01),),
        authority_evidence_id="validation-window-1",
    )
    coverage = assess_hybrid_validation_coverage("candidate-A", (screening,), (rejected,))

    assert coverage.resulting_credibility_state == CredibilityState.REJECTED_BY_AUTHORITY
    assert coverage.rejection_reason == "event-1:hard-constraint-rejected"


def test_duplicate_validation_for_same_required_event_fails_closed() -> None:
    screening = _screening("event-1")
    validation = _validated(screening)
    with pytest.raises(ValueError, match="duplicate/conflicting"):
        assess_hybrid_validation_coverage(
            "candidate-A",
            (screening,),
            (validation, validation),
        )


def test_complete_confirmed_and_shifted_set_advances_to_validated_candidate() -> None:
    first = _screening("event-1", 100.0)
    second = _screening("event-2", 200.0)
    coverage = assess_hybrid_validation_coverage(
        "candidate-A",
        (first, second),
        (
            _validated(first),
            _validated(second, outcome=ValidationOutcomeKind.SHIFTED, authoritative_time_s=210.0),
        ),
    )

    assert coverage.complete
    assert coverage.resulting_credibility_state == CredibilityState.AUTHORITATIVELY_VALIDATED_CANDIDATE
    assert coverage.rejection_reason is None
    assert [item.event_id for item in coverage.validations] == ["event-1", "event-2"]
