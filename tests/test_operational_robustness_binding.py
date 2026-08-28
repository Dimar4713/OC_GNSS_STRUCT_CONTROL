from __future__ import annotations

import pytest
from pydantic import ValidationError

from constellation_control.optimization.operational_robustness import (
    RealizationStatus,
    StrategyRealizationOutcome,
    StrategyRobustnessEvidence,
    common_sample_set_from_generated,
)
from constellation_control.optimization.operational_robustness_binding import (
    bind_operational_robustness,
    robustness_uncertainty_model_id,
)
from constellation_control.optimization.operations import (
    CredibilityState,
    HardConstraintEvidence,
    NamedObjectiveValue,
    ObjectiveDirection,
    OperationalStrategyEvaluation,
    OperationalStrategyKind,
    OperationalStrategyStudy,
    OperationalStudyIdentity,
)
from constellation_control.uncertainty.campaign import (
    DistributionKind,
    RobustnessCampaignConfig,
    ScalarUncertaintyConfig,
    generate_campaign_samples,
)


FINGERPRINT = "a" * 64
BACKEND = "orekit-numerical-test"


def _campaign(samples: int = 4) -> RobustnessCampaignConfig:
    return RobustnessCampaignConfig(
        campaign_id="ops-robustness",
        samples=samples,
        workers=2,
        seed=4713,
        accepted_candidate_id="candidate-01",
        scalar_uncertainties=(
            ScalarUncertaintyConfig(
                name="initial.TEST.delta_a_m",
                distribution=DistributionKind.NORMAL,
                sigma=1.0,
            ),
        ),
        worst_metric="delta_v_m_s",
        resume=False,
    )


def _evidence(
    strategy_id: str,
    *,
    failed: tuple[int, ...] = (),
    phase_violation: tuple[int, ...] = (),
    backend: str = BACKEND,
) -> StrategyRobustnessEvidence:
    config = _campaign()
    samples = generate_campaign_samples(config)
    common = common_sample_set_from_generated(config, samples)
    outcomes: list[StrategyRealizationOutcome] = []
    for index, sample in enumerate(common.samples):
        if index in failed:
            outcomes.append(
                StrategyRealizationOutcome(
                    realization=index,
                    sample_sha256=sample.sample_sha256,
                    status=RealizationStatus.FAILED,
                    failure_reason="authority failed",
                )
            )
        else:
            outcomes.append(
                StrategyRealizationOutcome(
                    realization=index,
                    sample_sha256=sample.sample_sha256,
                    status=RealizationStatus.COMPLETED,
                    metrics={"delta_v_m_s": 1.0 + index},
                    violations={"phase_corridor": index in phase_violation},
                    authority_backend=backend,
                    authority_force_model_fingerprint=FINGERPRINT,
                )
            )
    return StrategyRobustnessEvidence(
        strategy_id=strategy_id,
        common_samples=common,
        outcomes=tuple(outcomes),
    )


def _identity(evidence: StrategyRobustnessEvidence) -> OperationalStudyIdentity:
    return OperationalStudyIdentity(
        scenario_id="scenario",
        initial_epoch_iso="2026-01-01T00:00:00Z",
        seed=1,
        force_model_fingerprint=FINGERPRINT,
        frame="EME2000",
        time_scale="UTC",
        integrator_identity="integrator-v1",
        constraints_identity="constraints-v1",
        execution_policy_identity="policy-v1",
        campaign_horizon_s=86400.0,
        coast_horizon_s=3600.0,
        coast_output_step_s=60.0,
        authority_times_s=(0.0, 60.0),
        maneuver_windows=(True,),
        uncertainty_model_id=robustness_uncertainty_model_id(evidence),
    )


def _evaluation(
    strategy_id: str,
    kind: OperationalStrategyKind,
    identity: OperationalStudyIdentity,
) -> OperationalStrategyEvaluation:
    candidate = kind == OperationalStrategyKind.OPTIMIZED_CANDIDATE
    return OperationalStrategyEvaluation(
        strategy_id=strategy_id,
        kind=kind,
        credibility_state=(
            CredibilityState.AUTHORITATIVELY_VALIDATED_CANDIDATE
            if candidate
            else CredibilityState.AUTHORITATIVE_BASELINE
        ),
        identity=identity,
        candidate_id="candidate-01" if candidate else None,
        campaign_termination_reason="duration-reached",
        correction_count=1,
        cumulative_delta_v_m_s=1.0,
        cumulative_propellant_used_kg=0.1,
        objectives=(
            NamedObjectiveValue(
                name="delta_v",
                unit="m/s",
                direction=ObjectiveDirection.MINIMIZE,
                value=1.0,
            ),
        ),
        hard_constraints=(
            HardConstraintEvidence(
                name="base-safety",
                unit="margin",
                margin=1.0,
                evidence_source="authority",
            ),
        ),
        authority_backend=BACKEND,
        authority_force_model_fingerprint=FINGERPRINT,
        high_fidelity_validation_id="validation-1" if candidate else None,
    )


def test_complete_robustness_binds_structured_counts_probabilities_and_statistics() -> None:
    evidence = _evidence("rtc", phase_violation=(3,))
    evaluation = _evaluation("rtc", OperationalStrategyKind.RETURN_TO_CENTER_BASELINE, _identity(evidence))
    bound = bind_operational_robustness(evaluation, evidence)

    assert bound.robustness_available is True
    assert bound.robustness_reason is None
    assert bound.robustness_evidence is not None
    assert bound.robustness_evidence.total_realizations == 4
    assert bound.robustness_evidence.completed_realizations == 4
    assert bound.robustness_evidence.failed_realizations == 0
    assert bound.robustness_evidence.conservative_violation_probability["phase_corridor"] == pytest.approx(0.25)
    assert bound.robustness_evidence.metric_statistics["delta_v_m_s"]["count"] == 4


def test_unavailable_robustness_stays_unavailable_and_has_no_zero_risk_payload() -> None:
    evidence = _evidence("rtc")
    evaluation = _evaluation("rtc", OperationalStrategyKind.RETURN_TO_CENTER_BASELINE, _identity(evidence))
    assert evaluation.robustness_available is False
    assert evaluation.robustness_evidence is None
    assert evaluation.robustness_reason == "uncertainty campaign not supplied"


def test_required_recommendation_rejects_incomplete_robustness() -> None:
    rtc_evidence = _evidence("rtc", failed=(1,))
    identity = _identity(rtc_evidence)
    no_control = _evaluation("no-control", OperationalStrategyKind.NO_CONTROL_BASELINE, identity)
    rtc = bind_operational_robustness(
        _evaluation("rtc", OperationalStrategyKind.RETURN_TO_CENTER_BASELINE, identity),
        rtc_evidence,
    )
    b2b = _evaluation("b2b", OperationalStrategyKind.BOUNDARY_TO_BOUNDARY_BASELINE, identity)

    with pytest.raises(ValidationError, match="complete robustness realizations"):
        OperationalStrategyStudy(
            study_id="study",
            evaluations=(no_control, rtc, b2b),
            recommendation_strategy_id="rtc",
            robustness_required_for_recommendation=True,
        )


def test_hard_probability_threshold_becomes_negative_noncompensable_margin() -> None:
    evidence = _evidence("rtc", phase_violation=(3,))
    evaluation = _evaluation("rtc", OperationalStrategyKind.RETURN_TO_CENTER_BASELINE, _identity(evidence))
    bound = bind_operational_robustness(
        evaluation,
        evidence,
        violation_probability_limits={"phase_corridor": 0.10},
    )
    margin = next(item for item in bound.hard_constraints if item.name == "robustness.phase_corridor.probability_max")
    assert margin.margin == pytest.approx(-0.15)
    assert bound.operationally_credible is False


def test_explicit_probability_objective_is_added_only_when_requested() -> None:
    evidence = _evidence("rtc", phase_violation=(3,))
    evaluation = _evaluation("rtc", OperationalStrategyKind.RETURN_TO_CENTER_BASELINE, _identity(evidence))
    plain = bind_operational_robustness(evaluation, evidence)
    assert len(plain.objectives) == 1

    with_objective = bind_operational_robustness(
        evaluation,
        evidence,
        violation_probability_objectives=("phase_corridor",),
    )
    objective = with_objective.objectives[-1]
    assert objective.name == "robustness.phase_corridor.violation_probability"
    assert objective.direction == ObjectiveDirection.MINIMIZE
    assert objective.value == pytest.approx(0.25)


def test_strategy_uncertainty_and_authority_mismatch_fail_closed() -> None:
    evidence = _evidence("rtc")
    identity = _identity(evidence).model_copy(update={"uncertainty_model_id": "deterministic-v1"})
    evaluation = _evaluation("rtc", OperationalStrategyKind.RETURN_TO_CENTER_BASELINE, identity)
    with pytest.raises(ValueError, match="uncertainty identity"):
        bind_operational_robustness(evaluation, evidence)

    identity_ok = _identity(evidence)
    wrong_backend = _evaluation("rtc", OperationalStrategyKind.RETURN_TO_CENTER_BASELINE, identity_ok).model_copy(
        update={"authority_backend": "other-backend"}
    )
    with pytest.raises(ValueError, match="backend"):
        bind_operational_robustness(wrong_backend, evidence)
