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


def run_monte_carlo(
    config: MonteCarloConfig,
    evaluator: Callable[[dict[str, float | int]], dict[str, object]],
) -> MonteCarloResult:
    rng = np.random.default_rng(config.seed)
    names = tuple(sorted(config.perturbation_sigmas))
    samples = []
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

    numeric_keys = sorted(
        key for key in outcomes[0] if all(isinstance(outcome.get(key), (int, float)) for outcome in outcomes)
    ) if outcomes else []
    statistics: dict[str, object] = {}
    for key in numeric_keys:
        values = np.asarray([float(outcome[key]) for outcome in outcomes])
        statistics[key] = {
            "p50": float(np.percentile(values, 50)),
            "p95": float(np.percentile(values, 95)),
            "p99": float(np.percentile(values, 99)),
            "worst": float(np.max(values)),
        }

    violation_names = sorted(
        {name for outcome in outcomes for name in dict(outcome.get("violations", {}))}
    )
    violation_probability = {}
    for name in violation_names:
        count = sum(bool(dict(outcome.get("violations", {})).get(name, False)) for outcome in outcomes)
        violation_probability[name] = count / len(outcomes) if outcomes else 0.0

    return MonteCarloResult(
        samples=tuple(samples),
        outcomes=tuple(outcomes),
        summary={"statistics": statistics, "violation_probability": violation_probability},
    )
