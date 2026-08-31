from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from constellation_control.domain.digital_twin import SpacecraftOperationalState


class PropulsionCatalogEntry(BaseModel):
    model_config = ConfigDict(frozen=True)

    model_id: str = Field(min_length=1)
    system_type: str = Field(min_length=1)
    thrust_n: float | None = Field(default=None, gt=0.0)
    isp_s: float | None = Field(default=None, gt=0.0)
    propellant_types: tuple[str, ...] = ()
    authority_note: str | None = None

    @model_validator(mode="after")
    def validate_propellants(self) -> PropulsionCatalogEntry:
        values = [item.strip() for item in self.propellant_types]
        if any(not item for item in values):
            raise ValueError("propellant_types must not contain blank values")
        if len(values) != len(set(values)):
            raise ValueError("propellant_types must be unique")
        return self


class CorrectionCatalogEntry(BaseModel):
    model_config = ConfigDict(frozen=True)

    model_id: str = Field(min_length=1)
    system_type: str = Field(min_length=1)
    allowed_modes: tuple[Literal["ground", "autonomous", "hybrid"], ...] = ()
    authority_note: str | None = None

    @model_validator(mode="after")
    def validate_modes(self) -> CorrectionCatalogEntry:
        if len(self.allowed_modes) != len(set(self.allowed_modes)):
            raise ValueError("allowed_modes must be unique")
        return self


class SpacecraftSystemsCatalog(BaseModel):
    model_config = ConfigDict(frozen=True)

    propulsion: tuple[PropulsionCatalogEntry, ...] = ()
    correction: tuple[CorrectionCatalogEntry, ...] = ()

    @model_validator(mode="after")
    def validate_ids(self) -> SpacecraftSystemsCatalog:
        propulsion_ids = [item.model_id for item in self.propulsion]
        correction_ids = [item.model_id for item in self.correction]
        if len(propulsion_ids) != len(set(propulsion_ids)):
            raise ValueError("propulsion catalog model_id values must be unique")
        if len(correction_ids) != len(set(correction_ids)):
            raise ValueError("correction catalog model_id values must be unique")
        return self


class CatalogValidationFinding(BaseModel):
    model_config = ConfigDict(frozen=True)

    satellite_id: str
    system_kind: Literal["propulsion", "correction"]
    model_id: str | None
    valid: bool
    issues: tuple[str, ...] = ()


def _close(a: float, b: float) -> bool:
    return abs(a - b) <= max(1.0e-9, 1.0e-9 * max(abs(a), abs(b)))


def validate_operational_systems(
    states: tuple[SpacecraftOperationalState, ...], catalog: SpacecraftSystemsCatalog
) -> tuple[CatalogValidationFinding, ...]:
    propulsion_by_id = {item.model_id: item for item in catalog.propulsion}
    correction_by_id = {item.model_id: item for item in catalog.correction}
    findings: list[CatalogValidationFinding] = []

    for state in states:
        propulsion = state.propulsion
        if propulsion is not None:
            issues: list[str] = []
            if not propulsion.model_id:
                issues.append("propulsion.model_id is required for catalog validation")
                entry = None
            else:
                entry = propulsion_by_id.get(propulsion.model_id)
                if entry is None:
                    issues.append("propulsion model_id is absent from catalog")
            if entry is not None:
                if propulsion.system_type != entry.system_type:
                    issues.append("propulsion system_type does not match catalog")
                if propulsion.thrust_n is not None and entry.thrust_n is not None and not _close(propulsion.thrust_n, entry.thrust_n):
                    issues.append("propulsion thrust_n does not match catalog")
                if propulsion.isp_s is not None and entry.isp_s is not None and not _close(propulsion.isp_s, entry.isp_s):
                    issues.append("propulsion isp_s does not match catalog")
                if propulsion.propellant_type is not None and entry.propellant_types and propulsion.propellant_type not in entry.propellant_types:
                    issues.append("propellant_type is not allowed by catalog")
            findings.append(CatalogValidationFinding(
                satellite_id=state.satellite_id,
                system_kind="propulsion",
                model_id=propulsion.model_id,
                valid=not issues,
                issues=tuple(issues),
            ))

        correction = state.correction_system
        if correction is not None:
            issues = []
            model_id = correction.model_id
            if not model_id:
                issues.append("correction_system.model_id is required for catalog validation")
                entry_c = None
            else:
                entry_c = correction_by_id.get(model_id)
                if entry_c is None:
                    issues.append("correction model_id is absent from catalog")
            if entry_c is not None:
                if correction.system_type != entry_c.system_type:
                    issues.append("correction system_type does not match catalog")
                if correction.mode is not None and entry_c.allowed_modes and correction.mode not in entry_c.allowed_modes:
                    issues.append("correction mode is not allowed by catalog")
            findings.append(CatalogValidationFinding(
                satellite_id=state.satellite_id,
                system_kind="correction",
                model_id=model_id,
                valid=not issues,
                issues=tuple(issues),
            ))

    return tuple(findings)
