from __future__ import annotations

import pytest
from pydantic import ValidationError

from constellation_control.optimization.operational_policy_search import (
    OperationalPolicyEvaluation,
    OperationalPolicyParameters,
    OperationalPolicySearchConfig,
    run_operational_policy_screening_search,
)


def _config() -> OperationalPolicySearchConfig:
    return OperationalPolicySearchConfig(
        trigger_fraction_bounds=(0.2, 1.0),
        target_fraction_bounds=(-0.5, 1.0),
        lhs_samples=8,
        local_seeds=2,
        nsga_population=8,
        nsga_generations=3,
        seed=4713,
    )


def _evaluate(parameters: OperationalPolicyParameters) -> OperationalPolicyEvaluation:
    return OperationalPolicyEvaluation(
        objectives=(
            parameters.trigger_fraction,
            abs(parameters.target_fraction - 0.25),
        ),
        hard_margins=(
            1.0 - parameters.trigger_fraction,
            parameters.trigger_fraction - 0.1,
        ),
        metrics={"target_fraction": parameters.target_fraction},
    )


def test_rtc_and_boundary_to_boundary_guidance_convention() -> None:
    rtc = OperationalPolicyParameters(trigger_fraction=1.0, target_fraction=0.0)
    assert rtc.guidance_target_delta_u_rad(+1, 0.4) == pytest.approx(0.0)

    b2b = OperationalPolicyParameters(trigger_fraction=1.0, target_fraction=1.0)
    assert b2b.guidance_target_delta_u_rad(+1, 0.4) == pytest.approx(-0.4)
    assert b2b.guidance_target_delta_u_rad(-1, 0.4) == pytest.approx(+0.4)


def test_search_is_deterministic_and_all_candidates_remain_screening_only() -> None:
    first = run_operational_policy_screening_search(_config(), _evaluate)
    second = run_operational_policy_screening_search(_config(), _evaluate)

    assert first == second
    assert first.pareto_candidate_ids
    assert all(candidate.screening_only for candidate in first.candidates)
    assert all(candidate.feasible for candidate in first.candidates if candidate.candidate_id in first.pareto_candidate_ids)


def test_search_config_contains_only_policy_variables_not_physical_safety_constraints() -> None:
    fields = set(OperationalPolicySearchConfig.model_fields)
    assert "trigger_fraction_bounds" in fields
    assert "target_fraction_bounds" in fields
    assert "phase_corridor_rad" not in fields
    assert "min_pair_distance_m" not in fields
    assert "propellant_reserve_fraction" not in fields
    assert "force_model" not in fields


def test_bounds_fail_closed() -> None:
    with pytest.raises(ValidationError, match="trigger_fraction"):
        OperationalPolicySearchConfig(
            trigger_fraction_bounds=(0.0, 1.0),
            target_fraction_bounds=(0.0, 1.0),
            lhs_samples=4,
            nsga_population=4,
            nsga_generations=2,
            seed=1,
        )
    with pytest.raises(ValidationError, match="target_fraction"):
        OperationalPolicySearchConfig(
            trigger_fraction_bounds=(0.2, 1.0),
            target_fraction_bounds=(-1.1, 1.0),
            lhs_samples=4,
            nsga_population=4,
            nsga_generations=2,
            seed=1,
        )


def test_nonfinite_or_dimensionless_evaluator_contract_fails_closed() -> None:
    def invalid(_: OperationalPolicyParameters) -> OperationalPolicyEvaluation:
        return OperationalPolicyEvaluation(
            objectives=(float("nan"),),
            hard_margins=(1.0,),
            metrics={},
        )

    with pytest.raises(ValueError, match="non-finite"):
        run_operational_policy_screening_search(_config(), invalid)
