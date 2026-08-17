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
    constraints: tuple[Callable[[np.ndarray], float], ...] = (),
) -> OptimizationResult:
    """Run bounded local optimisation with optional hard inequality margins.

    Every constraint callable returns a margin that must remain >= 0.  This keeps
    the application layer explicit about safety constraints instead of hiding
    them in a weighted objective penalty.
    """

    if method not in {"SLSQP", "trust-constr"}:
        raise ValueError("method must be SLSQP or trust-constr")
    scipy_bounds = Bounds([item[0] for item in bounds], [item[1] for item in bounds])
    scipy_constraints = tuple({"type": "ineq", "fun": constraint} for constraint in constraints)
    result = minimize(
        objective,
        np.asarray(initial, dtype=float),
        method=method,
        bounds=scipy_bounds,
        constraints=scipy_constraints,
    )
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
    constraint_evaluator: Callable[[np.ndarray], tuple[float, ...]] | None = None,
    n_constraints: int = 0,
) -> tuple[np.ndarray, np.ndarray]:
    """Run NSGA-II; constraint margins are >= 0 and converted to pymoo G <= 0."""

    from pymoo.algorithms.moo.nsga2 import NSGA2
    from pymoo.core.problem import ElementwiseProblem
    from pymoo.optimize import minimize as pymoo_minimize

    if (constraint_evaluator is None) != (n_constraints == 0):
        raise ValueError("constraint_evaluator and n_constraints must be provided together")

    lower = np.array([item[0] for item in bounds], dtype=float)
    upper = np.array([item[1] for item in bounds], dtype=float)

    class DesignProblem(ElementwiseProblem):
        def __init__(self) -> None:
            super().__init__(
                n_var=len(bounds),
                n_obj=n_objectives,
                n_ieq_constr=n_constraints,
                xl=lower,
                xu=upper,
            )

        def _evaluate(self, x: np.ndarray, out: dict[str, np.ndarray], *args: object, **kwargs: object) -> None:
            out["F"] = np.asarray(evaluator(x), dtype=float)
            if constraint_evaluator is not None:
                margins = np.asarray(constraint_evaluator(x), dtype=float)
                if margins.shape != (n_constraints,):
                    raise ValueError("constraint evaluator returned unexpected number of margins")
                out["G"] = -margins

    result = pymoo_minimize(
        DesignProblem(),
        NSGA2(pop_size=population),
        ("n_gen", generations),
        seed=seed,
        verbose=False,
    )
    return np.asarray(result.X, dtype=float), np.asarray(result.F, dtype=float)
