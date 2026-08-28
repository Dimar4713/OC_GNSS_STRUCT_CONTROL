from __future__ import annotations

from collections.abc import Mapping, Sequence

from constellation_control.optimization.operational_robustness import (
    RealizationStatus,
    StrategyRobustnessEvidence,
    aggregate_strategy_robustness,
)
from constellation_control.optimization.operations import (
    HardConstraintEvidence,
    NamedObjectiveValue,
    ObjectiveDirection,
    OperationalRobustnessSummary,
    OperationalStrategyEvaluation,
)


def robustness_uncertainty_model_id(evidence: StrategyRobustnessEvidence) -> str:
    return f"robustness:{evidence.common_samples.sampling_model_sha256}"


def _completed_authority(evidence: StrategyRobustnessEvidence) -> tuple[str, str]:
    completed = [item for item in evidence.outcomes if item.status == RealizationStatus.COMPLETED]
    if not completed:
        raise ValueError("robustness evidence has no completed authoritative realizations")
    pairs: set[tuple[str, str]] = set()
    for item in completed:
        if item.authority_backend is None or item.authority_force_model_fingerprint is None:
            raise ValueError("completed robustness realization requires authority backend/fingerprint")
        pairs.add((item.authority_backend, item.authority_force_model_fingerprint))
    if len(pairs) != 1:
        raise ValueError("robustness completed realizations have inconsistent authority lineage")
    return next(iter(pairs))


def bind_operational_robustness(
    evaluation: OperationalStrategyEvaluation,
    evidence: StrategyRobustnessEvidence,
    *,
    violation_probability_limits: Mapping[str, float] | None = None,
    violation_probability_objectives: Sequence[str] = (),
) -> OperationalStrategyEvaluation:
    """Attach paired robustness evidence without inventing missing risk or weights.

    Hard probability limits are converted to signed margins `limit - observed`.
    Soft probability objectives are added only when explicitly requested and are
    always minimization objectives.
    """

    if evaluation.strategy_id != evidence.strategy_id:
        raise ValueError("robustness strategy id does not match operational evaluation")
    expected_uncertainty_id = robustness_uncertainty_model_id(evidence)
    if evaluation.identity.uncertainty_model_id != expected_uncertainty_id:
        raise ValueError("operational uncertainty identity does not match robustness sample model")

    aggregate = aggregate_strategy_robustness(evidence)
    authority_backend, authority_fingerprint = _completed_authority(evidence)
    if evaluation.authority_backend is not None and evaluation.authority_backend != authority_backend:
        raise ValueError("robustness backend does not match operational authority backend")
    if (
        evaluation.authority_force_model_fingerprint is not None
        and evaluation.authority_force_model_fingerprint != authority_fingerprint
    ):
        raise ValueError("robustness force fingerprint does not match operational authority fingerprint")

    summary = OperationalRobustnessSummary(
        campaign_id=evidence.common_samples.campaign_id,
        sampling_model_sha256=evidence.common_samples.sampling_model_sha256,
        total_realizations=aggregate.total_realizations,
        completed_realizations=aggregate.completed_realizations,
        failed_realizations=aggregate.failed_realizations,
        missing_realizations=aggregate.missing_realizations,
        conservative_violation_probability=dict(sorted(aggregate.conservative_violation_probability.items())),
        metric_statistics={
            name: dict(sorted(values.items()))
            for name, values in sorted(aggregate.metric_statistics.items())
        },
        authority_backend=authority_backend,
        authority_force_model_fingerprint=authority_fingerprint,
    )

    constraints = list(evaluation.hard_constraints)
    for name, limit in sorted((violation_probability_limits or {}).items()):
        if not 0.0 <= limit <= 1.0:
            raise ValueError("robustness violation probability limit must be in [0, 1]")
        if name not in summary.conservative_violation_probability:
            raise ValueError(f"robustness evidence does not contain violation probability: {name}")
        observed = summary.conservative_violation_probability[name]
        constraints.append(
            HardConstraintEvidence(
                name=f"robustness.{name}.probability_max",
                unit="probability",
                margin=limit - observed,
                evidence_source=(
                    f"paired robustness campaign {summary.campaign_id}; conservative denominator "
                    f"{summary.total_realizations}"
                ),
            )
        )

    objectives = list(evaluation.objectives)
    for name in violation_probability_objectives:
        if name not in summary.conservative_violation_probability:
            raise ValueError(f"robustness evidence does not contain objective probability: {name}")
        objectives.append(
            NamedObjectiveValue(
                name=f"robustness.{name}.violation_probability",
                unit="probability",
                direction=ObjectiveDirection.MINIMIZE,
                value=summary.conservative_violation_probability[name],
            )
        )

    return evaluation.model_copy(
        update={
            "robustness_available": True,
            "robustness_reason": None,
            "robustness_evidence": summary,
            "objectives": tuple(objectives),
            "hard_constraints": tuple(constraints),
        }
    )
