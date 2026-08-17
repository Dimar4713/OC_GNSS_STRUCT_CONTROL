import numpy as np
import pytest

from constellation_control.optimization.design import local_optimize
from constellation_control.optimization.pipeline import (
    CandidateEvaluation,
    DesignPipelineConfig,
    RecommendationPolicyConfig,
    run_design_pipeline,
)
from constellation_control.optimization.validation import ValidationOutcome


def _config() -> DesignPipelineConfig:
    return DesignPipelineConfig(
        bounds=((-1.0, 1.0),) * 6,
        lhs_samples=12,
        grid_levels=0,
        local_seeds=2,
        local_method="SLSQP",
        nsga_population=12,
        nsga_generations=4,
        top_k=2,
        seed=4713,
        recommendation=RecommendationPolicyConfig(
            version="weighted-normalized-v1",
            weights=(0.5, 0.3, 0.2),
        ),
    )


def _evaluate(vector: np.ndarray) -> CandidateEvaluation:
    stability = float((vector[0] - 0.2) ** 2 + 0.25 * np.dot(vector[1:], vector[1:]))
    delta_v = float(np.linalg.norm(vector))
    minimum_distance_proxy = float(2.0 - abs(vector[0]) - 0.1 * np.linalg.norm(vector[1:]))
    margins = (
        float(0.75 - abs(vector[0])),
        float(1.2 - np.linalg.norm(vector[1:3])),
    )
    return CandidateEvaluation(
        objectives=(stability, delta_v, -minimum_distance_proxy),
        constraint_margins=margins,
        metrics={
            "stability": stability,
            "delta_v_proxy": delta_v,
            "minimum_distance_proxy": minimum_distance_proxy,
        },
    )


def _validator(vector: np.ndarray) -> ValidationOutcome:
    return ValidationOutcome(
        backend="orekit-numerical-validation",
        metrics={
            "validated_stability": float(np.dot(vector, vector)),
            "validated_minimum_distance": float(1000.0 + 10.0 * vector[0]),
        },
    )


def test_local_optimizer_enforces_hard_margin() -> None:
    result = local_optimize(
        np.asarray([0.1]),
        lambda vector: -float(vector[0]),
        ((0.0, 2.0),),
        constraints=(lambda vector: 0.5 - float(vector[0]),),
    )
    assert result.success
    assert result.x[0] <= 0.50001
    assert result.x[0] >= 0.49


def test_pipeline_is_deterministic_and_pareto_set_is_feasible() -> None:
    first = run_design_pipeline(_config(), evaluator=_evaluate, validator=_validator)
    second = run_design_pipeline(_config(), evaluator=_evaluate, validator=_validator)

    assert first == second
    assert first.policy_version == "weighted-normalized-v1"
    assert len(first.validation) == 2
    by_id = {record.candidate_id: record for record in first.records}
    assert first.recommendation_candidate_id in first.pareto_candidate_ids
    assert all(by_id[candidate_id].feasible for candidate_id in first.pareto_candidate_ids)
    assert all(item.backend == "orekit-numerical-validation" for item in first.validation)


def test_pipeline_rejects_non_authoritative_top_k_validation() -> None:
    def screening_fallback(vector: np.ndarray) -> ValidationOutcome:
        del vector
        return ValidationOutcome(backend="synthetic-j2-screening", metrics={"value": 1.0})

    with pytest.raises(RuntimeError, match="non-authoritative backend"):
        run_design_pipeline(_config(), evaluator=_evaluate, validator=screening_fallback)


def test_recommendation_policy_requires_one_weight_per_objective() -> None:
    bad = _config().model_copy(
        update={"recommendation": RecommendationPolicyConfig(weights=(1.0, 1.0))}
    )
    with pytest.raises(ValueError, match="objective count mismatch"):
        run_design_pipeline(bad, evaluator=_evaluate, validator=_validator)
