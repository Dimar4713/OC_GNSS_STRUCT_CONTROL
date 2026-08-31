from __future__ import annotations

import pytest
from pydantic import ValidationError

from constellation_control.domain.digital_twin import AppliedPerturbation, PerturbationRule


def _gaussian_rule(**overrides: object) -> PerturbationRule:
    payload: dict[str, object] = {
        "rule_id": "rule-a",
        "parameter": "a_m",
        "distribution": "gaussian",
        "scope": "constellation",
        "target_ids": (),
        "mean": 0.0,
        "sigma": 10.0,
        "unit": "m",
    }
    payload.update(overrides)
    return PerturbationRule.model_validate(payload)


def test_perturbation_parameter_is_typed_and_serializes_compatibly() -> None:
    rule = _gaussian_rule()

    assert rule.parameter.value == "a_m"
    assert rule.model_dump(mode="json")["parameter"] == "a_m"


def test_unknown_perturbation_parameter_fails_in_domain_contract() -> None:
    with pytest.raises(ValidationError):
        _gaussian_rule(parameter="not-a-canonical-orbit-parameter")


def test_parameter_unit_mismatch_fails_in_domain_contract() -> None:
    with pytest.raises(ValidationError, match="requires unit m"):
        _gaussian_rule(unit="km")


def test_constellation_scope_rejects_target_ids() -> None:
    with pytest.raises(ValidationError, match="must not define target_ids"):
        _gaussian_rule(target_ids=("SAT-1",))


def test_non_constellation_scope_requires_unique_targets() -> None:
    with pytest.raises(ValidationError, match="target_ids must be unique"):
        _gaussian_rule(scope="satellite", target_ids=("SAT-1", "SAT-1"))


def test_applied_perturbation_rejects_wrong_unit() -> None:
    with pytest.raises(ValidationError, match="requires unit rad"):
        AppliedPerturbation(
            rule_id="rule-i",
            satellite_id="SAT-1",
            parameter="i_rad",
            sampled_delta=1e-4,
            unit="deg",
        )
