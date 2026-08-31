from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from constellation_control.application.run import load_scenario
from constellation_control.domain.digital_twin import (
    DigitalTwinConfig,
    PerturbationDistribution,
    PerturbationRule,
    PerturbationScope,
    SpacecraftGroup,
    SpacecraftOperationalState,
)
from constellation_control.domain.models import ScenarioConfig


ROOT = Path(__file__).resolve().parents[1]


def test_legacy_scenario_hash_is_unchanged_by_absent_digital_twin() -> None:
    scenario = load_scenario(ROOT / "scenarios" / "mvp_45deg.yaml")
    assert scenario.digital_twin is None

    payload = scenario.model_dump(mode="json")
    payload.pop("digital_twin", None)
    if not scenario.navigation_sites:
        payload.pop("navigation_sites", None)
    expected = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()

    assert scenario.config_hash() == expected


def test_operational_state_resolves_current_mass() -> None:
    state = SpacecraftOperationalState(
        satellite_id="SAT-1",
        dry_mass_kg=850.0,
        current_propellant_mass_kg=75.0,
        propellant_capacity_kg=120.0,
    )
    assert state.resolved_current_mass_kg == pytest.approx(925.0)


def test_operational_state_rejects_inconsistent_mass() -> None:
    with pytest.raises(ValidationError, match="must equal dry_mass_kg"):
        SpacecraftOperationalState(
            satellite_id="SAT-1",
            dry_mass_kg=850.0,
            current_propellant_mass_kg=75.0,
            current_mass_kg=930.0,
        )


def test_gaussian_rule_requires_sigma() -> None:
    with pytest.raises(ValidationError, match="requires sigma"):
        PerturbationRule(
            rule_id="r1",
            parameter="semi_major_axis",
            distribution=PerturbationDistribution.GAUSSIAN,
            scope=PerturbationScope.CONSTELLATION,
            unit="m",
        )


def test_group_and_individual_targets_validate_against_constellation() -> None:
    base = load_scenario(ROOT / "scenarios" / "mvp_45deg.yaml")
    satellite_ids = [sat.satellite_id for sat in base.constellation.satellites]
    assert satellite_ids
    first = satellite_ids[0]

    twin = DigitalTwinConfig(
        spacecraft_states=(
            SpacecraftOperationalState(
                satellite_id=first,
                dry_mass_kg=850.0,
                current_propellant_mass_kg=50.0,
            ),
        ),
        groups=(SpacecraftGroup(group_id="type-1", satellite_ids=(first,)),),
        perturbations=(
            PerturbationRule(
                rule_id="group-a",
                parameter="raan",
                distribution=PerturbationDistribution.GAUSSIAN,
                scope=PerturbationScope.GROUP,
                target_ids=("type-1",),
                mean=0.0,
                sigma=0.01,
                unit="rad",
            ),
            PerturbationRule(
                rule_id="sat-a",
                parameter="semi_major_axis",
                distribution=PerturbationDistribution.UNIFORM,
                scope=PerturbationScope.SATELLITE,
                target_ids=(first,),
                lower_bound=-1000.0,
                upper_bound=1000.0,
                unit="m",
            ),
        ),
    )

    scenario = ScenarioConfig.model_validate({**base.model_dump(mode="json"), "digital_twin": twin.model_dump(mode="json")})
    assert scenario.digital_twin is not None
    assert scenario.digital_twin.groups[0].group_id == "type-1"


def test_unknown_spacecraft_target_fails_closed() -> None:
    base = load_scenario(ROOT / "scenarios" / "mvp_45deg.yaml")
    twin = DigitalTwinConfig(
        perturbations=(
            PerturbationRule(
                rule_id="bad-target",
                parameter="inclination",
                distribution=PerturbationDistribution.GAUSSIAN,
                scope=PerturbationScope.SATELLITE,
                target_ids=("UNKNOWN-SAT",),
                sigma=0.001,
                unit="rad",
            ),
        )
    )

    with pytest.raises(ValidationError, match="unknown targets"):
        ScenarioConfig.model_validate({**base.model_dump(mode="json"), "digital_twin": twin.model_dump(mode="json")})
