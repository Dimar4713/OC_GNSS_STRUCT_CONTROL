from __future__ import annotations

from pathlib import Path

import pytest

from constellation_control.application.run import load_scenario
from constellation_control.domain.digital_twin import (
    DigitalTwinConfig,
    PerturbationDistribution,
    PerturbationRule,
    PerturbationScope,
    SpacecraftGroup,
)
from constellation_control.dynamics.orbits import mean_to_classical
from constellation_control.preview.perturbation_input import apply_perturbation_rules, create_perturbed_scenario


def _rule(
    rule_id: str,
    *,
    parameter: str = "a_m",
    scope: PerturbationScope = PerturbationScope.CONSTELLATION,
    target_ids: tuple[str, ...] = (),
    mean: float = 10.0,
    sigma: float = 0.0,
    unit: str = "m",
) -> PerturbationRule:
    return PerturbationRule(
        rule_id=rule_id,
        parameter=parameter,
        distribution=PerturbationDistribution.GAUSSIAN,
        scope=scope,
        target_ids=target_ids,
        mean=mean,
        sigma=sigma,
        unit=unit,
    )


def test_perturbation_mean_is_explicit() -> None:
    with pytest.raises(ValueError):
        PerturbationRule.model_validate(
            {
                "rule_id": "missing-mean",
                "parameter": "a_m",
                "distribution": "gaussian",
                "scope": "constellation",
                "sigma": 1.0,
                "unit": "m",
            }
        )


def test_satellite_rule_overrides_group_plane_and_constellation() -> None:
    source = load_scenario(Path("scenarios/mvp_45deg.yaml"))
    source = source.model_copy(
        update={
            "digital_twin": DigitalTwinConfig(
                groups=(SpacecraftGroup(group_id="G1", satellite_ids=("DEMO-ADD-45",)),)
            )
        }
    )
    rules = (
        _rule("const", mean=1.0),
        _rule("plane", scope=PerturbationScope.PLANE, target_ids=("P1",), mean=2.0),
        _rule("group", scope=PerturbationScope.GROUP, target_ids=("G1",), mean=3.0),
        _rule("sat", scope=PerturbationScope.SATELLITE, target_ids=("DEMO-ADD-45",), mean=4.0),
    )

    satellites, applied = apply_perturbation_rules(source, rules=rules, seed=4713)
    by_id = {sat.satellite_id: mean_to_classical(sat.mean_orbit) for sat in satellites}
    original = {sat.satellite_id: mean_to_classical(sat.mean_orbit) for sat in source.constellation.satellites}

    assert by_id["DEMO-REF"].a_m == pytest.approx(original["DEMO-REF"].a_m + 2.0)
    assert by_id["DEMO-ADD-45"].a_m == pytest.approx(original["DEMO-ADD-45"].a_m + 4.0)
    assert {(item.satellite_id, item.rule_id) for item in applied} == {
        ("DEMO-REF", "plane"),
        ("DEMO-ADD-45", "sat"),
    }


def test_same_seed_is_deterministic_and_order_independent() -> None:
    source = load_scenario(Path("scenarios/mvp_45deg.yaml"))
    rule = _rule("noise", mean=0.0, sigma=25.0)
    first_satellites, first_applied = apply_perturbation_rules(source, rules=(rule,), seed=12345)
    second_satellites, second_applied = apply_perturbation_rules(source, rules=(rule,), seed=12345)

    assert first_satellites == second_satellites
    assert first_applied == second_applied


def test_ambiguous_equal_precedence_fails_closed() -> None:
    source = load_scenario(Path("scenarios/mvp_45deg.yaml"))
    rules = (
        _rule("plane-a", scope=PerturbationScope.PLANE, target_ids=("P1",), mean=1.0),
        _rule("plane-b", scope=PerturbationScope.PLANE, target_ids=("P1",), mean=2.0),
    )
    with pytest.raises(ValueError, match="ambiguous perturbation rules"):
        apply_perturbation_rules(source, rules=rules, seed=1)


def test_unknown_target_and_wrong_unit_fail_closed() -> None:
    source = load_scenario(Path("scenarios/mvp_45deg.yaml"))
    with pytest.raises(ValueError, match="unknown targets"):
        apply_perturbation_rules(
            source,
            rules=(_rule("bad-target", scope=PerturbationScope.SATELLITE, target_ids=("UNKNOWN",)),),
            seed=1,
        )
    with pytest.raises(ValueError, match="requires unit"):
        apply_perturbation_rules(source, rules=(_rule("bad-unit", unit="km"),), seed=1)


def test_create_perturbed_scenario_preserves_parent_and_records_samples(tmp_path: Path) -> None:
    source_path = tmp_path / "source.yaml"
    source_path.write_bytes(Path("scenarios/mvp_45deg.yaml").read_bytes())
    before = source_path.read_bytes()

    result = create_perturbed_scenario(
        tmp_path,
        source_scenario_name="source.yaml",
        target_scenario_name="child.yaml",
        new_scenario_id="perturbed-child",
        rules=(_rule("a-noise", mean=15.0, sigma=0.0),),
        seed=777,
    )

    assert source_path.read_bytes() == before
    child = load_scenario(tmp_path / "child.yaml")
    assert result["applied_count"] == 2
    assert child.digital_twin is not None
    assert child.digital_twin.lineage is not None
    assert child.digital_twin.lineage.transformation == "perturbation"
    assert child.digital_twin.lineage.random_seed == 777
    assert len(child.digital_twin.applied_perturbations) == 2
    assert child.config_hash() != load_scenario(source_path).config_hash()


def test_create_perturbed_scenario_rejects_overwrite_and_source_traversal(tmp_path: Path) -> None:
    (tmp_path / "source.yaml").write_bytes(Path("scenarios/mvp_45deg.yaml").read_bytes())
    (tmp_path / "existing.yaml").write_text("occupied", encoding="utf-8")
    rule = _rule("a-noise", mean=1.0, sigma=0.0)

    with pytest.raises(ValueError, match="overwrite"):
        create_perturbed_scenario(
            tmp_path,
            source_scenario_name="source.yaml",
            target_scenario_name="existing.yaml",
            new_scenario_id="child",
            rules=(rule,),
            seed=1,
        )
    with pytest.raises(ValueError, match="source_scenario_name"):
        create_perturbed_scenario(
            tmp_path,
            source_scenario_name="../source.yaml",
            target_scenario_name="child.yaml",
            new_scenario_id="child",
            rules=(rule,),
            seed=1,
        )
