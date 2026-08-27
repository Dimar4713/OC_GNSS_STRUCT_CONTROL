from __future__ import annotations

import json
from pathlib import Path

import pytest

from constellation_control.optimization.operational_robustness import (
    CommonSampleReference,
    CommonSampleSetIdentity,
    RealizationStatus,
    StrategyRealizationOutcome,
    StrategyRobustnessEvidence,
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
from constellation_control.preview.optimal_operations_authority import (
    PreviewOptimizedAuthorityReduction,
    PreviewOptimizedCandidateSelection,
)
from constellation_control.preview.optimal_operations_decision import (
    PreviewOperationalDecisionPolicy,
    build_preview_operational_decision,
    write_preview_operational_decision,
)
from constellation_control.preview.optimal_operations_execution import (
    PreviewBaselineEvidence,
    PreviewOptimalOperationsFoundationRun,
    PreviewScreeningCandidateEvidence,
    PreviewScreeningEvidence,
)
from constellation_control.preview.optimal_operations_profile import PreviewOptimalOperationsPreflight


SAMPLING_SHA = "a" * 64
FORCE_SHA = "b" * 64


def _identity() -> OperationalStudyIdentity:
    return OperationalStudyIdentity(
        scenario_id="ops-decision-test",
        initial_epoch_iso="2026-01-01T00:00:00+00:00",
        seed=42,
        force_model_fingerprint=FORCE_SHA,
        frame="EME2000",
        time_scale="UTC",
        integrator_identity="c" * 64,
        constraints_identity="d" * 64,
        execution_policy_identity="e" * 64,
        campaign_horizon_s=3600.0,
        coast_horizon_s=600.0,
        coast_output_step_s=60.0,
        authority_times_s=(0.0, 60.0, 120.0),
        maneuver_windows=(True, True),
        uncertainty_model_id=f"robustness:{SAMPLING_SHA}",
    )


def _objectives(value: float) -> tuple[NamedObjectiveValue, ...]:
    return (
        NamedObjectiveValue(
            name="propellant_rate",
            unit="kg/Julian-year",
            direction=ObjectiveDirection.MINIMIZE,
            value=value,
        ),
        NamedObjectiveValue(
            name="correction_frequency",
            unit="events/Julian-year",
            direction=ObjectiveDirection.MINIMIZE,
            value=value,
        ),
    )


def _evaluation(kind: OperationalStrategyKind, strategy_id: str, value: float) -> OperationalStrategyEvaluation:
    validated = kind == OperationalStrategyKind.OPTIMIZED_CANDIDATE
    return OperationalStrategyEvaluation(
        strategy_id=strategy_id,
        kind=kind,
        credibility_state=(
            CredibilityState.AUTHORITATIVELY_VALIDATED_CANDIDATE
            if validated
            else CredibilityState.AUTHORITATIVE_BASELINE
        ),
        identity=_identity(),
        candidate_id="candidate-001" if validated else None,
        campaign_termination_reason="campaign-horizon-reached",
        correction_count=2,
        corrections_per_julian_year=2.0,
        cumulative_delta_v_m_s=value,
        delta_v_m_s_per_julian_year=value,
        cumulative_propellant_used_kg=value,
        propellant_kg_per_julian_year=value,
        projected_years_to_reserve=10.0,
        objectives=_objectives(value),
        hard_constraints=(
            HardConstraintEvidence(
                name="phase_corridor_margin",
                unit="rad",
                margin=0.01,
                evidence_source="authoritative-test",
            ),
        ),
        authority_backend="orekit-numerical-test",
        authority_force_model_fingerprint=FORCE_SHA,
        high_fidelity_validation_id="hybrid-validation-001" if validated else None,
    )


def _foundation() -> PreviewOptimalOperationsFoundationRun:
    preflight = PreviewOptimalOperationsPreflight.model_construct(
        schema_version="preview-optimal-operations-study-profile-v1",
        study_id="preview-decision-test",
        scenario_name="scenario.yaml",
        scenario_config_hash="f" * 64,
        identity=_identity(),
        controlled_deputy_id="DEP",
        reference_id="REF",
        search_config={},
        objective_definitions=(),
        hard_constraint_definitions=(),
        robustness_enabled=True,
        robustness_recommendation_required=True,
        robustness_campaign_id="paired-campaign",
        robustness_uncertainty_model_id="paired-model",
        robustness_sampling_model_sha256=SAMPLING_SHA,
        preflight_sha256="1" * 64,
    )
    baseline_strategies = (
        _evaluation(OperationalStrategyKind.NO_CONTROL_BASELINE, "baseline-no-control", 4.0),
        _evaluation(OperationalStrategyKind.RETURN_TO_CENTER_BASELINE, "baseline-return-to-center", 3.0),
        _evaluation(OperationalStrategyKind.BOUNDARY_TO_BOUNDARY_BASELINE, "baseline-boundary-to-boundary", 2.0),
    )
    baselines = tuple(
        PreviewBaselineEvidence.model_construct(strategy=item) for item in baseline_strategies
    )
    candidate = PreviewScreeningCandidateEvidence(
        candidate_id="candidate-001",
        stage="nsga2",
        trigger_fraction=0.5,
        target_fraction=0.25,
        objectives=(999.0, 998.0),
        hard_margins=(1.0,),
        metrics={},
        feasible=True,
        screening_only=True,
    )
    screening = PreviewScreeningEvidence(
        candidates=(candidate,),
        pareto_candidate_ids=(candidate.candidate_id,),
        search_config={},
        screening_only=True,
        evidence_sha256="2" * 64,
    )
    return PreviewOptimalOperationsFoundationRun(
        preflight=preflight,
        baselines=baselines,
        screening=screening,
        recommendation_strategy_id=None,
    )


def _authority(foundation: PreviewOptimalOperationsFoundationRun) -> PreviewOptimizedAuthorityReduction:
    candidate = foundation.screening.candidates[0]
    selection = PreviewOptimizedCandidateSelection(
        candidate_id=candidate.candidate_id,
        strategy_id="optimized-candidate-001",
        preflight_sha256=foundation.preflight.preflight_sha256,
        screening_evidence_sha256=foundation.screening.evidence_sha256,
        screening_candidate=candidate,
        selection_sha256="3" * 64,
    )
    return PreviewOptimizedAuthorityReduction.model_construct(
        selection=selection,
        hybrid=None,
        evaluation=_evaluation(
            OperationalStrategyKind.OPTIMIZED_CANDIDATE,
            "optimized-candidate-001",
            1.0,
        ),
        recommendation_strategy_id=None,
        robustness_available=False,
    )


def _samples() -> CommonSampleSetIdentity:
    return CommonSampleSetIdentity(
        campaign_id="paired-campaign",
        master_seed=4713,
        sampling_model_sha256=SAMPLING_SHA,
        samples=(
            CommonSampleReference(realization=0, realization_seed=100, sample_sha256="4" * 64),
            CommonSampleReference(realization=1, realization_seed=101, sample_sha256="5" * 64),
        ),
    )


def _robustness(strategy_id: str, *, failed_second: bool = False) -> StrategyRobustnessEvidence:
    common = _samples()
    first = StrategyRealizationOutcome(
        realization=0,
        sample_sha256=common.samples[0].sample_sha256,
        status=RealizationStatus.COMPLETED,
        metrics={"propellant_rate": 1.0},
        violations={"phase_corridor": False},
        authority_backend="orekit-numerical-test",
        authority_force_model_fingerprint=FORCE_SHA,
    )
    second = (
        StrategyRealizationOutcome(
            realization=1,
            sample_sha256=common.samples[1].sample_sha256,
            status=RealizationStatus.FAILED,
            failure_reason="numerical-failure-test",
        )
        if failed_second
        else StrategyRealizationOutcome(
            realization=1,
            sample_sha256=common.samples[1].sample_sha256,
            status=RealizationStatus.COMPLETED,
            metrics={"propellant_rate": 1.1},
            violations={"phase_corridor": False},
            authority_backend="orekit-numerical-test",
            authority_force_model_fingerprint=FORCE_SHA,
        )
    )
    return StrategyRobustnessEvidence(
        strategy_id=strategy_id,
        common_samples=common,
        outcomes=(first, second),
    )


def _all_robustness(foundation: PreviewOptimalOperationsFoundationRun) -> tuple[StrategyRobustnessEvidence, ...]:
    ids = tuple(item.strategy.strategy_id for item in foundation.baselines) + ("optimized-candidate-001",)
    return tuple(_robustness(strategy_id) for strategy_id in ids)


def _policy() -> PreviewOperationalDecisionPolicy:
    return PreviewOperationalDecisionPolicy(
        recommendation_strategy_id="optimized-candidate-001",
        robustness_required=True,
        violation_probability_limits={"phase_corridor": 0.0, "incomplete_realization": 0.0},
        violation_probability_objectives=(),
    )


def test_paired_robustness_builds_credible_pareto_and_recommendation(tmp_path: Path) -> None:
    foundation = _foundation()
    authority = _authority(foundation)
    robustness = _all_robustness(foundation)
    result = build_preview_operational_decision(foundation, authority, robustness, _policy())

    assert result.study.recommendation_strategy_id == "optimized-candidate-001"
    assert result.credible_pareto_strategy_ids == ("optimized-candidate-001",)
    assert all(item.robustness_available for item in result.study.evaluations)
    assert all(item.robustness_evidence is not None for item in result.study.evaluations)

    artifacts = write_preview_operational_decision(tmp_path, foundation, authority, robustness, result)
    manifest = json.loads(Path(artifacts.manifest_path).read_text(encoding="utf-8"))
    assert manifest["recommendation_strategy_id"] == "optimized-candidate-001"
    assert manifest["credible_pareto_strategy_ids"] == ["optimized-candidate-001"]
    assert manifest["common_sampling_model_sha256"] == SAMPLING_SHA


def test_incomplete_robustness_blocks_required_recommendation() -> None:
    foundation = _foundation()
    authority = _authority(foundation)
    robustness = list(_all_robustness(foundation))
    robustness[-1] = _robustness("optimized-candidate-001", failed_second=True)
    with pytest.raises(ValueError, match="final recommendation requires complete robustness realizations"):
        build_preview_operational_decision(foundation, authority, tuple(robustness), _policy())


def test_sampling_model_mismatch_fails_closed() -> None:
    foundation = _foundation()
    foundation = foundation.model_copy(
        update={
            "preflight": foundation.preflight.model_copy(
                update={"robustness_sampling_model_sha256": "9" * 64}
            )
        }
    )
    with pytest.raises(ValueError, match="sampling model hash"):
        build_preview_operational_decision(
            foundation,
            _authority(foundation),
            _all_robustness(foundation),
            _policy(),
        )


def test_non_pareto_recommendation_is_rejected() -> None:
    foundation = _foundation()
    bad_policy = _policy().model_copy(update={"recommendation_strategy_id": "baseline-no-control"})
    with pytest.raises(ValueError):
        build_preview_operational_decision(
            foundation,
            _authority(foundation),
            _all_robustness(foundation),
            bad_policy,
        )
