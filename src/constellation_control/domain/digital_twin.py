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
    parameter: str
    distribution: PerturbationDistribution
    scope: PerturbationScope
    target_ids: tuple[str, ...] = ()
    mean: float = 0.0
    sigma: float | None = Field(default=None, ge=0.0)
    lower_bound: float | None = None
    upper_bound: float | None = None
    unit: str

    @model_validator(mode="after")
    def validate_distribution_parameters(self) -> PerturbationRule:
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


class ScenarioLineage(BaseModel):
    model_config = ConfigDict(frozen=True)
    parent_scenario_id: str
    parent_config_hash: str
    transformation: Literal["perturbation", "import", "walker_generation", "manual_edit"]
    random_seed: int | None = None


class DigitalTwinConfig(BaseModel):
    model_config = ConfigDict(frozen=True)
    spacecraft_states: tuple[SpacecraftOperationalState, ...] = ()
    groups: tuple[SpacecraftGroup, ...] = ()
    perturbations: tuple[PerturbationRule, ...] = ()
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
