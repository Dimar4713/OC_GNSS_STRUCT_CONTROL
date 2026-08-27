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
)
from constellation_control.optimization.hybrid_authority import HybridCorrectionAuthorityReceipt
from constellation_control.optimization.hybrid_strategy import (
    HybridEventExecutionEvidence,
    HybridEventExecutionRecord,
    HybridStrategyValidationResult,
)
from constellation_control.optimization.operational_policy_search import (
    OperationalPolicyCandidate,
    OperationalPolicyParameters,
)
from constellation_control.optimization.operations import (
    CredibilityState,
    HardConstraintEvidence,
    NamedObjectiveValue,
    ObjectiveDirection,
    OperationalStrategyEvaluation,
    OperationalStrategyKind,
    OperationalStudyIdentity,
)
from constellation_control.optimization.optimal_operations_orchestration import (
    AuthoritativeOperationalOutcomeEvidence,
    assemble_optimal_operations_study,
    build_optimized_operational_evaluation,
)


def _identity(*, force: str = "force-a") -> OperationalStudyIdentity:
    return OperationalStudyIdentity(
        scenario_id="ops-study",
        initial_epoch_iso="2026-01-01T00:00:00+00:00",
        seed=42,
        force_model_fingerprint=force,
        frame="GCRF",
        time_scale="UTC",
        integrator_identity="dop853:test",
        constraints_identity="constraints:test",
        execution_policy_identity="mpc:test",
        campaign_horizon_s=1000.0,
        coast_horizon_s=200.0,
        coast_output_step_s=60.0,
        authority_times_s=(0.0, 60.0, 120.0),
        maneuver_windows=(True, True),
    )


def _objectives(*, fuel: float, corrections: float, lifetime: float) -> tuple[NamedObjectiveValue, ...]:
    return (
        NamedObjectiveValue(
            name="propellant_rate",
            unit="kg/Julian-year",
            direction=ObjectiveDirection.MINIMIZE,
            value=fuel,
        ),
        NamedObjectiveValue(
            name="correction_frequency",
            unit="events/Julian-year",
            direction=ObjectiveDirection.MINIMIZE,
            value=corrections,
        ),
        NamedObjectiveValue(
            name="projected_lifetime",
            unit="Julian-year",
            direction=ObjectiveDirection.MAXIMIZE,
            value=lifetime,
        ),
    )


def _outcome(*, fuel: float = 0.8, corrections: float = 3.0, lifetime: float = 12.0) -> AuthoritativeOperationalOutcomeEvidence:
    return AuthoritativeOperationalOutcomeEvidence(
        campaign_termination_reason="campaign-horizon-reached",
        correction_count=3,
        corrections_per_julian_year=corrections,
        cumulative_delta_v_m_s=0.08,
        delta_v_m_s_per_julian_year=0.08,
        cumulative_propellant_used_kg=fuel,
        propellant_kg_per_julian_year=fuel,
        projected_years_to_reserve=lifetime,
        minimum_corridor_margin_rad=0.01,
        minimum_fleet_distance_margin_m=1000.0,
        objectives=_objectives(fuel=fuel, corrections=corrections, lifetime=lifetime),
        hard_constraints=(
            HardConstraintEvidence(
                name="phase_corridor_margin",
                unit="rad",
                margin=0.01,
                evidence_source="authoritative-campaign",
            ),
        ),
        evidence_id="ops-outcome-001",
    )


def _candidate() -> OperationalPolicyCandidate:
    return OperationalPolicyCandidate(
        candidate_id="nsga2-opt-001",
        stage="nsga2",
        parameters=OperationalPolicyParameters(trigger_fraction=0.5, target_fraction=0.25),
        objectives=(999.0, 998.0, 997.0),
        hard_margins=(1.0,),
        metrics={"screening_only_metric": 123.0},
        feasible=True,
    )


def _validation(strategy_id: str = "optimized-1") -> EventValidationEvidence:
    screening = ScreeningEventBracket(
        strategy_id=strategy_id,
        event_id="event-1",
        event_kind=ScreeningEventKind.OPTIMIZED_TRIGGER,
        predicted_time_s=120.0,
        bracket_start_s=60.0,
        bracket_end_s=180.0,
        predicted_boundary_sign=1,
        predicted_state_coordinate=0.05,
        screening_backend="mean-screening",
        screening_force_model_fingerprint="force-a",
        screening_output_step_s=60.0,
        screening_config_identity="screen-v1",
    )
    anchor = AuthoritativeStateAnchor(
        anchor_id="anchor-1",
        kind=StateAnchorKind.AUTHORITATIVE_SNAPSHOT,
        anchor_time_s=60.0,
        source_evidence_id="transition-1",
        backend="orekit-numerical-validation",
        force_model_fingerprint="force-a",
        state_digest="state-digest",
    )
    return EventValidationEvidence(
        strategy_id=strategy_id,
        event_id="event-1",
        outcome=ValidationOutcomeKind.SHIFTED,
        screening=screening,
        state_anchor=anchor,
        validation_start_s=60.0,
        validation_end_s=180.0,
        validation_output_step_s=60.0,
        authority_backend="orekit-numerical-validation",
        authority_force_model_fingerprint="force-a",
        authority_config_identity="hf-v1",
        authoritative_event_time_s=180.0,
        authoritative_boundary_sign=1,
        authoritative_state_coordinate=0.06,
        timing_error_s=60.0,
        authority_evidence_id="hf-event-1",
    )


def _hybrid(
    *,
    state: CredibilityState = CredibilityState.AUTHORITATIVELY_VALIDATED_CANDIDATE,
    complete: bool = True,
    fingerprint: str = "force-a",
    authorized: bool = True,
) -> HybridStrategyValidationResult:
    validation = _validation()
    receipt = HybridCorrectionAuthorityReceipt(
        event_validation=validation,
        authority_attempted=True,
        authorized=authorized,
        authority_reason="authorized" if authorized else "rejected",
        hard_constraints=(
            HardConstraintEvidence(
                name="propellant_reserve_margin",
                unit="kg",
                margin=5.0 if authorized else -1.0,
                evidence_source="numerical-authority",
            ),
        ),
        resulting_credibility_state=state,
        replay_backend="orekit-numerical-validation" if authorized else None,
        transition_force_model_fingerprint=fingerprint if authorized else None,
    )
    record = HybridEventExecutionRecord(
        event_id="event-1",
        validation_key="key-1",
        reused=False,
        evidence=HybridEventExecutionEvidence(
            event_validation=validation,
            correction_authority_receipt=receipt,
        ),
    )
    return HybridStrategyValidationResult(
        strategy_id="optimized-1",
        required_event_ids=("event-1",),
        records=(record,),
        resulting_credibility_state=state,
        complete=complete,
        reason=None if state == CredibilityState.AUTHORITATIVELY_VALIDATED_CANDIDATE else "not-authorized",
    )


def _baseline(kind: OperationalStrategyKind, strategy_id: str, fuel: float) -> OperationalStrategyEvaluation:
    return OperationalStrategyEvaluation(
        strategy_id=strategy_id,
        kind=kind,
        credibility_state=CredibilityState.AUTHORITATIVE_BASELINE,
        identity=_identity(),
        campaign_termination_reason="campaign-horizon-reached",
        correction_count=4,
        corrections_per_julian_year=4.0,
        cumulative_delta_v_m_s=0.1,
        delta_v_m_s_per_julian_year=0.1,
        cumulative_propellant_used_kg=fuel,
        propellant_kg_per_julian_year=fuel,
        projected_years_to_reserve=10.0,
        objectives=_objectives(fuel=fuel, corrections=4.0, lifetime=10.0),
        hard_constraints=(
            HardConstraintEvidence(
                name="baseline_authority",
                unit="signed_boolean_margin",
                margin=0.0,
                evidence_source="p2-baseline",
            ),
        ),
        authority_backend="orekit-numerical-validation",
        authority_force_model_fingerprint="force-a",
    )


def test_validated_candidate_uses_authoritative_objectives_not_screening_scores() -> None:
    evaluation = build_optimized_operational_evaluation(
        strategy_id="optimized-1",
        candidate=_candidate(),
        hybrid=_hybrid(),
        identity=_identity(),
        outcome=_outcome(),
    )

    assert evaluation.operationally_credible
    assert evaluation.candidate_id == "nsga2-opt-001"
    assert tuple(item.value for item in evaluation.objectives) == pytest.approx((0.8, 3.0, 12.0))
    assert 999.0 not in tuple(item.value for item in evaluation.objectives)
    assert evaluation.authority_backend == "orekit-numerical-validation"
    assert evaluation.authority_force_model_fingerprint == "force-a"
    assert evaluation.high_fidelity_validation_id is not None
    assert evaluation.provenance["trigger_fraction"] == repr(0.5)
    assert any(item.name.startswith("hybrid_event.event-1.") for item in evaluation.hard_constraints)


def test_candidate_and_three_authoritative_baselines_form_recommendable_pareto_study() -> None:
    candidate = build_optimized_operational_evaluation(
        strategy_id="optimized-1",
        candidate=_candidate(),
        hybrid=_hybrid(),
        identity=_identity(),
        outcome=_outcome(),
    )
    baselines = (
        _baseline(OperationalStrategyKind.NO_CONTROL_BASELINE, "no-control", 2.0),
        _baseline(OperationalStrategyKind.RETURN_TO_CENTER_BASELINE, "rtc", 1.5),
        _baseline(OperationalStrategyKind.BOUNDARY_TO_BOUNDARY_BASELINE, "b2b", 1.2),
    )

    study = assemble_optimal_operations_study(
        study_id="optimal-final",
        baselines=baselines,
        candidate=candidate,
        recommendation_strategy_id="optimized-1",
    )

    assert study.recommendation_strategy_id == "optimized-1"
    assert len(study.evaluations) == 4


def test_incomplete_hybrid_candidate_cannot_be_recommended() -> None:
    hybrid = _hybrid(
        state=CredibilityState.CANDIDATE_AWAITING_VALIDATION,
        complete=False,
        authorized=False,
    )
    candidate = build_optimized_operational_evaluation(
        strategy_id="optimized-1",
        candidate=_candidate(),
        hybrid=hybrid,
        identity=_identity(),
        outcome=_outcome(),
    )
    assert not candidate.operationally_credible
    assert next(item for item in candidate.hard_constraints if item.name == "hybrid_strategy_authority").margin < 0.0

    baselines = (
        _baseline(OperationalStrategyKind.NO_CONTROL_BASELINE, "no-control", 2.0),
        _baseline(OperationalStrategyKind.RETURN_TO_CENTER_BASELINE, "rtc", 1.5),
        _baseline(OperationalStrategyKind.BOUNDARY_TO_BOUNDARY_BASELINE, "b2b", 1.2),
    )
    with pytest.raises(ValidationError, match="operationally credible"):
        assemble_optimal_operations_study(
            study_id="bad-recommendation",
            baselines=baselines,
            candidate=candidate,
            recommendation_strategy_id="optimized-1",
        )


def test_authority_fingerprint_mismatch_fails_closed() -> None:
    with pytest.raises(ValueError, match="fingerprint"):
        build_optimized_operational_evaluation(
            strategy_id="optimized-1",
            candidate=_candidate(),
            hybrid=_hybrid(fingerprint="force-b"),
            identity=_identity(force="force-a"),
            outcome=_outcome(),
        )


def test_conflicting_duplicate_hybrid_hard_evidence_fails_closed() -> None:
    base = _hybrid()
    first = base.records[0]
    assert first.evidence is not None
    assert first.evidence.correction_authority_receipt is not None
    conflicting_receipt = first.evidence.correction_authority_receipt.model_copy(
        update={
            "hard_constraints": (
                HardConstraintEvidence(
                    name="propellant_reserve_margin",
                    unit="kg",
                    margin=4.0,
                    evidence_source="different-evidence",
                ),
            )
        }
    )
    second = first.model_copy(
        update={
            "evidence": HybridEventExecutionEvidence(
                event_validation=first.evidence.event_validation,
                correction_authority_receipt=conflicting_receipt,
            )
        }
    )
    hybrid = base.model_copy(update={"records": (first, second)})

    with pytest.raises(ValueError, match="conflicting duplicate"):
        build_optimized_operational_evaluation(
            strategy_id="optimized-1",
            candidate=_candidate(),
            hybrid=hybrid,
            identity=_identity(),
            outcome=_outcome(),
        )
