from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, model_validator

from constellation_control.optimization.design import latin_hypercube, local_optimize, pareto_nsga2
from constellation_control.optimization.validation import (
    ValidationOutcome,
    ValidationReplayEvidence,
    replay_top_k_in_validation,
)


class RecommendationPolicyConfig(BaseModel):
    model_config = ConfigDict(frozen=True)
    version: str = "weighted-normalized-v1"
    weights: tuple[float, ...]

    @model_validator(mode="after")
    def validate_weights(self) -> RecommendationPolicyConfig:
        if self.version != "weighted-normalized-v1":
            raise ValueError("unsupported recommendation policy version")
        if not self.weights or any(weight < 0.0 for weight in self.weights):
            raise ValueError("recommendation weights must be non-negative and non-empty")
        if sum(self.weights) <= 0.0:
            raise ValueError("at least one recommendation weight must be positive")
        return self


class DesignPipelineConfig(BaseModel):
    model_config = ConfigDict(frozen=True)
    bounds: tuple[tuple[float, float], ...]
    lhs_samples: int = Field(gt=0)
    grid_levels: int = Field(default=0, ge=0)
    local_seeds: int = Field(default=3, gt=0)
    local_method: str = "SLSQP"
    nsga_population: int = Field(default=40, gt=1)
    nsga_generations: int = Field(default=40, gt=0)
    top_k: int = Field(default=3, gt=0)
    seed: int
    recommendation: RecommendationPolicyConfig

    @model_validator(mode="after")
    def validate_pipeline(self) -> DesignPipelineConfig:
        if len(self.bounds) == 0 or len(self.bounds) % 6 != 0:
            raise ValueError("design bounds must contain six variables per additional spacecraft")
        for lower, upper in self.bounds:
            if not np.isfinite(lower) or not np.isfinite(upper) or upper <= lower:
                raise ValueError("every design bound must be finite with upper > lower")
        if self.grid_levels == 1:
            raise ValueError("grid_levels must be 0 or >= 2")
        if self.local_method not in {"SLSQP", "trust-constr"}:
            raise ValueError("local_method must be SLSQP or trust-constr")
        return self


@dataclass(frozen=True)
class CandidateEvaluation:
    objectives: tuple[float, ...]
    constraint_margins: tuple[float, ...]
    metrics: dict[str, float]

    @property
    def feasible(self) -> bool:
        return all(margin >= 0.0 for margin in self.constraint_margins)


@dataclass(frozen=True)
class CandidateRecord:
    candidate_id: str
    stage: str
    vector: tuple[float, ...]
    objectives: tuple[float, ...]
    constraint_margins: tuple[float, ...]
    metrics: dict[str, float]
    feasible: bool
    parent_candidate_id: str | None = None


@dataclass(frozen=True)
class DesignPipelineResult:
    policy_version: str
    records: tuple[CandidateRecord, ...]
    pareto_candidate_ids: tuple[str, ...]
    recommendation_candidate_id: str
    validation: tuple[ValidationReplayEvidence, ...]


def _candidate_id(stage: str, vector: np.ndarray, parent: str | None = None) -> str:
    payload = {
        "stage": stage,
        "vector": [float(value) for value in vector],
        "parent": parent,
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def grid_candidates(bounds: tuple[tuple[float, float], ...], levels: int) -> np.ndarray:
    if levels == 0:
        return np.empty((0, len(bounds)), dtype=float)
    if levels < 2:
        raise ValueError("levels must be 0 or >= 2")
    count = levels ** len(bounds)
    if count > 100_000:
        raise ValueError("grid would exceed 100000 candidates")
    axes = [np.linspace(lower, upper, levels, dtype=float) for lower, upper in bounds]
    mesh = np.meshgrid(*axes, indexing="ij")
    return np.stack([axis.reshape(-1) for axis in mesh], axis=1)


def nondominated_mask(objectives: np.ndarray) -> np.ndarray:
    values = np.asarray(objectives, dtype=float)
    if values.ndim != 2:
        raise ValueError("objectives must be a 2-D array")
    mask = np.ones(values.shape[0], dtype=bool)
    for index in range(values.shape[0]):
        if not mask[index]:
            continue
        dominated_by_any = np.any(
            np.all(values <= values[index], axis=1) & np.any(values < values[index], axis=1)
        )
        mask[index] = not dominated_by_any
    return mask


def normalized_weighted_scores(objectives: np.ndarray, weights: tuple[float, ...]) -> np.ndarray:
    values = np.asarray(objectives, dtype=float)
    vector = np.asarray(weights, dtype=float)
    if values.ndim != 2 or values.shape[1] != vector.size:
        raise ValueError("recommendation weights must match objective count")
    if not np.all(np.isfinite(values)):
        raise ValueError("objectives must be finite")
    lower = values.min(axis=0)
    span = values.max(axis=0) - lower
    normalized = np.divide(values - lower, span, out=np.zeros_like(values), where=span > 0.0)
    return normalized @ (vector / vector.sum())


def _record(
    stage: str,
    vector: np.ndarray,
    evaluation: CandidateEvaluation,
    parent: str | None = None,
) -> CandidateRecord:
    return CandidateRecord(
        candidate_id=_candidate_id(stage, vector, parent),
        stage=stage,
        vector=tuple(float(value) for value in vector),
        objectives=tuple(float(value) for value in evaluation.objectives),
        constraint_margins=tuple(float(value) for value in evaluation.constraint_margins),
        metrics=dict(sorted(evaluation.metrics.items())),
        feasible=evaluation.feasible,
        parent_candidate_id=parent,
    )


def run_design_pipeline(
    config: DesignPipelineConfig,
    *,
    evaluator: Callable[[np.ndarray], CandidateEvaluation],
    validator: Callable[[np.ndarray], ValidationOutcome],
) -> DesignPipelineResult:
    """Execute deterministic constrained design search and authoritative top-K replay."""

    cache: dict[tuple[float, ...], CandidateEvaluation] = {}

    def evaluate(vector: np.ndarray) -> CandidateEvaluation:
        key = tuple(float(value) for value in np.asarray(vector, dtype=float))
        if key not in cache:
            outcome = evaluator(np.asarray(vector, dtype=float))
            if not outcome.objectives or not outcome.constraint_margins:
                raise ValueError("candidate evaluator must return objectives and hard-constraint margins")
            if not all(np.isfinite(value) for value in outcome.objectives + outcome.constraint_margins):
                raise ValueError("candidate evaluator returned non-finite values")
            cache[key] = outcome
        return cache[key]

    lhs = latin_hypercube(config.bounds, config.lhs_samples, config.seed)
    grid = grid_candidates(config.bounds, config.grid_levels)
    initial = np.vstack((lhs, grid)) if grid.size else lhs
    initial = np.unique(initial, axis=0)

    records: list[CandidateRecord] = []
    initial_records: list[CandidateRecord] = []
    for vector in initial:
        record = _record("screening", vector, evaluate(vector))
        records.append(record)
        initial_records.append(record)

    feasible_initial = [record for record in initial_records if record.feasible]
    if not feasible_initial:
        raise RuntimeError("no feasible screening candidates survived hard constraints")

    objective_count = len(feasible_initial[0].objectives)
    if len(config.recommendation.weights) != objective_count:
        raise ValueError("recommendation policy objective count mismatch")
    initial_objectives = np.asarray([record.objectives for record in feasible_initial], dtype=float)
    seed_scores = normalized_weighted_scores(initial_objectives, config.recommendation.weights)
    seed_order = sorted(
        range(len(feasible_initial)),
        key=lambda index: (float(seed_scores[index]), feasible_initial[index].candidate_id),
    )

    ideal = initial_objectives.min(axis=0)
    span = initial_objectives.max(axis=0) - ideal
    policy_weights = np.asarray(config.recommendation.weights, dtype=float)
    policy_weights = policy_weights / policy_weights.sum()

    def scalar_objective(vector: np.ndarray) -> float:
        objectives = np.asarray(evaluate(vector).objectives, dtype=float)
        normalized = np.divide(objectives - ideal, span, out=np.zeros_like(objectives), where=span > 0.0)
        return float(normalized @ policy_weights)

    margin_count = len(feasible_initial[0].constraint_margins)

    def constraint_at(index: int) -> Callable[[np.ndarray], float]:
        def margin(vector: np.ndarray) -> float:
            return float(evaluate(vector).constraint_margins[index])

        return margin

    hard_constraints = tuple(constraint_at(index) for index in range(margin_count))

    for seed_index in seed_order[: min(config.local_seeds, len(seed_order))]:
        parent = feasible_initial[seed_index]
        result = local_optimize(
            np.asarray(parent.vector, dtype=float),
            scalar_objective,
            config.bounds,
            method=config.local_method,
            constraints=hard_constraints,
        )
        vector = np.asarray(result.x, dtype=float)
        records.append(_record("local", vector, evaluate(vector), parent.candidate_id))

    def nsga_objectives(vector: np.ndarray) -> tuple[float, ...]:
        return evaluate(vector).objectives

    def nsga_margins(vector: np.ndarray) -> tuple[float, ...]:
        return evaluate(vector).constraint_margins

    nsga_x, _ = pareto_nsga2(
        nsga_objectives,
        config.bounds,
        objective_count,
        config.seed,
        population=config.nsga_population,
        generations=config.nsga_generations,
        constraint_evaluator=nsga_margins,
        n_constraints=margin_count,
    )
    if nsga_x.ndim == 1:
        nsga_x = nsga_x.reshape(1, -1)
    for vector in nsga_x:
        records.append(_record("nsga2", vector, evaluate(vector)))

    unique_final: dict[tuple[float, ...], CandidateRecord] = {}
    for record in records:
        if record.stage in {"local", "nsga2"} and record.feasible:
            unique_final.setdefault(record.vector, record)
    feasible_final = list(unique_final.values())
    if not feasible_final:
        raise RuntimeError("local/NSGA-II search produced no feasible candidates")
    final_objectives = np.asarray([record.objectives for record in feasible_final], dtype=float)
    pareto_mask = nondominated_mask(final_objectives)
    pareto_records = [record for record, keep in zip(feasible_final, pareto_mask, strict=True) if keep]
    pareto_objectives = np.asarray([record.objectives for record in pareto_records], dtype=float)
    scores = normalized_weighted_scores(pareto_objectives, config.recommendation.weights)
    ranked = sorted(
        range(len(pareto_records)),
        key=lambda index: (float(scores[index]), pareto_records[index].candidate_id),
    )
    ranked_records = [pareto_records[index] for index in ranked]
    ranked_x = np.asarray([record.vector for record in ranked_records], dtype=float)
    ranked_f = np.asarray([record.objectives for record in ranked_records], dtype=float)

    score_by_vector = {
        tuple(record.vector): float(scores[index])
        for index, record in enumerate(pareto_records)
    }

    def replay_policy(vector: np.ndarray, objectives: np.ndarray) -> float:
        del objectives
        return score_by_vector[tuple(float(value) for value in vector)]

    validation = replay_top_k_in_validation(
        ranked_x,
        ranked_f,
        top_k=config.top_k,
        ranking_policy=replay_policy,
        validator=validator,
    )
    if not validation:
        raise RuntimeError("top-K validation produced no authoritative evidence")

    return DesignPipelineResult(
        policy_version=config.recommendation.version,
        records=tuple(records),
        pareto_candidate_ids=tuple(record.candidate_id for record in ranked_records),
        recommendation_candidate_id=ranked_records[0].candidate_id,
        validation=validation,
    )
