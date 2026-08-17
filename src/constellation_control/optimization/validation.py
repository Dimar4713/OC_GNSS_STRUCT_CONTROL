from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class ValidationOutcome:
    backend: str
    metrics: dict[str, float]


@dataclass(frozen=True)
class ValidationReplayEvidence:
    candidate_index: int
    design_vector: tuple[float, ...]
    design_objectives: tuple[float, ...]
    ranking_score: float
    backend: str
    validation_metrics: dict[str, float]


def replay_top_k_in_validation(
    candidates: np.ndarray,
    design_objectives: np.ndarray,
    *,
    top_k: int,
    ranking_policy: Callable[[np.ndarray, np.ndarray], float],
    validator: Callable[[np.ndarray], ValidationOutcome],
) -> tuple[ValidationReplayEvidence, ...]:
    """Replay explicitly ranked design candidates in numerical Orekit validation.

    The ranking policy is mandatory: this layer never invents a preferred Pareto
    compromise. Validation is fail-closed and only accepts an authoritative
    `orekit-numerical*` backend identity.
    """

    x = np.asarray(candidates, dtype=float)
    f = np.asarray(design_objectives, dtype=float)
    if x.ndim != 2 or f.ndim != 2 or x.shape[0] != f.shape[0]:
        raise ValueError("candidates and design_objectives must be 2-D with equal row counts")
    if x.shape[0] == 0:
        return ()
    if top_k <= 0:
        raise ValueError("top_k must be positive")
    if not np.all(np.isfinite(x)) or not np.all(np.isfinite(f)):
        raise ValueError("candidate and objective arrays must be finite")

    ranked: list[tuple[float, int]] = []
    for index in range(x.shape[0]):
        score = float(ranking_policy(x[index].copy(), f[index].copy()))
        if not np.isfinite(score):
            raise ValueError(f"ranking policy returned a non-finite score for candidate {index}")
        ranked.append((score, index))
    ranked.sort(key=lambda item: (item[0], item[1]))

    evidence: list[ValidationReplayEvidence] = []
    for score, index in ranked[: min(top_k, len(ranked))]:
        vector = x[index].copy()
        outcome = validator(vector)
        if not outcome.backend.lower().startswith("orekit-numerical"):
            raise RuntimeError(
                f"candidate {index} validation returned non-authoritative backend: {outcome.backend}"
            )
        if not all(np.isfinite(value) for value in outcome.metrics.values()):
            raise RuntimeError(f"candidate {index} validation returned non-finite metrics")
        evidence.append(
            ValidationReplayEvidence(
                candidate_index=index,
                design_vector=tuple(float(value) for value in vector),
                design_objectives=tuple(float(value) for value in f[index]),
                ranking_score=score,
                backend=outcome.backend,
                validation_metrics=dict(sorted(outcome.metrics.items())),
            )
        )
    return tuple(evidence)
