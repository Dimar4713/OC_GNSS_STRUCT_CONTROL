from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, model_validator

from constellation_control.optimization.design import latin_hypercube, local_optimize, pareto_nsga2


class OperationalPolicySearchConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    trigger_fraction_bounds: tuple[float, float]
    target_fraction_bounds: tuple[float, float]
    lhs_samples: int = Field(gt=0)
    local_seeds: int = Field(default=3, gt=0)
    local_method: str = "SLSQP"
    nsga_population: int = Field(default=40, gt=1)
    nsga_generations: int = Field(default=40, gt=0)
    seed: int

    @model_validator(mode="after")
    def validate_bounds(self) -> OperationalPolicySearchConfig:
        trigger_low, trigger_high = self.trigger_fraction_bounds
        target_low, target_high = self.target_fraction_bounds
        if not (0.0 < trigger_low < trigger_high <= 1.0):
            raise ValueError("trigger_fraction bounds must satisfy 0 < low < high <= 1")
        if not (-1.0 <= target_low < target_high <= 1.0):
            raise ValueError("target_fraction bounds must satisfy -1 <= low < high <= 1")
        if self.local_method not in {"SLSQP", "trust-constr"}:
            raise ValueError("local_method must be SLSQP or trust-constr")
        return self

    @property
    def bounds(self) -> tuple[tuple[float, float], ...]:
        return (self.trigger_fraction_bounds, self.target_fraction_bounds)


@dataclass(frozen=True)
class OperationalPolicyParameters:
    trigger_fraction: float
    target_fraction: float

    def guidance_target_delta_u_rad(self, crossed_boundary_sign: int, corridor_half_width_rad: float) -> float:
        if crossed_boundary_sign not in (-1, 1):
            raise ValueError("crossed_boundary_sign must be -1 or +1")
        if not np.isfinite(corridor_half_width_rad) or corridor_half_width_rad <= 0.0:
            raise ValueError("corridor_half_width_rad must be positive and finite")
        return -float(crossed_boundary_sign) * self.target_fraction * corridor_half_width_rad


@dataclass(frozen=True)
class OperationalPolicyEvaluation:
    objectives: tuple[float, ...]
    hard_margins: tuple[float, ...]
    metrics: dict[str, float]

    @property
    def feasible(self) -> bool:
        return all(margin >= 0.0 for margin in self.hard_margins)


@dataclass(frozen=True)
class OperationalPolicyCandidate:
    candidate_id: str
    stage: str
    parameters: OperationalPolicyParameters
    objectives: tuple[float, ...]
    hard_margins: tuple[float, ...]
    metrics: dict[str, float]
    feasible: bool
    screening_only: bool = True


@dataclass(frozen=True)
class OperationalPolicySearchResult:
    candidates: tuple[OperationalPolicyCandidate, ...]
    pareto_candidate_ids: tuple[str, ...]


def _candidate_id(stage: str, vector: np.ndarray) -> str:
    payload = {"stage": stage, "vector": [float(value) for value in vector]}
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _parameters(vector: np.ndarray) -> OperationalPolicyParameters:
    values = np.asarray(vector, dtype=float)
    if values.shape != (2,) or np.any(~np.isfinite(values)):
        raise ValueError("operational policy vector must contain two finite values")
    return OperationalPolicyParameters(
        trigger_fraction=float(values[0]),
        target_fraction=float(values[1]),
    )


def _record(stage: str, vector: np.ndarray, evaluation: OperationalPolicyEvaluation) -> OperationalPolicyCandidate:
    return OperationalPolicyCandidate(
        candidate_id=_candidate_id(stage, vector),
        stage=stage,
        parameters=_parameters(vector),
        objectives=tuple(float(value) for value in evaluation.objectives),
        hard_margins=tuple(float(value) for value in evaluation.hard_margins),
        metrics=dict(sorted(evaluation.metrics.items())),
        feasible=evaluation.feasible,
    )


def _nondominated_ids(records: list[OperationalPolicyCandidate]) -> tuple[str, ...]:
    feasible = [record for record in records if record.feasible]
    if not feasible:
        return ()
    values = np.asarray([record.objectives for record in feasible], dtype=float)
    keep = np.ones(len(feasible), dtype=bool)
    for index in range(len(feasible)):
        dominated = np.any(np.all(values <= values[index], axis=1) & np.any(values < values[index], axis=1))
        keep[index] = not dominated
    return tuple(record.candidate_id for record, retained in zip(feasible, keep, strict=True) if retained)


def run_operational_policy_screening_search(
    config: OperationalPolicySearchConfig,
    evaluator: Callable[[OperationalPolicyParameters], OperationalPolicyEvaluation],
) -> OperationalPolicySearchResult:
    """Generate screening-only operational policy candidates.

    This search never confers operational credibility. Physical safety constraints
    remain inside evaluator-provided signed margins and are not optimizer variables.
    """

    cache: dict[tuple[float, float], OperationalPolicyEvaluation] = {}

    def evaluate_vector(vector: np.ndarray) -> OperationalPolicyEvaluation:
        parameters = _parameters(vector)
        key = (parameters.trigger_fraction, parameters.target_fraction)
        if key not in cache:
            outcome = evaluator(parameters)
            if not outcome.objectives or not outcome.hard_margins:
                raise ValueError("operational policy evaluator requires objectives and hard margins")
            values = outcome.objectives + outcome.hard_margins + tuple(outcome.metrics.values())
            if any(not np.isfinite(value) for value in values):
                raise ValueError("operational policy evaluator returned non-finite evidence")
            cache[key] = outcome
        return cache[key]

    lhs = latin_hypercube(config.bounds, config.lhs_samples, config.seed)
    records = [_record("screening", vector, evaluate_vector(vector)) for vector in lhs]
    feasible = [record for record in records if record.feasible]
    if not feasible:
        raise RuntimeError("no feasible operational policy screening candidates")

    objective_count = len(feasible[0].objectives)
    margin_count = len(feasible[0].hard_margins)
    if any(len(item.objectives) != objective_count or len(item.hard_margins) != margin_count for item in feasible):
        raise ValueError("operational policy evaluator dimensions must be stable")

    seed_order = sorted(feasible, key=lambda item: (sum(item.objectives), item.candidate_id))

    def scalar_objective(vector: np.ndarray) -> float:
        return float(sum(evaluate_vector(vector).objectives))

    def constraint_at(index: int) -> Callable[[np.ndarray], float]:
        return lambda vector: float(evaluate_vector(vector).hard_margins[index])

    constraints = tuple(constraint_at(index) for index in range(margin_count))
    for seed_record in seed_order[: min(config.local_seeds, len(seed_order))]:
        initial = np.asarray(
            [seed_record.parameters.trigger_fraction, seed_record.parameters.target_fraction],
            dtype=float,
        )
        result = local_optimize(
            initial,
            scalar_objective,
            config.bounds,
            method=config.local_method,
            constraints=constraints,
        )
        vector = np.asarray(result.x, dtype=float)
        records.append(_record("local", vector, evaluate_vector(vector)))

    def nsga_objectives(vector: np.ndarray) -> tuple[float, ...]:
        return evaluate_vector(vector).objectives

    def nsga_margins(vector: np.ndarray) -> tuple[float, ...]:
        return evaluate_vector(vector).hard_margins

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
        records.append(_record("nsga2", vector, evaluate_vector(vector)))

    return OperationalPolicySearchResult(
        candidates=tuple(records),
        pareto_candidate_ids=_nondominated_ids(records),
    )
