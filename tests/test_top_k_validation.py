import numpy as np
import pytest

from constellation_control.optimization.validation import (
    ValidationOutcome,
    replay_top_k_in_validation,
)


def test_top_k_replay_uses_explicit_policy_and_stable_tie_break() -> None:
    candidates = np.asarray([[10.0, 1.0], [20.0, 2.0], [30.0, 3.0]])
    objectives = np.asarray([[2.0, 1.0], [1.0, 3.0], [1.0, 1.0]])
    visited: list[float] = []

    def policy(vector: np.ndarray, objective: np.ndarray) -> float:
        del vector
        return float(objective[0] + objective[1])

    def validator(vector: np.ndarray) -> ValidationOutcome:
        visited.append(float(vector[0]))
        return ValidationOutcome(
            backend="orekit-numerical-validation",
            metrics={"drift": float(vector[1]) * 1.0e-9},
        )

    evidence = replay_top_k_in_validation(
        candidates,
        objectives,
        top_k=2,
        ranking_policy=policy,
        validator=validator,
    )

    assert visited == [30.0, 10.0]
    assert [item.candidate_index for item in evidence] == [2, 0]
    assert evidence[0].backend == "orekit-numerical-validation"


def test_top_k_replay_rejects_silent_screening_fallback() -> None:
    candidates = np.asarray([[1.0]])
    objectives = np.asarray([[1.0]])

    with pytest.raises(RuntimeError, match="non-authoritative backend"):
        replay_top_k_in_validation(
            candidates,
            objectives,
            top_k=1,
            ranking_policy=lambda vector, objective: float(objective[0]),
            validator=lambda vector: ValidationOutcome(
                backend="synthetic-j2-screening",
                metrics={"drift": 0.0},
            ),
        )
