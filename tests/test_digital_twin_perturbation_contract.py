from __future__ import annotations

import pytest
from pydantic import ValidationError

from constellation_control.domain.digital_twin import (
    AppliedPerturbation,
    PerturbationDistribution,
    PerturbationParameter,
    PerturbationRule,
    PerturbationScope,
    ScenarioLineage,
)


def test_supported_parameter_and_unit_are_explicit() -> None:
    rule = PerturbationRule(
        rule_id="a-rule",
        parameter=PerturbationParameter.SEMI_MAJOR_AXIS,
        distribution=PerturbationDistribution.GAUSSIAN,
        scope=PerturbationScope.SATELLITE,
        target_ids=("SAT-1",),
        mean=0.0,
        sigma=25.0,
        unit="m",
    )
    assert rule.parameter is PerturbationParameter.SEMI_MAJOR_AXIS
    assert rule.unit == "m"


def test_unknown_parameter_is_rejected_fail_closed() -> None:
    with pytest.raises(ValidationError):
        PerturbationRule(
            rule_id="bad-parameter",
            parameter="free_form_parameter",
            distribution="gaussian",
            scope="satellite",
            target_ids=("SAT-1",),
            mean=0.0,
            sigma=1.0,
            unit="m",
        )


def test_wrong_unit_is_rejected_fail_closed() -> None:
    with pytest.raises(ValidationError, match="requires unit"):
        PerturbationRule(
            rule_id="bad-unit",
            parameter="inclination",
            distribution="gaussian",
            scope="satellite",
            target_ids=("SAT-1",),
            mean=0.0,
            sigma=0.001,
            unit="deg",
        )


def test_constellation_scope_rejects_target_ids() -> None:
    with pytest.raises(ValidationError, match="must not define target_ids"):
        PerturbationRule(
            rule_id="ambiguous-scope",
            parameter="eccentricity",
            distribution="gaussian",
            scope="constellation",
            target_ids=("SAT-1",),
            mean=0.0,
            sigma=1e-5,
            unit="1",
        )


def test_applied_perturbation_uses_same_parameter_unit_contract() -> None:
    applied = AppliedPerturbation(
        rule_id="epoch-rule",
        satellite_id="SAT-1",
        parameter="epoch_offset",
        sampled_delta=2.5,
        unit="s",
    )
    assert applied.parameter is PerturbationParameter.EPOCH_OFFSET

    with pytest.raises(ValidationError, match="requires unit"):
        AppliedPerturbation(
            rule_id="epoch-rule",
            satellite_id="SAT-1",
            parameter="epoch_offset",
            sampled_delta=2.5,
            unit="ms",
        )


def test_lineage_requires_real_sha256_parent_hash() -> None:
    valid = ScenarioLineage(
        parent_scenario_id="parent",
        parent_config_hash="a" * 64,
        transformation="perturbation",
        random_seed=42,
    )
    assert valid.parent_config_hash == "a" * 64

    with pytest.raises(ValidationError):
        ScenarioLineage(
            parent_scenario_id="parent",
            parent_config_hash="not-a-sha256",
            transformation="perturbation",
            random_seed=42,
        )
