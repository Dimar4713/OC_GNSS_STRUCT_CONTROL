from __future__ import annotations

from enum import StrEnum

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, model_validator


class OperationalStrategyKind(StrEnum):
    NO_CONTROL_BASELINE = "no_control_baseline"
    RETURN_TO_CENTER_BASELINE = "return_to_center_baseline"
    BOUNDARY_TO_BOUNDARY_BASELINE = "boundary_to_boundary_baseline"
    OPTIMIZED_CANDIDATE = "optimized_candidate"


class CredibilityState(StrEnum):
    SCREENING_ONLY = "screening-only"
    AUTHORITATIVE_BASELINE = "authoritative-baseline"
    CANDIDATE_AWAITING_VALIDATION = "candidate-awaiting-validation"
    AUTHORITATIVELY_VALIDATED_CANDIDATE = "authoritatively-validated-candidate"
    REJECTED_BY_AUTHORITY = "rejected-by-authority"


class ObjectiveDirection(StrEnum):
    MINIMIZE = "minimize"
    MAXIMIZE = "maximize"


class OperationalStudyIdentity(BaseModel):
    """Compatibility identity required before operational strategies may be compared."""

    model_config = ConfigDict(frozen=True)

    scenario_id: str
    initial_epoch_iso: str
    seed: int
    force_model_fingerprint: str
    frame: str
    time_scale: str
    integrator_identity: str
    constraints_identity: str
    execution_policy_identity: str
    campaign_horizon_s: float = Field(gt=0.0)
    coast_horizon_s: float = Field(gt=0.0)
    coast_output_step_s: float = Field(gt=0.0)
    authority_times_s: tuple[float, ...]
    maneuver_windows: tuple[bool, ...]
    uncertainty_model_id: str = "deterministic-v1"

    @model_validator(mode="after")
    def validate_grids(self) -> OperationalStudyIdentity:
        if len(self.authority_times_s) < 2 or self.authority_times_s[0] != 0.0:
            raise ValueError("authority_times_s must start at zero and contain at least two samples")
        intervals = np.diff(np.asarray(self.authority_times_s, dtype=float))
        if np.any(~np.isfinite(intervals)) or np.any(intervals <= 0.0):
            raise ValueError("authority_times_s must be finite and strictly increasing")
        if len(self.maneuver_windows) != len(self.authority_times_s) - 1:
            raise ValueError("maneuver_windows must have one entry per authority interval")
        return self


class NamedObjectiveValue(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    unit: str
    direction: ObjectiveDirection
    value: float


class HardConstraintEvidence(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    unit: str
    margin: float
    evidence_source: str

    @property
    def passed(self) -> bool:
        return self.margin >= 0.0


class OperationalStrategyEvaluation(BaseModel):
    """One baseline/candidate evaluation with hard authority separated from soft objectives."""

    model_config = ConfigDict(frozen=True)

    strategy_id: str
    kind: OperationalStrategyKind
    credibility_state: CredibilityState
    identity: OperationalStudyIdentity
    candidate_id: str | None = None
    campaign_termination_reason: str
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
    robustness_available: bool = False
    robustness_reason: str | None = "uncertainty campaign not supplied"
    objectives: tuple[NamedObjectiveValue, ...]
    hard_constraints: tuple[HardConstraintEvidence, ...]
    authority_backend: str | None = None
    authority_force_model_fingerprint: str | None = None
    high_fidelity_validation_id: str | None = None
    provenance: dict[str, str] = {}

    @model_validator(mode="after")
    def validate_credibility(self) -> OperationalStrategyEvaluation:
        if not self.objectives:
            raise ValueError("operational evaluation requires at least one named objective")
        objective_keys = [(item.name, item.unit, item.direction) for item in self.objectives]
        if len(objective_keys) != len(set(objective_keys)):
            raise ValueError("objective definitions must be unique")
        if not self.hard_constraints:
            raise ValueError("operational evaluation requires explicit hard constraints")
        if self.kind == OperationalStrategyKind.OPTIMIZED_CANDIDATE and self.candidate_id is None:
            raise ValueError("optimized candidate requires candidate_id")
        if self.credibility_state == CredibilityState.AUTHORITATIVE_BASELINE:
            if self.kind == OperationalStrategyKind.OPTIMIZED_CANDIDATE:
                raise ValueError("optimized candidate cannot use authoritative-baseline state")
            if self.authority_backend is None or self.authority_force_model_fingerprint is None:
                raise ValueError("authoritative baseline requires backend/fingerprint provenance")
        if self.credibility_state == CredibilityState.AUTHORITATIVELY_VALIDATED_CANDIDATE:
            if self.kind != OperationalStrategyKind.OPTIMIZED_CANDIDATE:
                raise ValueError("validated-candidate state requires optimized candidate kind")
            if self.high_fidelity_validation_id is None:
                raise ValueError("validated candidate requires high_fidelity_validation_id")
            if self.authority_backend is None or self.authority_force_model_fingerprint is None:
                raise ValueError("validated candidate requires authority backend/fingerprint")
            if any(not constraint.passed for constraint in self.hard_constraints):
                raise ValueError("validated candidate cannot violate hard constraints")
        return self

    @property
    def hard_constraints_passed(self) -> bool:
        return all(item.passed for item in self.hard_constraints)

    @property
    def operationally_credible(self) -> bool:
        if not self.hard_constraints_passed:
            return False
        if self.credibility_state == CredibilityState.AUTHORITATIVE_BASELINE:
            return True
        return self.credibility_state == CredibilityState.AUTHORITATIVELY_VALIDATED_CANDIDATE


class OperationalStrategyStudy(BaseModel):
    model_config = ConfigDict(frozen=True)

    study_id: str
    evaluations: tuple[OperationalStrategyEvaluation, ...]
    recommendation_strategy_id: str | None = None

    @model_validator(mode="after")
    def validate_study(self) -> OperationalStrategyStudy:
        if not self.evaluations:
            raise ValueError("operational study requires evaluations")
        ids = [item.strategy_id for item in self.evaluations]
        if len(ids) != len(set(ids)):
            raise ValueError("strategy_id values must be unique")
        identity = self.evaluations[0].identity
        if any(item.identity != identity for item in self.evaluations[1:]):
            raise ValueError("operational strategies have incompatible physical/control identity")
        if self.recommendation_strategy_id is not None:
            required = {
                OperationalStrategyKind.NO_CONTROL_BASELINE,
                OperationalStrategyKind.RETURN_TO_CENTER_BASELINE,
                OperationalStrategyKind.BOUNDARY_TO_BOUNDARY_BASELINE,
            }
            kinds = {item.kind for item in self.evaluations}
            if not required.issubset(kinds):
                raise ValueError("final recommendation requires all three P2 operational baselines")
            selected = next(
                (item for item in self.evaluations if item.strategy_id == self.recommendation_strategy_id),
                None,
            )
            if selected is None:
                raise ValueError("recommendation_strategy_id is unknown")
            if not selected.operationally_credible:
                raise ValueError("final recommendation must be operationally credible")
            if selected.strategy_id not in credible_pareto_strategy_ids(self):
                raise ValueError("final recommendation must belong to the credible Pareto set")
        return self


def _objective_signature(evaluation: OperationalStrategyEvaluation) -> tuple[tuple[str, str, ObjectiveDirection], ...]:
    return tuple((item.name, item.unit, item.direction) for item in evaluation.objectives)


def credible_pareto_strategy_ids(study: OperationalStrategyStudy) -> tuple[str, ...]:
    """Return nondominated credible strategies; hard-constraint failures are excluded, not weighted."""

    credible = [item for item in study.evaluations if item.operationally_credible]
    if not credible:
        return ()
    signature = _objective_signature(credible[0])
    if any(_objective_signature(item) != signature for item in credible[1:]):
        raise ValueError("credible strategies must use identical named objective definitions")
    values = np.asarray(
        [
            [
                objective.value
                if objective.direction == ObjectiveDirection.MINIMIZE
                else -objective.value
                for objective in item.objectives
            ]
            for item in credible
        ],
        dtype=float,
    )
    if np.any(~np.isfinite(values)):
        raise ValueError("objective values must be finite")
    keep = np.ones(len(credible), dtype=bool)
    for index in range(len(credible)):
        dominated = np.any(
            np.all(values <= values[index], axis=1)
            & np.any(values < values[index], axis=1)
        )
        keep[index] = not dominated
    return tuple(item.strategy_id for item, retained in zip(credible, keep, strict=True) if retained)
