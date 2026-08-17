from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

import numpy as np

from constellation_control.domain.models import MonteCarloConfig


@dataclass(frozen=True)
class MonteCarloResult:
    samples: tuple[dict[str, float | int], ...]
    outcomes: tuple[dict[str, object], ...]
    summary: dict[str, object]


def _as_numeric(value: object, key: str) -> float:
    if not isinstance(value, (int, float)):
        raise TypeError(f"Monte Carlo outcome {key!r} must be numeric")
    return float(value)


def _as_violations(value: object) -> dict[str, bool]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise TypeError("Monte Carlo outcome 'violations' must be a mapping")
    violations: dict[str, bool] = {}
    for name, violated in value.items():
        if not isinstance(name, str) or not isinstance(violated, bool):
            raise TypeError("violation mapping must contain str -> bool entries")
        violations[name] = violated
    return violations


def run_monte_carlo(
    config: MonteCarloConfig,
    evaluator: Callable[[dict[str, float | int]], dict[str, object]],
) -> MonteCarloResult:
    rng = np.random.default_rng(config.seed)
    names = tuple(sorted(config.perturbation_sigmas))
    samples: list[dict[str, float | int]] = []
    for index in range(config.samples):
        sample: dict[str, float | int] = {
            "realization": index,
            "realization_seed": int(rng.integers(0, 2**31 - 1)),
        }
        for name in names:
            sample[name] = float(rng.normal(0.0, config.perturbation_sigmas[name]))
        samples.append(sample)

    if config.workers == 1:
        outcomes = [evaluator(sample) for sample in samples]
    else:
        with ThreadPoolExecutor(max_workers=config.workers) as pool:
            outcomes = list(pool.map(evaluator, samples))

    numeric_keys = (
        sorted(
            key
            for key in outcomes[0]
            if key != "violations"
            and all(isinstance(outcome.get(key), (int, float)) for outcome in outcomes)
        )
        if outcomes
        else []
    )
    statistics: dict[str, object] = {}
    for key in numeric_keys:
        values = np.asarray([_as_numeric(outcome[key], key) for outcome in outcomes])
        statistics[key] = {
            "p50": float(np.percentile(values, 50)),
            "p95": float(np.percentile(values, 95)),
            "p99": float(np.percentile(values, 99)),
            "worst": float(np.max(values)),
        }

    violation_maps = [_as_violations(outcome.get("violations")) for outcome in outcomes]
    violation_names = sorted({name for violations in violation_maps for name in violations})
    violation_probability: dict[str, float] = {}
    for name in violation_names:
        count = sum(violations.get(name, False) for violations in violation_maps)
        violation_probability[name] = count / len(outcomes) if outcomes else 0.0

    return MonteCarloResult(
        samples=tuple(samples),
        outcomes=tuple(outcomes),
        summary={"statistics": statistics, "violation_probability": violation_probability},
    )
