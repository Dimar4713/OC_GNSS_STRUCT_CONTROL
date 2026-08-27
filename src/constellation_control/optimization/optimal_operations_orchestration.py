from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence

from pydantic import BaseModel, ConfigDict, Field, model_validator

from constellation_control.optimization.hybrid_strategy import HybridStrategyValidationResult
from constellation_control.optimization.operational_policy_search import OperationalPolicyCandidate
from constellation_control.optimization.operational_robustness import StrategyRobustnessEvidence
from constellation_control.optimization.operational_robustness_binding import bind_operational_robustness
from constellation_control.optimization.operations import (
    CredibilityState,
    HardConstraintEvidence,
    NamedObjectiveValue,
    OperationalStrategyEvaluation,
    OperationalStrategyKind,
    OperationalStrategyStudy,
    OperationalStudyIdentity,
)


class AuthoritativeOperationalOutcomeEvidence(BaseModel):
    """Accepted operational metrics supplied by an authoritative campaign/evidence layer.

    This model intentionally contains no screening score fields and performs no
    propagation, maneuver sizing, annualization, or uncertainty sampling.
    """

    model_config = ConfigDict(frozen=True)

    campaign_termination_reason: str = Field(min_length=1)
    correction_count: int = Field(ge=0)
    corrections_per_julian_year: float | None = Field(default=None, ge=0.0)
    cumulative_delta_v_m_s: float = Field(ge=0.0)
    delta_v_m_s_per_julian_year: float | None = Field(default=None, ge=0.0)
    cumulative_propellant_used_kg: float = Field(ge=0.0)
    propellant_kg_per_julian_year: float | None = Field(default=None, ge=0.0)
    projected_years_to_reserve: float | None = Field(default=None, ge=0.0)
    minimum_corridor_margin_rad: float | None = None
    minimum_fleet_distance_margin_m: float | None = None
    settling_mean_s: float | None = Field(default=None, ge=0.0)
    coast_mean_s: float | None = Field(default=None, ge=0.0)
    objectives: tuple[NamedObjectiveValue, ...]
    hard_constraints: tuple[HardConstraintEvidence, ...]
    evidence_id: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_evidence(self) -> AuthoritativeOperationalOutcomeEvidence:
        if not self.objectives:
            raise ValueError("authoritative operational outcome requires named objectives")
        if not self.hard_constraints:
            raise ValueError("authoritative operational outcome requires hard constraints")
        return self


def _validation_digest(result: HybridStrategyValidationResult) -> str:
    raw = json.dumps(result.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _merge_hard_constraints(
    outcome_constraints: tuple[HardConstraintEvidence, ...],
    hybrid: HybridStrategyValidationResult,
) -> tuple[HardConstraintEvidence, ...]:
    merged: list[HardConstraintEvidence] = list(outcome_constraints)
    keys: dict[tuple[str, str], HardConstraintEvidence] = {
        (item.name, item.unit): item for item in outcome_constraints
    }
    if len(keys) != len(outcome_constraints):
        raise ValueError("authoritative operational hard-constraint definitions must be unique")

    for record in hybrid.records:
        if record.evidence is None or record.evidence.correction_authority_receipt is None:
            continue
        receipt = record.evidence.correction_authority_receipt
        for item in receipt.hard_constraints:
            normalized = HardConstraintEvidence(
                name=f"hybrid_event.{record.event_id}.{item.name}",
                unit=item.unit,
                margin=item.margin,
                evidence_source=item.evidence_source,
            )
            key = (normalized.name, normalized.unit)
            previous = keys.get(key)
            if previous is not None:
                if previous != normalized:
                    raise ValueError("conflicting duplicate hybrid hard-constraint evidence")
                continue
            keys[key] = normalized
            merged.append(normalized)

    hybrid_gate = HardConstraintEvidence(
        name="hybrid_strategy_authority",
        unit="signed_boolean_margin",
        margin=(
            0.0
            if hybrid.complete
            and hybrid.resulting_credibility_state
            == CredibilityState.AUTHORITATIVELY_VALIDATED_CANDIDATE
            else -1.0
        ),
        evidence_source=hybrid.reason or hybrid.resulting_credibility_state.value,
    )
    key = (hybrid_gate.name, hybrid_gate.unit)
    previous = keys.get(key)
    if previous is not None and previous != hybrid_gate:
        raise ValueError("conflicting hybrid strategy authority evidence")
    if previous is None:
        merged.append(hybrid_gate)
    return tuple(merged)


def _authority_lineage(
    hybrid: HybridStrategyValidationResult,
    identity: OperationalStudyIdentity,
) -> tuple[str | None, str | None]:
    pairs: set[tuple[str, str]] = set()
    for record in hybrid.records:
        if record.evidence is None or record.evidence.correction_authority_receipt is None:
            continue
        receipt = record.evidence.correction_authority_receipt
        if not receipt.authorized:
            continue
        if receipt.replay_backend is None or receipt.transition_force_model_fingerprint is None:
            raise ValueError("authorized hybrid correction receipt requires backend/fingerprint lineage")
        pairs.add((receipt.replay_backend, receipt.transition_force_model_fingerprint))

    if hybrid.resulting_credibility_state == CredibilityState.AUTHORITATIVELY_VALIDATED_CANDIDATE:
        if len(pairs) != 1:
            raise ValueError("validated optimized candidate requires one unambiguous authority lineage")
    elif len(pairs) > 1:
        raise ValueError("hybrid correction receipts contain inconsistent authority lineage")

    if not pairs:
        return None, None
    backend, fingerprint = next(iter(pairs))
    if fingerprint != identity.force_model_fingerprint:
        raise ValueError("optimized candidate authority fingerprint does not match operational study identity")
    return backend, fingerprint


def build_optimized_operational_evaluation(
    *,
    strategy_id: str,
    candidate: OperationalPolicyCandidate,
    hybrid: HybridStrategyValidationResult,
    identity: OperationalStudyIdentity,
    outcome: AuthoritativeOperationalOutcomeEvidence,
    robustness: StrategyRobustnessEvidence | None = None,
    violation_probability_limits: Mapping[str, float] | None = None,
    violation_probability_objectives: Sequence[str] = (),
) -> OperationalStrategyEvaluation:
    """Reduce accepted candidate evidence into the existing operational contract.

    Screening objectives are intentionally ignored. Authority state comes only
    from the hybrid result; final objective values come only from ``outcome``.
    """

    if hybrid.strategy_id != strategy_id:
        raise ValueError("hybrid strategy id does not match optimized operational strategy id")
    if not candidate.screening_only:
        raise ValueError("operational policy candidate must retain screening-only provenance")
    if not candidate.feasible:
        raise ValueError("infeasible screening candidate cannot enter authority orchestration")

    backend, fingerprint = _authority_lineage(hybrid, identity)
    hard_constraints = _merge_hard_constraints(outcome.hard_constraints, hybrid)
    validation_id = _validation_digest(hybrid)

    evaluation = OperationalStrategyEvaluation(
        strategy_id=strategy_id,
        kind=OperationalStrategyKind.OPTIMIZED_CANDIDATE,
        credibility_state=hybrid.resulting_credibility_state,
        identity=identity,
        candidate_id=candidate.candidate_id,
        campaign_termination_reason=outcome.campaign_termination_reason,
        correction_count=outcome.correction_count,
        corrections_per_julian_year=outcome.corrections_per_julian_year,
        cumulative_delta_v_m_s=outcome.cumulative_delta_v_m_s,
        delta_v_m_s_per_julian_year=outcome.delta_v_m_s_per_julian_year,
        cumulative_propellant_used_kg=outcome.cumulative_propellant_used_kg,
        propellant_kg_per_julian_year=outcome.propellant_kg_per_julian_year,
        projected_years_to_reserve=outcome.projected_years_to_reserve,
        minimum_corridor_margin_rad=outcome.minimum_corridor_margin_rad,
        minimum_fleet_distance_margin_m=outcome.minimum_fleet_distance_margin_m,
        settling_mean_s=outcome.settling_mean_s,
        coast_mean_s=outcome.coast_mean_s,
        objectives=outcome.objectives,
        hard_constraints=hard_constraints,
        authority_backend=backend,
        authority_force_model_fingerprint=fingerprint,
        high_fidelity_validation_id=(
            validation_id
            if hybrid.resulting_credibility_state
            == CredibilityState.AUTHORITATIVELY_VALIDATED_CANDIDATE
            else None
        ),
        provenance={
            "operational_candidate_id": candidate.candidate_id,
            "screening_stage": candidate.stage,
            "trigger_fraction": repr(candidate.parameters.trigger_fraction),
            "target_fraction": repr(candidate.parameters.target_fraction),
            "authoritative_outcome_evidence_id": outcome.evidence_id,
            "hybrid_validation_sha256": validation_id,
        },
    )

    if robustness is None:
        return evaluation
    return bind_operational_robustness(
        evaluation,
        robustness,
        violation_probability_limits=violation_probability_limits,
        violation_probability_objectives=violation_probability_objectives,
    )


def assemble_optimal_operations_study(
    *,
    study_id: str,
    baselines: tuple[OperationalStrategyEvaluation, ...],
    candidate: OperationalStrategyEvaluation,
    recommendation_strategy_id: str | None = None,
    robustness_required_for_recommendation: bool = False,
) -> OperationalStrategyStudy:
    """Compare one optimized candidate with the exact three accepted P2 baselines."""

    required = {
        OperationalStrategyKind.NO_CONTROL_BASELINE,
        OperationalStrategyKind.RETURN_TO_CENTER_BASELINE,
        OperationalStrategyKind.BOUNDARY_TO_BOUNDARY_BASELINE,
    }
    if len(baselines) != 3 or {item.kind for item in baselines} != required:
        raise ValueError("optimal operations study requires exactly the three P2 baselines")
    if any(item.credibility_state != CredibilityState.AUTHORITATIVE_BASELINE for item in baselines):
        raise ValueError("optimal operations baselines must be authoritative")
    if candidate.kind != OperationalStrategyKind.OPTIMIZED_CANDIDATE:
        raise ValueError("optimal operations candidate must use optimized-candidate kind")
    return OperationalStrategyStudy(
        study_id=study_id,
        evaluations=(*baselines, candidate),
        recommendation_strategy_id=recommendation_strategy_id,
        robustness_required_for_recommendation=robustness_required_for_recommendation,
    )
