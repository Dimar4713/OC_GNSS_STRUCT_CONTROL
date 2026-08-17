from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
from scipy.optimize import Bounds, minimize
from scipy.stats import qmc

from constellation_control.domain.models import OptimizationResult


@dataclass(frozen=True)
class DesignWeights:
    drift: float
    periodic: float
    plane: float
    proximity: float
    track: float
    dv_est: float


def weighted_design_cost(metrics: dict[str, float], weights: DesignWeights) -> float:
    return (
        weights.drift * metrics["drift_sq"]
        + weights.periodic * metrics["periodic_sq"]
        + weights.plane * metrics["plane_sq"]
        + weights.proximity * metrics["proximity_penalty"]
        + weights.track * metrics["track_error_sq"]
        + weights.dv_est * metrics["estimated_lifetime_delta_v"]
    )


def latin_hypercube(bounds: tuple[tuple[float, float], ...], samples: int, seed: int) -> np.ndarray:
    lower = np.array([item[0] for item in bounds], dtype=float)
    upper = np.array([item[1] for item in bounds], dtype=float)
    unit = qmc.LatinHypercube(d=len(bounds), seed=seed).random(samples)
    return qmc.scale(unit, lower, upper)


def local_optimize(
    initial: np.ndarray,
    objective: Callable[[np.ndarray], float],
    bounds: tuple[tuple[float, float], ...],
    method: str = "SLSQP",
) -> OptimizationResult:
    if method not in {"SLSQP", "trust-constr"}:
        raise ValueError("method must be SLSQP or trust-constr")
    scipy_bounds = Bounds([item[0] for item in bounds], [item[1] for item in bounds])
    result = minimize(objective, np.asarray(initial, dtype=float), method=method, bounds=scipy_bounds)
    return OptimizationResult(
        success=bool(result.success),
        algorithm=method,
        x=tuple(float(value) for value in result.x),
        objective=float(result.fun),
        message=str(result.message),
    )


def pareto_nsga2(
    evaluator: Callable[[np.ndarray], tuple[float, ...]],
    bounds: tuple[tuple[float, float], ...],
    n_objectives: int,
    seed: int,
    population: int = 80,
    generations: int = 100,
) -> tuple[np.ndarray, np.ndarray]:
    from pymoo.algorithms.moo.nsga2 import NSGA2
    from pymoo.core.problem import ElementwiseProblem
    from pymoo.optimize import minimize as pymoo_minimize

    lower = np.array([item[0] for item in bounds], dtype=float)
    upper = np.array([item[1] for item in bounds], dtype=float)

    class DesignProblem(ElementwiseProblem):
        def __init__(self) -> None:
            super().__init__(n_var=len(bounds), n_obj=n_objectives, xl=lower, xu=upper)

        def _evaluate(self, x: np.ndarray, out: dict[str, np.ndarray], *args: object, **kwargs: object) -> None:
            out["F"] = np.asarray(evaluator(x), dtype=float)

    result = pymoo_minimize(DesignProblem(), NSGA2(pop_size=population), ("n_gen", generations), seed=seed, verbose=False)
    return np.asarray(result.X, dtype=float), np.asarray(result.F, dtype=float)
