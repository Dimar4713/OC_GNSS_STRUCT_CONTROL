from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from itertools import combinations
from math import hypot
from pathlib import Path

import numpy as np
import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from constellation_control.adapters.orekit.adapter import OrekitSidecarPropagator
from constellation_control.analysis.fuel import propellant_used_kg
from constellation_control.application.run import load_scenario
from constellation_control.domain.models import (
    ForceMode,
    Maneuver,
    PropagationRequest,
    PropagationResult,
    SatelliteSpec,
    ScenarioConfig,
)
from constellation_control.mean_elements.roe import damico_roe
from constellation_control.uncertainty.campaign import (
    DistributionKind,
    RobustnessCampaignConfig,
    RobustnessCampaignResult,
    campaign_config_hash,
    run_robustness_campaign,
)


class RobustnessAuthorityConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    backend_prefix: str = "orekit-numerical"
    orekit_version: str = Field(min_length=1)
    gravity_model: str = Field(min_length=1)
    orekit_data_revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    orekit_data_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class RobustnessApplicationConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    campaign: RobustnessCampaignConfig
    authority: RobustnessAuthorityConfig
    baseline_maneuvers: tuple[Maneuver, ...]

    @model_validator(mode="after")
    def require_baseline_control(self) -> RobustnessApplicationConfig:
        if not self.baseline_maneuvers:
            raise ValueError("robustness campaign requires at least one accepted baseline maneuver")
        return self


@dataclass(frozen=True)
class AppliedUncertainty:
    request: PropagationRequest
    dropped_maneuver_indices: tuple[int, ...]


def load_robustness_application_config(path: Path) -> RobustnessApplicationConfig:
    return RobustnessApplicationConfig.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


def _allowed_uncertainty_names(scenario: ScenarioConfig, config: RobustnessApplicationConfig) -> set[str]:
    allowed: set[str] = set()
    mean_components = (
        "delta_a_m",
        "delta_ex",
        "delta_ey",
        "delta_ix",
        "delta_iy",
        "delta_lambda_rad",
    )
    for satellite in scenario.constellation.satellites:
        for source in ("initial", "od"):
            allowed.update(f"{source}.{satellite.satellite_id}.{component}" for component in mean_components)
        allowed.add(f"slot.{satellite.satellite_id}.delta_lambda_rad")
        allowed.add(f"spacecraft.{satellite.satellite_id}.cr_area_over_mass_fraction")
    for index, _ in enumerate(config.baseline_maneuvers):
        allowed.update(
            {
                f"maneuver.{index}.magnitude_fraction",
                f"maneuver.{index}.direction_r_rad",
                f"maneuver.{index}.direction_t_rad",
                f"maneuver.{index}.direction_n_rad",
                f"maneuver.{index}.timing_error_s",
                f"window.{index}.unavailable",
            }
        )
    return allowed


def validate_uncertainty_contract(scenario: ScenarioConfig, config: RobustnessApplicationConfig) -> None:
    """Reject unknown or incorrectly typed uncertainty variables before sampling.

    This prevents a typo in a YAML variable name from silently becoming an
    un-applied uncertainty and producing falsely optimistic robustness evidence.
    """

    allowed = _allowed_uncertainty_names(scenario, config)
    configured: list[str] = []
    for item in config.campaign.scalar_uncertainties:
        configured.append(item.name)
        is_window = item.name.startswith("window.") and item.name.endswith(".unavailable")
        if is_window and item.distribution != DistributionKind.BERNOULLI:
            raise ValueError(f"maneuver-window availability must be Bernoulli: {item.name}")
        if not is_window and item.distribution == DistributionKind.BERNOULLI:
            raise ValueError(f"Bernoulli uncertainty is reserved for window availability: {item.name}")
    for group in config.campaign.correlated_normal_groups:
        for name in group.names:
            configured.append(name)
            if name.startswith("window.") and name.endswith(".unavailable"):
                raise ValueError("window availability cannot be part of a correlated normal group")
    unknown = sorted(set(configured) - allowed)
    if unknown:
        raise ValueError(f"unknown robustness uncertainty variable(s): {unknown}")


def _number(sample: dict[str, object], name: str) -> float:
    value = sample.get(name, 0.0)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"uncertainty variable {name!r} must be numeric")
    numeric = float(value)
    if not np.isfinite(numeric):
        raise ValueError(f"uncertainty variable {name!r} must be finite")
    return numeric


def _flag(sample: dict[str, object], name: str) -> bool:
    value = sample.get(name, False)
    if not isinstance(value, bool):
        raise TypeError(f"uncertainty variable {name!r} must be boolean")
    return value


def _perturb_satellite(satellite: SatelliteSpec, sample: dict[str, object]) -> SatelliteSpec:
    satellite_id = satellite.satellite_id
    mean = satellite.mean_orbit
    a_delta = _number(sample, f"initial.{satellite_id}.delta_a_m") + _number(
        sample, f"od.{satellite_id}.delta_a_m"
    )
    ex_delta = _number(sample, f"initial.{satellite_id}.delta_ex") + _number(sample, f"od.{satellite_id}.delta_ex")
    ey_delta = _number(sample, f"initial.{satellite_id}.delta_ey") + _number(sample, f"od.{satellite_id}.delta_ey")
    ix_delta = _number(sample, f"initial.{satellite_id}.delta_ix") + _number(sample, f"od.{satellite_id}.delta_ix")
    iy_delta = _number(sample, f"initial.{satellite_id}.delta_iy") + _number(sample, f"od.{satellite_id}.delta_iy")
    lambda_delta = (
        _number(sample, f"initial.{satellite_id}.delta_lambda_rad")
        + _number(sample, f"od.{satellite_id}.delta_lambda_rad")
        + _number(sample, f"slot.{satellite_id}.delta_lambda_rad")
    )
    perturbed_mean = mean.model_copy(
        update={
            "a_m": mean.a_m + a_delta,
            "ex": mean.ex + ex_delta,
            "ey": mean.ey + ey_delta,
            "ix": mean.ix + ix_delta,
            "iy": mean.iy + iy_delta,
            "lambda_rad": mean.lambda_rad + lambda_delta,
        }
    )
    cr_fraction = _number(sample, f"spacecraft.{satellite_id}.cr_area_over_mass_fraction")
    cr = satellite.spacecraft.cr * (1.0 + cr_fraction)
    if cr <= 0.0:
        raise ValueError(f"sample produced non-positive Cr for {satellite_id}")
    spacecraft = satellite.spacecraft.model_copy(update={"cr": cr})
    return satellite.model_copy(update={"mean_orbit": perturbed_mean, "spacecraft": spacecraft})


def _perturb_maneuver(index: int, maneuver: Maneuver, sample: dict[str, object], duration_s: float) -> Maneuver | None:
    if _flag(sample, f"window.{index}.unavailable"):
        return None
    magnitude_fraction = _number(sample, f"maneuver.{index}.magnitude_fraction")
    scale = 1.0 + magnitude_fraction
    if scale <= 0.0:
        raise ValueError(f"sample produced non-positive maneuver magnitude scale for maneuver {index}")
    rotation = np.asarray(
        [
            _number(sample, f"maneuver.{index}.direction_r_rad"),
            _number(sample, f"maneuver.{index}.direction_t_rad"),
            _number(sample, f"maneuver.{index}.direction_n_rad"),
        ],
        dtype=float,
    )
    nominal = np.asarray(maneuver.dv_rtn_m_s, dtype=float)
    perturbed_dv = scale * nominal + np.cross(rotation, nominal)
    time_s = maneuver.time_s + _number(sample, f"maneuver.{index}.timing_error_s")
    if time_s < 0.0 or time_s > duration_s:
        return None
    return maneuver.model_copy(
        update={
            "time_s": float(time_s),
            "dv_rtn_m_s": tuple(float(value) for value in perturbed_dv),
        }
    )


def apply_uncertainty_sample(
    scenario: ScenarioConfig,
    config: RobustnessApplicationConfig,
    sample: dict[str, object],
) -> AppliedUncertainty:
    satellites = tuple(_perturb_satellite(satellite, sample) for satellite in scenario.constellation.satellites)
    maneuvers: list[Maneuver] = []
    dropped: list[int] = []
    for index, maneuver in enumerate(config.baseline_maneuvers):
        perturbed = _perturb_maneuver(index, maneuver, sample, scenario.duration_s)
        if perturbed is None:
            dropped.append(index)
        else:
            maneuvers.append(perturbed)
    request = PropagationRequest(
        scenario_id=scenario.scenario_id,
        epoch=scenario.epoch,
        frame=scenario.frame,
        time_scale=scenario.time_scale,
        satellites=satellites,
        maneuvers=tuple(maneuvers),
        duration_s=scenario.duration_s,
        output_step_s=scenario.output_step_s,
        force_model=scenario.force_model,
        integrator=scenario.integrator,
        seed=int(sample["realization_seed"]),
    )
    return AppliedUncertainty(request=request, dropped_maneuver_indices=tuple(dropped))


def _verify_authority(
    result: PropagationResult,
    request: PropagationRequest,
    authority: RobustnessAuthorityConfig,
) -> None:
    if not result.backend.lower().startswith(authority.backend_prefix.lower()):
        raise RuntimeError(f"robustness claim requires {authority.backend_prefix}, got {result.backend}")
    if result.force_model_fingerprint != request.force_model.fingerprint():
        raise RuntimeError("robustness replay force-model fingerprint mismatch")
    metadata = result.backend_metadata
    expected = {
        "orekit_version": authority.orekit_version,
        "gravity_model": authority.gravity_model,
        "orekit_data_revision": authority.orekit_data_revision,
        "orekit_data_sha256": authority.orekit_data_sha256,
    }
    for key, value in expected.items():
        if metadata.get(key) != value:
            raise RuntimeError(f"robustness replay authority mismatch for {key}: {metadata.get(key)!r}")


def _pair_minimum_distance(result: PropagationResult, satellite_ids: tuple[str, ...]) -> float:
    minimum = float("inf")
    for left_id, right_id in combinations(satellite_ids, 2):
        for left, right in zip(result.cartesian_states[left_id], result.cartesian_states[right_id], strict=True):
            minimum = min(minimum, float(np.linalg.norm(np.asarray(left.r_m) - np.asarray(right.r_m))))
    if not np.isfinite(minimum):
        raise RuntimeError("robustness replay produced no pair-distance evidence")
    return minimum


def _evaluate_trajectory(
    scenario: ScenarioConfig,
    applied: AppliedUncertainty,
    result: PropagationResult,
) -> dict[str, object]:
    by_id = {sat.satellite_id: sat for sat in applied.request.satellites}
    max_phase = 0.0
    max_e = 0.0
    max_i = 0.0
    min_delta_a_margin = float("inf")
    lower_da, upper_da = scenario.constraints.delta_a_bounds_m
    violations: dict[str, bool] = {
        "minimum_pair_distance": False,
        "phase_corridor": False,
        "delta_a_corridor": False,
        "eccentricity_corridor": False,
        "inclination_corridor": False,
        "propellant_reserve": False,
        "maneuver_window_unavailable": bool(applied.dropped_maneuver_indices),
    }
    controlled_pairs = 0
    for deputy in applied.request.satellites:
        if deputy.role != "additional" or deputy.reference_id is None:
            continue
        controlled_pairs += 1
        reference = by_id[deputy.reference_id]
        for ref_mean, dep_mean in zip(
            result.mean_orbits[reference.satellite_id],
            result.mean_orbits[deputy.satellite_id],
            strict=True,
        ):
            roe = damico_roe(ref_mean, dep_mean)
            delta_a_m = roe.delta_a * ref_mean.a_m
            max_phase = max(max_phase, abs(roe.delta_lambda_rad))
            max_e = max(max_e, hypot(roe.delta_ex, roe.delta_ey))
            max_i = max(max_i, hypot(roe.delta_ix, roe.delta_iy))
            min_delta_a_margin = min(min_delta_a_margin, delta_a_m - lower_da, upper_da - delta_a_m)
            violations["delta_a_corridor"] |= not lower_da <= delta_a_m <= upper_da
            violations["phase_corridor"] |= abs(roe.delta_lambda_rad) > scenario.constraints.phase_corridor_rad
            violations["eccentricity_corridor"] |= hypot(roe.delta_ex, roe.delta_ey) > scenario.constraints.delta_e_max
            violations["inclination_corridor"] |= hypot(roe.delta_ix, roe.delta_iy) > scenario.constraints.delta_i_max_rad
    if controlled_pairs == 0 or not np.isfinite(min_delta_a_margin):
        raise RuntimeError("robustness trajectory requires at least one additional/reference pair")

    satellite_ids = tuple(by_id)
    minimum_distance = _pair_minimum_distance(result, satellite_ids)
    violations["minimum_pair_distance"] = minimum_distance < scenario.constraints.min_pair_distance_m

    maneuvers_by_satellite: dict[str, list[Maneuver]] = {satellite_id: [] for satellite_id in satellite_ids}
    for maneuver in applied.request.maneuvers:
        maneuvers_by_satellite[maneuver.satellite_id].append(maneuver)

    spacecraft_metrics: dict[str, object] = {}
    fleet_delta_v = 0.0
    fleet_propellant_used = 0.0
    finite_lifetimes: list[float] = []
    for satellite in applied.request.satellites:
        delta_v = sum(float(np.linalg.norm(maneuver.dv_rtn_m_s)) for maneuver in maneuvers_by_satellite[satellite.satellite_id])
        used = propellant_used_kg(satellite.spacecraft.initial_mass_kg, delta_v, satellite.spacecraft.isp_s)
        residual = satellite.spacecraft.propellant_mass_kg - used
        reserve = satellite.spacecraft.propellant_mass_kg * scenario.constraints.propellant_reserve_fraction
        violations["propellant_reserve"] |= residual < reserve
        lifetime_to_reserve_s: float | None
        if used > 0.0:
            usable = max(satellite.spacecraft.propellant_mass_kg - reserve, 0.0)
            lifetime_to_reserve_s = scenario.duration_s * usable / used
            finite_lifetimes.append(lifetime_to_reserve_s)
        else:
            lifetime_to_reserve_s = None
        spacecraft_metrics[satellite.satellite_id] = {
            "delta_v_m_s": delta_v,
            "propellant_used_kg": used,
            "residual_propellant_kg": residual,
            "required_reserve_kg": reserve,
            "reserve_lifetime_estimate_s": lifetime_to_reserve_s,
        }
        fleet_delta_v += delta_v
        fleet_propellant_used += used

    return {
        "fleet": {
            "total_delta_v_m_s": fleet_delta_v,
            "total_propellant_used_kg": fleet_propellant_used,
            "minimum_pair_distance_m": minimum_distance,
            "max_abs_delta_lambda_rad": max_phase,
            "max_relative_eccentricity": max_e,
            "max_relative_inclination_rad": max_i,
            "minimum_delta_a_margin_m": min_delta_a_margin,
            "reserve_lifetime_estimate_s": min(finite_lifetimes) if finite_lifetimes else None,
        },
        "spacecraft": spacecraft_metrics,
        "dropped_maneuver_indices": list(applied.dropped_maneuver_indices),
        "backend": result.backend,
        "backend_metadata": dict(sorted(result.backend_metadata.items())),
        "violations": violations,
    }


def run_robustness_application(
    scenario_path: Path,
    campaign_path: Path,
    output_root: Path,
) -> Path:
    scenario = load_scenario(scenario_path)
    config = load_robustness_application_config(campaign_path)
    if scenario.force_model.mode != ForceMode.VALIDATION:
        raise ValueError("final robustness campaign requires validation force mode")
    if not scenario.orekit_sidecar_url:
        raise ValueError("final robustness campaign requires orekit_sidecar_url")
    known_satellites = {sat.satellite_id for sat in scenario.constellation.satellites}
    if not any(sat.role == "additional" and sat.reference_id is not None for sat in scenario.constellation.satellites):
        raise ValueError("robustness campaign requires at least one additional/reference pair")
    for maneuver in config.baseline_maneuvers:
        if maneuver.satellite_id not in known_satellites:
            raise ValueError(f"baseline maneuver targets unknown satellite: {maneuver.satellite_id}")
        if maneuver.time_s > scenario.duration_s:
            raise ValueError("baseline maneuver lies outside scenario horizon")
    validate_uncertainty_contract(scenario, config)

    propagator = OrekitSidecarPropagator(scenario.orekit_sidecar_url, timeout_s=300.0)

    def evaluator(sample: dict[str, object]) -> dict[str, object]:
        applied = apply_uncertainty_sample(scenario, config, sample)
        result = propagator.propagate(applied.request)
        _verify_authority(result, applied.request, config.authority)
        return _evaluate_trajectory(scenario, applied, result)

    payload = {
        "scenario_hash": scenario.config_hash(),
        "campaign_hash": campaign_config_hash(config.campaign),
        "force_model_fingerprint": scenario.force_model.fingerprint(),
        "accepted_candidate_id": config.campaign.accepted_candidate_id,
    }
    run_hash = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:20]
    output_dir = output_root / f"{scenario.scenario_id}--robustness" / run_hash
    provenance = {
        "scenario_id": scenario.scenario_id,
        "scenario_config_hash": scenario.config_hash(),
        "force_model_fingerprint": scenario.force_model.fingerprint(),
        "frame": scenario.frame.value,
        "time_scale": scenario.time_scale.value,
        "accepted_candidate_id": config.campaign.accepted_candidate_id,
        "required_backend_prefix": config.authority.backend_prefix,
        "required_orekit_version": config.authority.orekit_version,
        "required_gravity_model": config.authority.gravity_model,
        "required_orekit_data_revision": config.authority.orekit_data_revision,
        "required_orekit_data_sha256": config.authority.orekit_data_sha256,
    }
    result: RobustnessCampaignResult = run_robustness_campaign(
        config.campaign,
        evaluator,
        output_dir,
        provenance=provenance,
    )
    return result.output_dir
