from __future__ import annotations

import pytest
from pydantic import ValidationError

from constellation_control.optimization.operations import (
    CredibilityState,
    HardConstraintEvidence,
    NamedObjectiveValue,
    ObjectiveDirection,
    OperationalStrategyEvaluation,
    OperationalStrategyKind,
    OperationalStrategyStudy,
    OperationalStudyIdentity,
    credible_pareto_strategy_ids,
)


def _identity(*, force: str = "force-a") -> OperationalStudyIdentity:
    return OperationalStudyIdentity(
        scenario_id="ops-study",
        initial_epoch_iso="2026-01-01T00:00:00+00:00",
        seed=42,
        force_model_fingerprint=force,
        frame="GCRF",
        time_scale="UTC",
        integrator_identity="dop853:1e-10:1e-12",
        constraints_identity="constraints-v1:abc",
        execution_policy_identity="mpc-policy-v1:def",
        campaign_horizon_s=31_557_600.0,
        coast_horizon_s=86_400.0,
        coast_output_step_s=300.0,
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


def _constraints(*, phase: float = 0.01, safety: float = 1000.0, reserve: float = 5.0) -> tuple[HardConstraintEvidence, ...]:
    return (
        HardConstraintEvidence(
            name="phase_corridor_margin",
            unit="rad",
            margin=phase,
            evidence_source="p2-campaign",
        ),
        HardConstraintEvidence(
            name="fleet_distance_margin",
            unit="m",
            margin=safety,
            evidence_source="high-fidelity-replay",
        ),
        HardConstraintEvidence(
            name="propellant_reserve_margin",
            unit="kg",
            margin=reserve,
            evidence_source="authority-ledger",
        ),
    )


def _baseline(kind: OperationalStrategyKind, strategy_id: str, *, fuel: float) -> OperationalStrategyEvaluation:
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
        hard_constraints=_constraints(),
        authority_backend="orekit-numerical-validation",
        authority_force_model_fingerprint="force-a",
    )


def _validated_candidate(
    *,
    strategy_id: str = "candidate-good",
    fuel: float = 0.8,
    corrections: float = 3.0,
    lifetime: float = 12.0,
) -> OperationalStrategyEvaluation:
    return OperationalStrategyEvaluation(
        strategy_id=strategy_id,
        kind=OperationalStrategyKind.OPTIMIZED_CANDIDATE,
        credibility_state=CredibilityState.AUTHORITATIVELY_VALIDATED_CANDIDATE,
        identity=_identity(),
        candidate_id="nsga2-001",
        campaign_termination_reason="campaign-horizon-reached",
        correction_count=3,
        corrections_per_julian_year=corrections,
        cumulative_delta_v_m_s=0.08,
        delta_v_m_s_per_julian_year=0.08,
        cumulative_propellant_used_kg=fuel,
        propellant_kg_per_julian_year=fuel,
        projected_years_to_reserve=lifetime,
        objectives=_objectives(fuel=fuel, corrections=corrections, lifetime=lifetime),
        hard_constraints=_constraints(),
        authority_backend="orekit-numerical-validation",
        authority_force_model_fingerprint="force-a",
        high_fidelity_validation_id="validation-001",
    )


def test_incompatible_physical_identity_cannot_be_compared() -> None:
    first = _baseline(OperationalStrategyKind.NO_CONTROL_BASELINE, "no-control", fuel=0.0)
    second = _baseline(OperationalStrategyKind.RETURN_TO_CENTER_BASELINE, "rtc", fuel=1.0)
    second = second.model_copy(update={"identity": _identity(force="force-b")})

    with pytest.raises(ValidationError, match="incompatible physical/control identity"):
        OperationalStrategyStudy(study_id="bad", evaluations=(first, second))


def test_unvalidated_candidate_is_not_operationally_credible() -> None:
    candidate = OperationalStrategyEvaluation(
        strategy_id="candidate-pending",
        kind=OperationalStrategyKind.OPTIMIZED_CANDIDATE,
        credibility_state=CredibilityState.CANDIDATE_AWAITING_VALIDATION,
        identity=_identity(),
        candidate_id="screen-001",
        campaign_termination_reason="screening-complete",
        correction_count=2,
        cumulative_delta_v_m_s=0.05,
        cumulative_propellant_used_kg=0.5,
        objectives=_objectives(fuel=0.5, corrections=2.0, lifetime=20.0),
        hard_constraints=_constraints(),
    )

    assert candidate.hard_constraints_passed
    assert not candidate.operationally_credible


def test_validated_candidate_cannot_hide_hard_constraint_violation() -> None:
    with pytest.raises(ValidationError, match="cannot violate hard constraints"):
        OperationalStrategyEvaluation(
            strategy_id="unsafe",
            kind=OperationalStrategyKind.OPTIMIZED_CANDIDATE,
            credibility_state=CredibilityState.AUTHORITATIVELY_VALIDATED_CANDIDATE,
            identity=_identity(),
            candidate_id="unsafe-001",
            campaign_termination_reason="validation-complete",
            correction_count=1,
            cumulative_delta_v_m_s=0.001,
            cumulative_propellant_used_kg=0.01,
            objectives=_objectives(fuel=0.01, corrections=1.0, lifetime=100.0),
            hard_constraints=_constraints(safety=-1.0),
            authority_backend="orekit-numerical-validation",
            authority_force_model_fingerprint="force-a",
            high_fidelity_validation_id="validation-unsafe",
        )


def test_rejected_candidate_with_better_soft_scores_never_enters_credible_pareto() -> None:
    baseline = _baseline(
        OperationalStrategyKind.BOUNDARY_TO_BOUNDARY_BASELINE,
        "b2b",
        fuel=1.0,
    )
    rejected = OperationalStrategyEvaluation(
        strategy_id="rejected",
        kind=OperationalStrategyKind.OPTIMIZED_CANDIDATE,
        credibility_state=CredibilityState.REJECTED_BY_AUTHORITY,
        identity=_identity(),
        candidate_id="nsga2-rejected",
        campaign_termination_reason="maneuver-authority-rejected:safety",
        correction_count=1,
        cumulative_delta_v_m_s=0.001,
        cumulative_propellant_used_kg=0.01,
        projected_years_to_reserve=1000.0,
        objectives=_objectives(fuel=0.01, corrections=0.1, lifetime=1000.0),
        hard_constraints=_constraints(safety=-10.0),
        authority_backend="orekit-numerical-validation",
        authority_force_model_fingerprint="force-a",
        high_fidelity_validation_id="validation-rejected",
    )
    study = OperationalStrategyStudy(study_id="pareto", evaluations=(baseline, rejected))

    assert credible_pareto_strategy_ids(study) == ("b2b",)


def test_final_recommendation_requires_all_three_baselines_and_credible_pareto_membership() -> None:
    no_control = _baseline(OperationalStrategyKind.NO_CONTROL_BASELINE, "no-control", fuel=2.0)
    rtc = _baseline(OperationalStrategyKind.RETURN_TO_CENTER_BASELINE, "rtc", fuel=1.5)
    b2b = _baseline(OperationalStrategyKind.BOUNDARY_TO_BOUNDARY_BASELINE, "b2b", fuel=1.2)
    candidate = _validated_candidate()

    study = OperationalStrategyStudy(
        study_id="complete",
        evaluations=(no_control, rtc, b2b, candidate),
        recommendation_strategy_id="candidate-good",
    )
    assert study.recommendation_strategy_id == "candidate-good"
    assert "candidate-good" in credible_pareto_strategy_ids(study)

    with pytest.raises(ValidationError, match="requires all three P2 operational baselines"):
        OperationalStrategyStudy(
            study_id="missing-baselines",
            evaluations=(b2b, candidate),
            recommendation_strategy_id="candidate-good",
        )
