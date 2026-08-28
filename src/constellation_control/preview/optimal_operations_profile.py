from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, model_validator

from constellation_control.application.run import load_scenario
from constellation_control.control.execution import MPCExecutionPolicy
from constellation_control.domain.models import ForceMode, ScenarioConfig
from constellation_control.optimization.operational_policy_search import OperationalPolicySearchConfig
from constellation_control.optimization.operations import ObjectiveDirection, OperationalStudyIdentity

PREVIEW_OPTIMAL_OPERATIONS_PROFILE_SCHEMA = "preview-optimal-operations-study-profile-v1"


def _identity(payload: object) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def scenario_integrator_identity(scenario: ScenarioConfig) -> str:
    return _identity(scenario.integrator.model_dump(mode="json"))


def scenario_constraints_identity(scenario: ScenarioConfig) -> str:
    return _identity(scenario.constraints.model_dump(mode="json"))


class PreviewExecutionPolicyProfile(BaseModel):
    model_config = ConfigDict(frozen=True)

    max_abs_impulse_rtn_m_s: tuple[float, float, float]
    min_impulse_bit_m_s: float
    trust_tolerances_roe: tuple[float, float, float, float, float, float]
    target_roe: tuple[float, float, float, float, float, float]
    w_tracking: float
    w_max: float

    @model_validator(mode="after")
    def validate_backend_policy(self) -> PreviewExecutionPolicyProfile:
        self.backend_policy()
        return self

    def backend_policy(self) -> MPCExecutionPolicy:
        return MPCExecutionPolicy(
            max_abs_impulse_rtn_m_s=self.max_abs_impulse_rtn_m_s,
            min_impulse_bit_m_s=self.min_impulse_bit_m_s,
            trust_tolerances_roe=self.trust_tolerances_roe,
            target_roe=self.target_roe,
            w_tracking=self.w_tracking,
            w_max=self.w_max,
        )

    def identity(self) -> str:
        return _identity(self.model_dump(mode="json"))


class PreviewOperationalPolicySearchProfile(BaseModel):
    model_config = ConfigDict(frozen=True)

    trigger_fraction_bounds: tuple[float, float]
    target_fraction_bounds: tuple[float, float]
    lhs_samples: int
    local_seeds: int
    local_method: str
    nsga_population: int
    nsga_generations: int
    seed: int

    @model_validator(mode="after")
    def validate_backend_search(self) -> PreviewOperationalPolicySearchProfile:
        self.backend_config()
        return self

    def backend_config(self) -> OperationalPolicySearchConfig:
        return OperationalPolicySearchConfig(
            trigger_fraction_bounds=self.trigger_fraction_bounds,
            target_fraction_bounds=self.target_fraction_bounds,
            lhs_samples=self.lhs_samples,
            local_seeds=self.local_seeds,
            local_method=self.local_method,
            nsga_population=self.nsga_population,
            nsga_generations=self.nsga_generations,
            seed=self.seed,
        )


class PreviewObjectiveDefinition(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str = Field(min_length=1)
    unit: str = Field(min_length=1)
    direction: ObjectiveDirection


class PreviewHardConstraintDefinition(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str = Field(min_length=1)
    unit: str = Field(min_length=1)


class PreviewRobustnessPolicy(BaseModel):
    model_config = ConfigDict(frozen=True)

    enabled: bool
    recommendation_required: bool
    campaign_id: str | None
    uncertainty_model_id: str | None
    sampling_model_sha256: str | None

    @model_validator(mode="after")
    def validate_explicit_policy(self) -> PreviewRobustnessPolicy:
        if self.enabled:
            if not self.campaign_id or not self.uncertainty_model_id:
                raise ValueError("enabled robustness requires explicit campaign_id and uncertainty_model_id")
            if self.sampling_model_sha256 is None or len(self.sampling_model_sha256) != 64:
                raise ValueError("enabled robustness requires explicit 64-character sampling_model_sha256")
            try:
                int(self.sampling_model_sha256, 16)
            except ValueError as exc:
                raise ValueError("sampling_model_sha256 must be lowercase hexadecimal") from exc
            if self.sampling_model_sha256.lower() != self.sampling_model_sha256:
                raise ValueError("sampling_model_sha256 must be lowercase hexadecimal")
        else:
            if self.recommendation_required:
                raise ValueError("disabled robustness cannot be required for recommendation")
            if any(value is not None for value in (self.campaign_id, self.uncertainty_model_id, self.sampling_model_sha256)):
                raise ValueError("disabled robustness must explicitly carry null campaign/model evidence")
        return self


class PreviewOptimalOperationsStudyProfile(BaseModel):
    model_config = ConfigDict(frozen=True)

    schema_version: str = PREVIEW_OPTIMAL_OPERATIONS_PROFILE_SCHEMA
    study_id: str = Field(min_length=1)
    scenario_name: str = Field(min_length=1)
    controlled_deputy_id: str = Field(min_length=1)
    seed: int
    campaign_horizon_s: float = Field(gt=0.0)
    coast_horizon_s: float = Field(gt=0.0)
    coast_output_step_s: float = Field(gt=0.0)
    max_corrections: int = Field(gt=0)
    authority_times_s: tuple[float, ...]
    maneuver_windows: tuple[bool, ...]
    execution_policy: PreviewExecutionPolicyProfile
    uncertainty_model_id: str = Field(min_length=1)
    search: PreviewOperationalPolicySearchProfile
    objectives: tuple[PreviewObjectiveDefinition, ...]
    hard_constraints: tuple[PreviewHardConstraintDefinition, ...]
    robustness: PreviewRobustnessPolicy
    expected_force_model_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    expected_frame: str = Field(min_length=1)
    expected_time_scale: str = Field(min_length=1)
    expected_integrator_identity: str = Field(pattern=r"^[0-9a-f]{64}$")
    expected_constraints_identity: str = Field(pattern=r"^[0-9a-f]{64}$")
    expected_execution_policy_identity: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_profile(self) -> PreviewOptimalOperationsStudyProfile:
        if self.schema_version != PREVIEW_OPTIMAL_OPERATIONS_PROFILE_SCHEMA:
            raise ValueError(f"unsupported optimal-operations profile schema: {self.schema_version}")
        if len(self.authority_times_s) < 2 or self.authority_times_s[0] != 0.0:
            raise ValueError("authority_times_s must start at zero and contain at least two samples")
        times = np.asarray(self.authority_times_s, dtype=float)
        intervals = np.diff(times)
        if np.any(~np.isfinite(times)) or np.any(intervals <= 0.0):
            raise ValueError("authority_times_s must be finite and strictly increasing")
        if len(self.maneuver_windows) != len(self.authority_times_s) - 1:
            raise ValueError("maneuver_windows must have one entry per authority interval")
        objective_keys = [(item.name, item.unit, item.direction) for item in self.objectives]
        if not objective_keys or len(objective_keys) != len(set(objective_keys)):
            raise ValueError("profile requires unique explicit objective definitions")
        constraint_keys = [(item.name, item.unit) for item in self.hard_constraints]
        if not constraint_keys or len(constraint_keys) != len(set(constraint_keys)):
            raise ValueError("profile requires unique explicit hard-constraint definitions")
        if self.expected_execution_policy_identity != self.execution_policy.identity():
            raise ValueError("execution-policy identity does not match explicit execution policy payload")
        return self


class PreviewOptimalOperationsPreflight(BaseModel):
    model_config = ConfigDict(frozen=True)

    schema_version: str
    study_id: str
    scenario_name: str
    controlled_deputy_id: str
    reference_id: str
    scenario_config_hash: str
    max_corrections: int
    identity: OperationalStudyIdentity
    search_config: dict[str, object]
    objective_definitions: tuple[PreviewObjectiveDefinition, ...]
    hard_constraint_definitions: tuple[PreviewHardConstraintDefinition, ...]
    robustness_enabled: bool
    robustness_recommendation_required: bool
    robustness_campaign_id: str | None
    robustness_uncertainty_model_id: str | None
    robustness_sampling_model_sha256: str | None
    preflight_sha256: str


def _preflight_digest(payload: dict[str, object]) -> str:
    return _identity(payload)


def preflight_optimal_operations_study(
    scenario_path: Path,
    profile: PreviewOptimalOperationsStudyProfile,
) -> PreviewOptimalOperationsPreflight:
    """Validate and reduce a Preview 0.2 study profile without running any physics or optimization."""

    scenario = load_scenario(scenario_path)
    if scenario_path.name != profile.scenario_name:
        raise ValueError("scenario file name does not match optimal-operations profile")
    if scenario.force_model.mode != ForceMode.VALIDATION:
        raise ValueError("optimal-operations study requires VALIDATION force mode")
    if not scenario.orekit_sidecar_url:
        raise ValueError("optimal-operations study requires configured numerical Orekit authority")

    by_id = {sat.satellite_id: sat for sat in scenario.constellation.satellites}
    deputy = by_id.get(profile.controlled_deputy_id)
    if deputy is None or deputy.role != "additional":
        raise ValueError("controlled_deputy_id must name an additional satellite in ScenarioConfig")
    if deputy.reference_id is None or deputy.reference_id not in by_id:
        raise ValueError("controlled deputy requires a valid reference_id in ScenarioConfig")
    reference_id = deputy.reference_id

    actual_force = scenario.force_model.fingerprint()
    actual_integrator = scenario_integrator_identity(scenario)
    actual_constraints = scenario_constraints_identity(scenario)
    actual_execution = profile.execution_policy.identity()
    checks = (
        ("force-model fingerprint", profile.expected_force_model_fingerprint, actual_force),
        ("frame", profile.expected_frame, scenario.frame.value),
        ("time scale", profile.expected_time_scale, scenario.time_scale.value),
        ("integrator identity", profile.expected_integrator_identity, actual_integrator),
        ("constraints identity", profile.expected_constraints_identity, actual_constraints),
        ("execution-policy identity", profile.expected_execution_policy_identity, actual_execution),
    )
    for label, expected, actual in checks:
        if expected != actual:
            raise ValueError(f"optimal-operations {label} mismatch: expected {expected}, got {actual}")

    identity = OperationalStudyIdentity(
        scenario_id=scenario.scenario_id,
        initial_epoch_iso=scenario.epoch.isoformat(),
        seed=profile.seed,
        force_model_fingerprint=actual_force,
        frame=scenario.frame.value,
        time_scale=scenario.time_scale.value,
        integrator_identity=actual_integrator,
        constraints_identity=actual_constraints,
        execution_policy_identity=actual_execution,
        campaign_horizon_s=profile.campaign_horizon_s,
        coast_horizon_s=profile.coast_horizon_s,
        coast_output_step_s=profile.coast_output_step_s,
        authority_times_s=profile.authority_times_s,
        maneuver_windows=profile.maneuver_windows,
        uncertainty_model_id=profile.uncertainty_model_id,
    )
    search_payload = profile.search.backend_config().model_dump(mode="json")
    evidence: dict[str, object] = {
        "schema_version": profile.schema_version,
        "study_id": profile.study_id,
        "scenario_name": profile.scenario_name,
        "controlled_deputy_id": profile.controlled_deputy_id,
        "reference_id": reference_id,
        "scenario_config_hash": scenario.config_hash(),
        "max_corrections": profile.max_corrections,
        "identity": identity.model_dump(mode="json"),
        "search_config": search_payload,
        "objective_definitions": [item.model_dump(mode="json") for item in profile.objectives],
        "hard_constraint_definitions": [item.model_dump(mode="json") for item in profile.hard_constraints],
        "robustness": profile.robustness.model_dump(mode="json"),
    }
    return PreviewOptimalOperationsPreflight(
        schema_version=profile.schema_version,
        study_id=profile.study_id,
        scenario_name=profile.scenario_name,
        controlled_deputy_id=profile.controlled_deputy_id,
        reference_id=reference_id,
        scenario_config_hash=scenario.config_hash(),
        max_corrections=profile.max_corrections,
        identity=identity,
        search_config=search_payload,
        objective_definitions=profile.objectives,
        hard_constraint_definitions=profile.hard_constraints,
        robustness_enabled=profile.robustness.enabled,
        robustness_recommendation_required=profile.robustness.recommendation_required,
        robustness_campaign_id=profile.robustness.campaign_id,
        robustness_uncertainty_model_id=profile.robustness.uncertainty_model_id,
        robustness_sampling_model_sha256=profile.robustness.sampling_model_sha256,
        preflight_sha256=_preflight_digest(evidence),
    )
