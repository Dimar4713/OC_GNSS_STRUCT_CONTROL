from __future__ import annotations

import pytest

from constellation_control.control.policies import CorrectionPolicy
from constellation_control.optimization.hybrid import (
    AuthoritativeStateAnchor,
    EventValidationEvidence,
    ScreeningEventBracket,
    ScreeningEventKind,
    StateAnchorKind,
    ValidationOutcomeKind,
)
from constellation_control.optimization.hybrid_authority import HybridCorrectionAuthorityReceipt
from constellation_control.optimization.hybrid_strategy import (
    HybridEventExecutionEvidence,
    HybridValidationJob,
    put_hybrid_execution_cache,
    run_hybrid_strategy_validation,
)
from constellation_control.optimization.operations import CredibilityState, HardConstraintEvidence


def _screening(event_id: str, predicted: float) -> ScreeningEventBracket:
    return ScreeningEventBracket(
        strategy_id="candidate-A",
        event_id=event_id,
        event_kind=ScreeningEventKind.PHASE_BOUNDARY,
        predicted_time_s=predicted,
        bracket_start_s=predicted - 20.0,
        bracket_end_s=predicted + 20.0,
        predicted_boundary_sign=1,
        predicted_state_coordinate=0.1,
        screening_backend="mean-screening",
        screening_force_model_fingerprint="screen-fp",
        screening_output_step_s=20.0,
        screening_config_identity="screen-config",
    )


def _anchor(digest: str = "state-a") -> AuthoritativeStateAnchor:
    return AuthoritativeStateAnchor(
        anchor_id=f"anchor-{digest}",
        kind=StateAnchorKind.AUTHORITATIVE_SNAPSHOT,
        anchor_time_s=80.0,
        source_evidence_id="transition-1",
        backend="orekit-numerical-validation",
        force_model_fingerprint="hf-fp",
        state_digest=digest,
    )


def _job(
    event_id: str,
    predicted: float,
    *,
    anchor_digest: str = "state-a",
    config: str = "hf-config",
    step: float = 5.0,
    correction_required: bool = True,
) -> HybridValidationJob:
    return HybridValidationJob(
        screening=_screening(event_id, predicted),
        anchor=_anchor(anchor_digest),
        policy=CorrectionPolicy.BOUNDARY_TO_BOUNDARY,
        corridor_half_width_rad=0.1,
        validation_output_step_s=step,
        authority_config_identity=config,
        correction_authority_required=correction_required,
        correction_authority_identity="mpc-v1" if correction_required else None,
    )


def _validation(job: HybridValidationJob, *, absent: bool = False) -> EventValidationEvidence:
    if absent:
        return EventValidationEvidence(
            strategy_id=job.strategy_id,
            event_id=job.event_id,
            outcome=ValidationOutcomeKind.EVENT_ABSENT,
            screening=job.screening,
            state_anchor=job.anchor,
            validation_start_s=job.screening.bracket_start_s,
            validation_end_s=job.screening.bracket_end_s,
            validation_output_step_s=job.validation_output_step_s,
            authority_backend="orekit-numerical-validation",
            authority_force_model_fingerprint="hf-fp",
            authority_config_identity=job.authority_config_identity,
            authority_evidence_id=f"window-{job.event_id}",
        )
    authoritative_time = job.screening.predicted_time_s + 5.0
    return EventValidationEvidence(
        strategy_id=job.strategy_id,
        event_id=job.event_id,
        outcome=ValidationOutcomeKind.SHIFTED,
        screening=job.screening,
        state_anchor=job.anchor,
        validation_start_s=job.screening.bracket_start_s,
        validation_end_s=job.screening.bracket_end_s,
        validation_output_step_s=job.validation_output_step_s,
        authority_backend="orekit-numerical-validation",
        authority_force_model_fingerprint="hf-fp",
        authority_config_identity=job.authority_config_identity,
        authoritative_event_time_s=authoritative_time,
        authoritative_boundary_sign=1,
        authoritative_state_coordinate=0.101,
        timing_error_s=5.0,
        authority_evidence_id=f"window-{job.event_id}",
    )


def _receipt(
    validation: EventValidationEvidence,
    *,
    authorized: bool = True,
) -> HybridCorrectionAuthorityReceipt:
    margin = 1.0 if authorized else -1.0
    return HybridCorrectionAuthorityReceipt(
        event_validation=validation,
        authority_attempted=True,
        authorized=authorized,
        authority_reason=(
            "authorized-by-numerical-replay" if authorized else "propellant-reserve-violation"
        ),
        hard_constraints=(
            HardConstraintEvidence(
                name="propellant_reserve_margin",
                unit="kg",
                margin=margin,
                evidence_source="numerical-authority",
            ),
        ),
        resulting_credibility_state=(
            CredibilityState.AUTHORITATIVELY_VALIDATED_CANDIDATE
            if authorized
            else CredibilityState.REJECTED_BY_AUTHORITY
        ),
        replay_backend="orekit-numerical-validation",
    )


def _executed(job: HybridValidationJob, *, absent: bool = False, authorized: bool = True):
    validation = _validation(job, absent=absent)
    receipt = None
    if job.correction_authority_required and not absent:
        receipt = _receipt(validation, authorized=authorized)
    return HybridEventExecutionEvidence(
        event_validation=validation,
        correction_authority_receipt=receipt,
    )


def test_two_required_events_complete_authoritative_candidate() -> None:
    jobs = (_job("event-1", 100.0), _job("event-2", 200.0))
    result = run_hybrid_strategy_validation(jobs, executor=_executed)

    assert result.complete
    assert result.resulting_credibility_state == CredibilityState.AUTHORITATIVELY_VALIDATED_CANDIDATE
    assert result.required_event_ids == ("event-1", "event-2")
    assert len(result.records) == 2


def test_missing_event_validation_keeps_candidate_awaiting() -> None:
    first = _job("event-1", 100.0)
    second = _job("event-2", 200.0)

    def executor(job):
        return _executed(job) if job.event_id == "event-1" else None

    result = run_hybrid_strategy_validation((first, second), executor=executor)

    assert not result.complete
    assert result.resulting_credibility_state == CredibilityState.CANDIDATE_AWAITING_VALIDATION
    assert result.reason == "missing-authoritative-validation:event-2"


def test_event_absent_rejects_strategy() -> None:
    first = _job("event-1", 100.0)
    second = _job("event-2", 200.0)

    def executor(job):
        return _executed(job, absent=job.event_id == "event-2")

    result = run_hybrid_strategy_validation((first, second), executor=executor)

    assert result.complete
    assert result.resulting_credibility_state == CredibilityState.REJECTED_BY_AUTHORITY
    assert result.reason == "event-2:event-absent"


def test_correction_authority_rejection_preserves_shifted_event_time() -> None:
    job = _job("event-1", 100.0)
    result = run_hybrid_strategy_validation(
        (job,),
        executor=lambda current: _executed(current, authorized=False),
    )

    assert result.resulting_credibility_state == CredibilityState.REJECTED_BY_AUTHORITY
    evidence = result.records[0].evidence
    assert evidence is not None
    assert evidence.event_validation.authoritative_event_time_s == pytest.approx(105.0)
    assert evidence.correction_authority_receipt is not None
    assert evidence.correction_authority_receipt.authority_reason == "propellant-reserve-violation"


def test_duplicate_exact_job_executes_once_and_reuses_evidence() -> None:
    job = _job("event-1", 100.0)
    calls = 0

    def executor(current):
        nonlocal calls
        calls += 1
        return _executed(current)

    result = run_hybrid_strategy_validation((job, job), executor=executor)

    assert calls == 1
    assert len(result.records) == 1
    assert result.records[0].reused
    assert result.complete


def test_anchor_config_or_grid_change_invalidates_exact_reuse_key() -> None:
    base = _job("event-1", 100.0)
    changed_anchor = _job("event-1", 100.0, anchor_digest="state-b")
    changed_config = _job("event-1", 100.0, config="hf-config-2")
    changed_grid = _job("event-1", 100.0, step=10.0)

    assert len(
        {
            base.exact_key(),
            changed_anchor.exact_key(),
            changed_config.exact_key(),
            changed_grid.exact_key(),
        }
    ) == 4
    with pytest.raises(ValueError, match="conflicting hybrid validation jobs"):
        run_hybrid_strategy_validation((base, changed_anchor), executor=_executed)


def test_conflicting_evidence_for_same_exact_key_fails_closed() -> None:
    job = _job("event-1", 100.0)
    first = _executed(job)
    second_validation = first.event_validation.model_copy(
        update={
            "authoritative_event_time_s": 106.0,
            "timing_error_s": 6.0,
        }
    )
    second = HybridEventExecutionEvidence(
        event_validation=second_validation,
        correction_authority_receipt=_receipt(second_validation),
    )
    cache = {}
    put_hybrid_execution_cache(cache, job.exact_key(), first)
    with pytest.raises(ValueError, match="conflicting hybrid execution evidence"):
        put_hybrid_execution_cache(cache, job.exact_key(), second)
