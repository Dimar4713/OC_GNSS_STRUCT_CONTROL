from __future__ import annotations

import hashlib
from dataclasses import replace
from math import pi
from pathlib import Path

import numpy as np
import yaml

from constellation_control.application.run import load_scenario
from constellation_control.domain.digital_twin import (
    AppliedPerturbation,
    DigitalTwinConfig,
    PerturbationDistribution,
    PerturbationRule,
    PerturbationScope,
    ScenarioLineage,
)
from constellation_control.domain.models import ScenarioConfig, SatelliteSpec
from constellation_control.dynamics.orbits import ClassicalElements, classical_to_mean, mean_to_classical, wrap_pi

_SUPPORTED_PARAMETERS: dict[str, str] = {
    "a_m": "m",
    "e": "1",
    "i_rad": "rad",
    "raan_rad": "rad",
    "argp_rad": "rad",
    "mean_anomaly_rad": "rad",
}
_SCOPE_RANK = {
    PerturbationScope.CONSTELLATION: 0,
    PerturbationScope.PLANE: 1,
    PerturbationScope.GROUP: 2,
    PerturbationScope.SATELLITE: 3,
}


def _safe_existing_scenario(root: Path, name: str) -> Path:
    if not name or Path(name).name != name or not name.lower().endswith((".yaml", ".yml")):
        raise ValueError("source_scenario_name must be an existing YAML file name without path components")
    resolved_root = root.resolve()
    candidate = (resolved_root / name).resolve()
    if candidate.parent != resolved_root or not candidate.is_file():
        raise ValueError("source scenario does not exist inside scenario root")
    return candidate


def _matches(rule: PerturbationRule, satellite: SatelliteSpec, twin: DigitalTwinConfig) -> bool:
    if rule.scope == PerturbationScope.CONSTELLATION:
        return True
    if rule.scope == PerturbationScope.PLANE:
        return satellite.plane_id in rule.target_ids
    if rule.scope == PerturbationScope.SATELLITE:
        return satellite.satellite_id in rule.target_ids
    groups = {group.group_id: set(group.satellite_ids) for group in twin.groups}
    return any(satellite.satellite_id in groups.get(group_id, set()) for group_id in rule.target_ids)


def _selected_rule(
    rules: tuple[PerturbationRule, ...],
    satellite: SatelliteSpec,
    twin: DigitalTwinConfig,
    parameter: str,
) -> PerturbationRule | None:
    matches = [rule for rule in rules if rule.parameter == parameter and _matches(rule, satellite, twin)]
    if not matches:
        return None
    rank = max(_SCOPE_RANK[rule.scope] for rule in matches)
    winners = [rule for rule in matches if _SCOPE_RANK[rule.scope] == rank]
    if len(winners) != 1:
        ids = ", ".join(sorted(rule.rule_id for rule in winners))
        raise ValueError(
            f"ambiguous perturbation rules for satellite={satellite.satellite_id} parameter={parameter}: {ids}"
        )
    return winners[0]


def _sample(seed: int, satellite_id: str, rule: PerturbationRule) -> float:
    key = f"{seed}\0{satellite_id}\0{rule.rule_id}\0{rule.parameter}".encode()
    derived = int.from_bytes(hashlib.sha256(key).digest()[:8], "big", signed=False)
    rng = np.random.default_rng(derived)
    if rule.distribution == PerturbationDistribution.GAUSSIAN:
        if rule.sigma is None:
            raise ValueError(f"gaussian rule {rule.rule_id} requires sigma")
        return float(rng.normal(rule.mean, rule.sigma))
    if rule.lower_bound is None or rule.upper_bound is None:
        raise ValueError(f"uniform rule {rule.rule_id} requires bounds")
    return float(rng.uniform(rule.lower_bound, rule.upper_bound))


def _replace_parameter(elements: ClassicalElements, parameter: str, delta: float) -> ClassicalElements:
    values = {
        "a_m": elements.a_m,
        "e": elements.e,
        "i_rad": elements.i_rad,
        "raan_rad": elements.raan_rad,
        "argp_rad": elements.argp_rad,
        "mean_anomaly_rad": elements.mean_anomaly_rad,
    }
    values[parameter] += delta
    if values["a_m"] <= 0.0:
        raise ValueError("perturbation produced non-positive semi-major axis")
    if not 0.0 <= values["e"] < 1.0:
        raise ValueError("perturbation produced eccentricity outside [0, 1)")
    if not 0.0 <= values["i_rad"] <= pi:
        raise ValueError("perturbation produced inclination outside [0, pi]")
    values["raan_rad"] = wrap_pi(values["raan_rad"])
    values["argp_rad"] = wrap_pi(values["argp_rad"])
    values["mean_anomaly_rad"] = wrap_pi(values["mean_anomaly_rad"])
    return replace(elements, **values)


def _validate_rule_targets(source: ScenarioConfig, rules: tuple[PerturbationRule, ...]) -> DigitalTwinConfig:
    prior_twin = source.digital_twin or DigitalTwinConfig()
    candidate_twin = prior_twin.model_copy(update={"perturbations": rules, "applied_perturbations": ()})
    ScenarioConfig.model_validate(
        source.model_dump(mode="json") | {"digital_twin": candidate_twin.model_dump(mode="json")}
    )
    return prior_twin


def apply_perturbation_rules(
    source: ScenarioConfig,
    *,
    rules: tuple[PerturbationRule, ...],
    seed: int,
) -> tuple[tuple[SatelliteSpec, ...], tuple[AppliedPerturbation, ...]]:
    twin = _validate_rule_targets(source, rules)
    for rule in rules:
        expected = _SUPPORTED_PARAMETERS.get(rule.parameter)
        if expected is None:
            raise ValueError(f"unsupported perturbation parameter: {rule.parameter}")
        if rule.unit != expected:
            raise ValueError(f"parameter {rule.parameter} requires unit {expected}, got {rule.unit}")

    satellites: list[SatelliteSpec] = []
    applied: list[AppliedPerturbation] = []
    for satellite in source.constellation.satellites:
        elements = mean_to_classical(satellite.mean_orbit)
        for parameter in _SUPPORTED_PARAMETERS:
            rule = _selected_rule(rules, satellite, twin, parameter)
            if rule is None:
                continue
            delta = _sample(seed, satellite.satellite_id, rule)
            elements = _replace_parameter(elements, parameter, delta)
            applied.append(
                AppliedPerturbation(
                    rule_id=rule.rule_id,
                    satellite_id=satellite.satellite_id,
                    parameter=parameter,
                    sampled_delta=delta,
                    unit=rule.unit,
                )
            )
        satellites.append(
            satellite.model_copy(
                update={"mean_orbit": classical_to_mean(elements, satellite.mean_orbit.definition)}
            )
        )
    return tuple(satellites), tuple(applied)


def create_perturbed_scenario(
    scenario_root: Path,
    *,
    source_scenario_name: str,
    target_scenario_name: str,
    new_scenario_id: str,
    rules: tuple[PerturbationRule, ...],
    seed: int,
) -> dict[str, object]:
    if not rules:
        raise ValueError("at least one enabled perturbation rule is required")
    source = load_scenario(_safe_existing_scenario(scenario_root, source_scenario_name))
    if new_scenario_id == source.scenario_id:
        raise ValueError("new_scenario_id must differ from parent scenario_id")
    if not target_scenario_name or Path(target_scenario_name).name != target_scenario_name:
        raise ValueError("target_scenario_name must not contain path components")
    if not target_scenario_name.lower().endswith((".yaml", ".yml")):
        raise ValueError("target_scenario_name must end with .yaml or .yml")
    root = scenario_root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    target = (root / target_scenario_name).resolve()
    if target.parent != root:
        raise ValueError("invalid target scenario path")
    if target.exists():
        raise ValueError("target scenario already exists; overwrite is forbidden")

    satellites, applied = apply_perturbation_rules(source, rules=rules, seed=seed)
    constellation = source.constellation.model_copy(update={"satellites": satellites})
    prior_twin = source.digital_twin or DigitalTwinConfig()
    twin = prior_twin.model_copy(
        update={
            "perturbations": rules,
            "applied_perturbations": applied,
            "lineage": ScenarioLineage(
                parent_scenario_id=source.scenario_id,
                parent_config_hash=source.config_hash(),
                transformation="perturbation",
                random_seed=seed,
            ),
        }
    )
    child = ScenarioConfig.model_validate(
        source.model_dump(mode="json")
        | {
            "scenario_id": new_scenario_id,
            "constellation": constellation.model_dump(mode="json"),
            "digital_twin": twin.model_dump(mode="json"),
        }
    )
    target.write_text(
        yaml.safe_dump(child.model_dump(mode="json"), sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    return {
        "saved": True,
        "scenario_name": target.name,
        "scenario_id": child.scenario_id,
        "parent_scenario_id": source.scenario_id,
        "parent_config_hash": source.config_hash(),
        "child_config_hash": child.config_hash(),
        "seed": seed,
        "applied_count": len(applied),
        "applied_perturbations": [item.model_dump(mode="json") for item in applied],
    }
