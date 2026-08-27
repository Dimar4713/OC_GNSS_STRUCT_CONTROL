from __future__ import annotations

import hashlib
import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, model_validator

from constellation_control.optimization.operational_robustness import StrategyRobustnessEvidence
from constellation_control.optimization.operational_robustness_binding import (
    bind_operational_robustness,
    robustness_uncertainty_model_id,
)
from constellation_control.optimization.operations import (
    OperationalStrategyStudy,
    credible_pareto_strategy_ids,
)
from constellation_control.optimization.optimal_operations_orchestration import (
    assemble_optimal_operations_study,
)
from constellation_control.preview.optimal_operations_authority import (
    PreviewOptimizedAuthorityReduction,
)
from constellation_control.preview.optimal_operations_execution import (
    PreviewOptimalOperationsFoundationRun,
)


class PreviewOperationalDecisionPolicy(BaseModel):
    """Explicit decision rule; no robustness threshold is supplied by Preview."""

    model_config = ConfigDict(frozen=True)

    recommendation_strategy_id: str = Field(min_length=1)
    robustness_required: bool
    violation_probability_limits: dict[str, float]
    violation_probability_objectives: tuple[str, ...]

    @model_validator(mode="after")
    def validate_policy(self) -> PreviewOperationalDecisionPolicy:
        if len(self.violation_probability_objectives) != len(set(self.violation_probability_objectives)):
            raise ValueError("robustness probability objectives must be unique")
        for name, limit in self.violation_probability_limits.items():
            if not name:
                raise ValueError("robustness probability limit names must be non-empty")
            if not 0.0 <= limit <= 1.0:
                raise ValueError("robustness probability limits must be in [0, 1]")
        if any(not name for name in self.violation_probability_objectives):
            raise ValueError("robustness probability objective names must be non-empty")
        return self


class PreviewOperationalDecisionResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    study: OperationalStrategyStudy
    credible_pareto_strategy_ids: tuple[str, ...]
    common_campaign_id: str
    common_sampling_model_sha256: str
    decision_policy: PreviewOperationalDecisionPolicy
    decision_evidence_sha256: str


class PreviewOperationalDecisionArtifacts(BaseModel):
    model_config = ConfigDict(frozen=True)

    run_dir: str
    study_path: str
    robustness_path: str
    decision_path: str
    manifest_path: str
    decision_evidence_sha256: str


def _digest(payload: object) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _validate_common_robustness(
    foundation: PreviewOptimalOperationsFoundationRun,
    evidence: tuple[StrategyRobustnessEvidence, ...],
    strategy_ids: tuple[str, ...],
) -> tuple[str, str]:
    preflight = foundation.preflight
    if not preflight.robustness_enabled:
        raise ValueError("Preview decision requires robustness enabled in the preflighted study")
    if len(evidence) != len(strategy_ids):
        raise ValueError("paired robustness evidence must cover every compared strategy")
    by_strategy = {item.strategy_id: item for item in evidence}
    if len(by_strategy) != len(evidence) or set(by_strategy) != set(strategy_ids):
        raise ValueError("paired robustness strategy ids must exactly match compared strategies")

    first = evidence[0].common_samples
    if any(item.common_samples != first for item in evidence[1:]):
        raise ValueError("paired robustness requires one identical common sample-set identity")
    if preflight.robustness_campaign_id != first.campaign_id:
        raise ValueError("robustness campaign id does not match preflighted study")
    if preflight.robustness_sampling_model_sha256 != first.sampling_model_sha256:
        raise ValueError("robustness sampling model hash does not match preflighted study")
    expected_uncertainty_id = robustness_uncertainty_model_id(evidence[0])
    if preflight.identity.uncertainty_model_id != expected_uncertainty_id:
        raise ValueError("OperationalStudyIdentity uncertainty model does not match paired robustness sample model")
    return first.campaign_id, first.sampling_model_sha256


def build_preview_operational_decision(
    foundation: PreviewOptimalOperationsFoundationRun,
    authority: PreviewOptimizedAuthorityReduction,
    robustness: tuple[StrategyRobustnessEvidence, ...],
    policy: PreviewOperationalDecisionPolicy,
) -> PreviewOperationalDecisionResult:
    if authority.selection.preflight_sha256 != foundation.preflight.preflight_sha256:
        raise ValueError("optimized authority evidence does not match foundation preflight")
    if authority.selection.screening_evidence_sha256 != foundation.screening.evidence_sha256:
        raise ValueError("optimized authority evidence does not match foundation screening evidence")
    if authority.recommendation_strategy_id is not None or authority.robustness_available:
        raise ValueError("decision stage requires pre-robustness authority reduction")
    if foundation.preflight.robustness_recommendation_required and not policy.robustness_required:
        raise ValueError("preflight requires robustness for recommendation")

    baselines = tuple(item.strategy for item in foundation.baselines)
    candidate = authority.evaluation
    strategy_ids = tuple(item.strategy_id for item in (*baselines, candidate))
    campaign_id, sampling_hash = _validate_common_robustness(foundation, robustness, strategy_ids)
    evidence_by_strategy = {item.strategy_id: item for item in robustness}

    bound_baselines = tuple(
        bind_operational_robustness(
            item,
            evidence_by_strategy[item.strategy_id],
            violation_probability_limits=policy.violation_probability_limits,
            violation_probability_objectives=policy.violation_probability_objectives,
        )
        for item in baselines
    )
    bound_candidate = bind_operational_robustness(
        candidate,
        evidence_by_strategy[candidate.strategy_id],
        violation_probability_limits=policy.violation_probability_limits,
        violation_probability_objectives=policy.violation_probability_objectives,
    )

    bound_by_strategy = {item.strategy_id: item for item in (*bound_baselines, bound_candidate)}
    selected = bound_by_strategy.get(policy.recommendation_strategy_id)
    if selected is None:
        raise ValueError("final recommendation strategy id is unknown")
    if policy.robustness_required:
        if selected.robustness_evidence is None or not selected.robustness_evidence.complete:
            raise ValueError("final recommendation requires complete robustness realizations")
    if not selected.hard_constraints_passed:
        raise ValueError("final recommendation violates explicit hard constraints")

    study = assemble_optimal_operations_study(
        study_id=foundation.preflight.study_id,
        baselines=bound_baselines,
        candidate=bound_candidate,
        recommendation_strategy_id=policy.recommendation_strategy_id,
        robustness_required_for_recommendation=policy.robustness_required,
    )
    pareto = credible_pareto_strategy_ids(study)
    if policy.recommendation_strategy_id not in pareto:
        raise ValueError("final recommendation is not in the credible Pareto set")

    payload = {
        "preflight_sha256": foundation.preflight.preflight_sha256,
        "screening_evidence_sha256": foundation.screening.evidence_sha256,
        "authority_selection_sha256": authority.selection.selection_sha256,
        "common_campaign_id": campaign_id,
        "common_sampling_model_sha256": sampling_hash,
        "decision_policy": policy.model_dump(mode="json"),
        "study": study.model_dump(mode="json"),
        "credible_pareto_strategy_ids": pareto,
    }
    return PreviewOperationalDecisionResult(
        study=study,
        credible_pareto_strategy_ids=pareto,
        common_campaign_id=campaign_id,
        common_sampling_model_sha256=sampling_hash,
        decision_policy=policy,
        decision_evidence_sha256=_digest(payload),
    )


def write_preview_operational_decision(
    output_root: Path,
    foundation: PreviewOptimalOperationsFoundationRun,
    authority: PreviewOptimizedAuthorityReduction,
    robustness: tuple[StrategyRobustnessEvidence, ...],
    result: PreviewOperationalDecisionResult,
) -> PreviewOperationalDecisionArtifacts:
    if result.study.study_id != foundation.preflight.study_id:
        raise ValueError("decision study id does not match foundation")
    if result.study.recommendation_strategy_id != result.decision_policy.recommendation_strategy_id:
        raise ValueError("persisted recommendation does not match explicit decision policy")
    if result.study.recommendation_strategy_id not in result.credible_pareto_strategy_ids:
        raise ValueError("persisted recommendation must remain in credible Pareto set")

    run_dir = output_root / result.study.study_id / f"decision-{result.decision_evidence_sha256[:16]}"
    run_dir.mkdir(parents=True, exist_ok=True)
    study_path = run_dir / "operational_study.json"
    robustness_path = run_dir / "paired_robustness.json"
    decision_path = run_dir / "operational_decision.json"
    manifest_path = run_dir / "decision_manifest.json"

    study_path.write_text(result.study.model_dump_json(indent=2), encoding="utf-8")
    robustness_path.write_text(
        json.dumps([item.model_dump(mode="json") for item in robustness], indent=2, sort_keys=True),
        encoding="utf-8",
    )
    decision_path.write_text(result.model_dump_json(indent=2), encoding="utf-8")
    manifest = {
        "study_id": result.study.study_id,
        "preflight_sha256": foundation.preflight.preflight_sha256,
        "screening_evidence_sha256": foundation.screening.evidence_sha256,
        "authority_selection_sha256": authority.selection.selection_sha256,
        "common_campaign_id": result.common_campaign_id,
        "common_sampling_model_sha256": result.common_sampling_model_sha256,
        "credible_pareto_strategy_ids": list(result.credible_pareto_strategy_ids),
        "recommendation_strategy_id": result.study.recommendation_strategy_id,
        "robustness_required_for_recommendation": result.study.robustness_required_for_recommendation,
        "decision_evidence_sha256": result.decision_evidence_sha256,
        "semantics": "paired robustness + credible Pareto + explicit final recommendation; no hidden thresholds",
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    return PreviewOperationalDecisionArtifacts(
        run_dir=str(run_dir),
        study_path=str(study_path),
        robustness_path=str(robustness_path),
        decision_path=str(decision_path),
        manifest_path=str(manifest_path),
        decision_evidence_sha256=result.decision_evidence_sha256,
    )
