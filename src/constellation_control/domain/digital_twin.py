from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class PerturbationDistribution(StrEnum):
    GAUSSIAN = "gaussian"
    UNIFORM = "uniform"


class PerturbationScope(StrEnum):
    CONSTELLATION = "constellation"
    PLANE = "plane"
    GROUP = "group"
    SATELLITE = "satellite"


class PerturbationParameter(StrEnum):
    SEMI_MAJOR_AXIS = "semi_major_axis"
    ECCENTRICITY = "eccentricity"
    INCLINATION = "inclination"
    RAAN = "raan"
    ARGUMENT_OF_PERIGEE = "argument_of_perigee"
    MEAN_ANOMALY = "mean_anomaly"
    EPOCH_OFFSET = "epoch_offset"


PERTURBATION_PARAMETER_UNITS: dict[PerturbationParameter, str] = {
    PerturbationParameter.SEMI_MAJOR_AXIS: "m",
    PerturbationParameter.ECCENTRICITY: "1",
    PerturbationParameter.INCLINATION: "rad",
    PerturbationParameter.RAAN: "rad",
    PerturbationParameter.ARGUMENT_OF_PERIGEE: "rad",
    PerturbationParameter.MEAN_ANOMALY: "rad",
    PerturbationParameter.EPOCH_OFFSET: "s",
}


class PropulsionSystem(BaseModel):
    model_config = ConfigDict(frozen=True)
    system_type: str
    model_id: str | None = None
    thrust_n: float | None = Field(default=None, gt=0.0)
    isp_s: float | None = Field(default=None, gt=0.0)
    propellant_type: str | None = None


class CorrectionSystem(BaseModel):
    model_config = ConfigDict(frozen=True)
    system_type: str
    mode: Literal["ground", "autonomous", "hybrid"] | None = None


class SpacecraftOperationalState(BaseModel):
    model_config = ConfigDict(frozen=True)
    satellite_id: str
    spacecraft_model_id: str | None = None
    dry_mass_kg: float = Field(gt=0.0)
    current_propellant_mass_kg: float = Field(ge=0.0)
    propellant_capacity_kg: float | None = Field(default=None, ge=0.0)
    current_mass_kg: float | None = Field(default=None, gt=0.0)
    propulsion: PropulsionSystem | None = None
    correction_system: CorrectionSystem | None = None

    @model_validator(mode="after")
    def validate_mass_state(self) -> SpacecraftOperationalState:
        if self.propellant_capacity_kg is not None and self.current_propellant_mass_kg > self.propellant_capacity_kg:
            raise ValueError("current_propellant_mass_kg must not exceed propellant_capacity_kg")
        expected_mass = self.dry_mass_kg + self.current_propellant_mass_kg
        if self.current_mass_kg is not None and self.current_mass_kg < self.dry_mass_kg:
            raise ValueError("current_mass_kg must be greater than or equal to dry_mass_kg")
        if self.current_mass_kg is not None and abs(self.current_mass_kg - expected_mass) > 1e-6:
            raise ValueError("current_mass_kg must equal dry_mass_kg + current_propellant_mass_kg")
        return self

    @property
    def resolved_current_mass_kg(self) -> float:
        if self.current_mass_kg is not None:
            return self.current_mass_kg
        return self.dry_mass_kg + self.current_propellant_mass_kg


class SpacecraftGroup(BaseModel):
    model_config = ConfigDict(frozen=True)
    group_id: str
    satellite_ids: tuple[str, ...]

    @model_validator(mode="after")
    def validate_group(self) -> SpacecraftGroup:
        if not self.satellite_ids:
            raise ValueError("spacecraft group must contain at least one satellite")
        if len(self.satellite_ids) != len(set(self.satellite_ids)):
            raise ValueError("spacecraft group satellite_ids must be unique")
        return self


class PerturbationRule(BaseModel):
    model_config = ConfigDict(frozen=True)
    rule_id: str
    parameter: PerturbationParameter
    distribution: PerturbationDistribution
    scope: PerturbationScope
    target_ids: tuple[str, ...] = ()
    mean: float
    sigma: float | None = Field(default=None, ge=0.0)
    lower_bound: float | None = None
    upper_bound: float | None = None
    unit: str

    @model_validator(mode="after")
    def validate_distribution_parameters(self) -> PerturbationRule:
        expected_unit = PERTURBATION_PARAMETER_UNITS[self.parameter]
        if self.unit != expected_unit:
            raise ValueError(
                f"perturbation parameter {self.parameter.value} requires unit {expected_unit!r}, got {self.unit!r}"
            )
        if self.scope == PerturbationScope.CONSTELLATION and self.target_ids:
            raise ValueError("constellation perturbation scope must not define target_ids")
        if self.scope != PerturbationScope.CONSTELLATION and not self.target_ids:
            raise ValueError("non-constellation perturbation scope requires target_ids")
        if self.distribution == PerturbationDistribution.GAUSSIAN:
            if self.sigma is None:
                raise ValueError("gaussian perturbation requires sigma")
            if self.lower_bound is not None or self.upper_bound is not None:
                raise ValueError("gaussian perturbation must not define uniform bounds")
        if self.distribution == PerturbationDistribution.UNIFORM:
            if self.lower_bound is None or self.upper_bound is None:
                raise ValueError("uniform perturbation requires lower_bound and upper_bound")
            if self.lower_bound > self.upper_bound:
                raise ValueError("lower_bound must not exceed upper_bound")
            if self.sigma is not None:
                raise ValueError("uniform perturbation must not define sigma")
        return self


class AppliedPerturbation(BaseModel):
    model_config = ConfigDict(frozen=True)
    rule_id: str
    satellite_id: str
    parameter: PerturbationParameter
    sampled_delta: float
    unit: str

    @model_validator(mode="after")
    def validate_unit(self) -> AppliedPerturbation:
        expected_unit = PERTURBATION_PARAMETER_UNITS[self.parameter]
        if self.unit != expected_unit:
            raise ValueError(
                f"applied perturbation parameter {self.parameter.value} requires unit {expected_unit!r}, got {self.unit!r}"
            )
        return self


class ScenarioLineage(BaseModel):
    model_config = ConfigDict(frozen=True)
    parent_scenario_id: str
    parent_config_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    transformation: Literal[
        "perturbation",
        "import",
        "walker_generation",
        "manual_edit",
        "osculating_import",
        "propagated_state",
    ]
    random_seed: int | None = None


class DigitalTwinConfig(BaseModel):
    model_config = ConfigDict(frozen=True)
    spacecraft_states: tuple[SpacecraftOperationalState, ...] = ()
    groups: tuple[SpacecraftGroup, ...] = ()
    perturbations: tuple[PerturbationRule, ...] = ()
    applied_perturbations: tuple[AppliedPerturbation, ...] = ()
    lineage: ScenarioLineage | None = None

    @model_validator(mode="after")
    def validate_local_uniqueness(self) -> DigitalTwinConfig:
        state_ids = [state.satellite_id for state in self.spacecraft_states]
        if len(state_ids) != len(set(state_ids)):
            raise ValueError("spacecraft state satellite_id values must be unique")
        group_ids = [group.group_id for group in self.groups]
        if len(group_ids) != len(set(group_ids)):
            raise ValueError("spacecraft group_id values must be unique")
        rule_ids = [rule.rule_id for rule in self.perturbations]
        if len(rule_ids) != len(set(rule_ids)):
            raise ValueError("perturbation rule_id values must be unique")
        return self
