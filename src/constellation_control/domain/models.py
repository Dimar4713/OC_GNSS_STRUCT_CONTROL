from __future__ import annotations

import hashlib
import json
from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from constellation_control.domain.navigation import NavigationSiteConfig


class ForceMode(StrEnum):
    SCREENING = "screening"
    DESIGN = "design"
    VALIDATION = "validation"


class GravityModelName(StrEnum):
    EIGEN_6S = "EIGEN-6S"


class FrameName(StrEnum):
    EME2000 = "EME2000"
    GCRF = "GCRF"
    ICRF = "ICRF"
    ITRF = "ITRF"


class TimeScaleName(StrEnum):
    UTC = "UTC"
    TAI = "TAI"
    TT = "TT"
    GPS = "GPS"


class MeanElementDefinition(BaseModel):
    model_config = ConfigDict(frozen=True)
    representation: Literal["equinoctial"] = "equinoctial"
    theory: str
    force_model_fingerprint: str


class MeanOrbit(BaseModel):
    model_config = ConfigDict(frozen=True)
    a_m: float = Field(gt=0.0)
    ex: float
    ey: float
    ix: float
    iy: float
    lambda_rad: float
    definition: MeanElementDefinition


class OsculatingState(BaseModel):
    model_config = ConfigDict(frozen=True)
    epoch_s: float
    r_m: tuple[float, float, float]
    v_m_s: tuple[float, float, float]


class SpacecraftModel(BaseModel):
    model_config = ConfigDict(frozen=True)
    dry_mass_kg: float = Field(gt=0.0)
    propellant_mass_kg: float = Field(ge=0.0)
    isp_s: float = Field(gt=0.0)
    area_m2: float = Field(gt=0.0)
    cr: float = Field(gt=0.0)

    @property
    def initial_mass_kg(self) -> float:
        return self.dry_mass_kg + self.propellant_mass_kg


class SatelliteSpec(BaseModel):
    model_config = ConfigDict(frozen=True)
    satellite_id: str
    plane_id: str
    role: Literal["reference", "additional"]
    reference_id: str | None = None
    mean_orbit: MeanOrbit
    spacecraft: SpacecraftModel

    @model_validator(mode="after")
    def validate_reference(self) -> SatelliteSpec:
        if self.role == "additional" and not self.reference_id:
            raise ValueError("additional satellite requires reference_id")
        return self


class PlaneSpec(BaseModel):
    model_config = ConfigDict(frozen=True)
    plane_id: str
    satellite_ids: tuple[str, ...] = ()


class ConstellationSpec(BaseModel):
    model_config = ConfigDict(frozen=True)
    satellites: tuple[SatelliteSpec, ...]
    planes: tuple[PlaneSpec, ...] = ()

    @model_validator(mode="after")
    def validate_ids(self) -> ConstellationSpec:
        ids = [sat.satellite_id for sat in self.satellites]
        if len(ids) != len(set(ids)):
            raise ValueError("satellite_id values must be unique")
        known = set(ids)
        for sat in self.satellites:
            if sat.reference_id and sat.reference_id not in known:
                raise ValueError(f"unknown reference_id: {sat.reference_id}")
        return self


class ForceModelConfig(BaseModel):
    model_config = ConfigDict(frozen=True)
    mode: ForceMode
    gravity_model: GravityModelName | None = None
    mu_m3_s2: float = Field(gt=0.0)
    reference_radius_m: float = Field(gt=0.0)
    flattening: float = Field(ge=0.0, lt=1.0)
    j2: float
    earth_rotation_rate_rad_s: float = Field(gt=0.0)
    gravity_degree: int = Field(ge=0)
    gravity_order: int = Field(ge=0)
    moon: bool = False
    sun: bool = False
    srp: bool = False
    tides: bool = False
    relativity: bool = False

    @model_validator(mode="after")
    def validate_gravity_configuration(self) -> ForceModelConfig:
        if self.gravity_order > self.gravity_degree:
            raise ValueError("gravity_order must not exceed gravity_degree")
        if self.mode in (ForceMode.DESIGN, ForceMode.VALIDATION) and self.gravity_model is None:
            raise ValueError("high-fidelity force model requires explicit gravity_model")
        return self

    def fingerprint(self) -> str:
        raw = json.dumps(self.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(raw.encode()).hexdigest()


class IntegratorConfig(BaseModel):
    model_config = ConfigDict(frozen=True)
    min_step_s: float = Field(gt=0.0)
    max_step_s: float = Field(gt=0.0)
    abs_tolerance: float = Field(gt=0.0)
    rel_tolerance: float = Field(gt=0.0)

    @model_validator(mode="after")
    def validate_steps(self) -> IntegratorConfig:
        if self.max_step_s < self.min_step_s:
            raise ValueError("max_step_s must be greater than or equal to min_step_s")
        return self


class ConstraintConfig(BaseModel):
    model_config = ConfigDict(frozen=True)
    min_pair_distance_m: float = Field(gt=0.0)
    delta_a_bounds_m: tuple[float, float]
    delta_e_max: float = Field(gt=0.0)
    delta_i_max_rad: float = Field(gt=0.0)
    phase_corridor_rad: float = Field(gt=0.0)
    propellant_reserve_fraction: float = Field(ge=0.0, lt=1.0)


class MonteCarloConfig(BaseModel):
    model_config = ConfigDict(frozen=True)
    samples: int = Field(gt=0)
    workers: int = Field(gt=0)
    seed: int
    perturbation_sigmas: dict[str, float] = Field(default_factory=dict)


class Maneuver(BaseModel):
    model_config = ConfigDict(frozen=True)
    satellite_id: str
    time_s: float = Field(ge=0.0)
    dv_rtn_m_s: tuple[float, float, float]


class ManeuverPlan(BaseModel):
    model_config = ConfigDict(frozen=True)
    maneuvers: tuple[Maneuver, ...] = ()


class PropagationRequest(BaseModel):
    model_config = ConfigDict(frozen=True)
    scenario_id: str
    epoch: datetime
    frame: FrameName
    time_scale: TimeScaleName
    satellites: tuple[SatelliteSpec, ...]
    maneuvers: tuple[Maneuver, ...] = ()
    duration_s: float = Field(gt=0.0)
    output_step_s: float = Field(gt=0.0)
    force_model: ForceModelConfig
    integrator: IntegratorConfig
    seed: int


class PropagationResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    backend: str
    backend_version: str
    force_model_fingerprint: str
    backend_metadata: dict[str, str] = Field(default_factory=dict)
    times_s: tuple[float, ...]
    mean_orbits: dict[str, tuple[MeanOrbit, ...]]
    cartesian_states: dict[str, tuple[OsculatingState, ...]]


class StabilityMetrics(BaseModel):
    model_config = ConfigDict(frozen=True)
    pair_id: str
    secular_drift_delta_lambda_rad_s: float
    periodic_amplitude_delta_lambda_rad: float
    secular_drift_raan_rad_s: float
    eccentricity_vector_drift_rate_s: float
    inclination_vector_drift_rate_s: float
    minimum_pair_distance_m: float
    time_of_closest_approach_s: float
    ground_track_closure_error_m: float
    pdop: float | None = None


class OptimizationResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    success: bool
    algorithm: str
    x: tuple[float, ...]
    objective: float | None = None
    objectives: tuple[float, ...] = ()
    message: str = ""


class ExperimentRunManifest(BaseModel):
    model_config = ConfigDict(frozen=True)
    scenario_id: str
    run_id: str
    config_hash: str
    code_version: str
    force_model_fingerprint: str
    force_model_mode: ForceMode
    force_model: ForceModelConfig
    integrator: IntegratorConfig
    constraints: ConstraintConfig
    frame: FrameName
    time_scale: TimeScaleName
    mean_element_definitions: dict[str, MeanElementDefinition]
    backend: str
    backend_version: str
    backend_metadata: dict[str, str]
    epoch: datetime
    random_seed: int
    algorithm_versions: dict[str, str]


class ScenarioConfig(BaseModel):
    model_config = ConfigDict(frozen=True)
    scenario_id: str
    seed: int
    epoch: datetime
    frame: FrameName
    time_scale: TimeScaleName
    duration_s: float = Field(gt=0.0)
    output_step_s: float = Field(gt=0.0)
    orekit_sidecar_url: str | None = None
    force_model: ForceModelConfig
    integrator: IntegratorConfig
    constraints: ConstraintConfig
    monte_carlo: MonteCarloConfig
    constellation: ConstellationSpec
    maneuvers: tuple[Maneuver, ...] = ()
    navigation_sites: tuple[NavigationSiteConfig, ...] = ()

    @model_validator(mode="after")
    def validate_targets_and_sites(self) -> ScenarioConfig:
        known = {sat.satellite_id for sat in self.constellation.satellites}
        for maneuver in self.maneuvers:
            if maneuver.satellite_id not in known:
                raise ValueError(f"unknown maneuver satellite_id: {maneuver.satellite_id}")
            if maneuver.time_s > self.duration_s:
                raise ValueError("maneuver time_s must lie inside scenario duration")
        site_ids = [site.site_id for site in self.navigation_sites]
        if len(site_ids) != len(set(site_ids)):
            raise ValueError("navigation site_id values must be unique")
        return self

    def config_hash(self) -> str:
        payload = self.model_dump(mode="json")
        # Preserve historical hashes for scenarios that do not request geometry.
        if not self.navigation_sites:
            payload.pop("navigation_sites", None)
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(raw.encode()).hexdigest()
