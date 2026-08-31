from __future__ import annotations

from constellation_control.domain.digital_twin import (
    CorrectionSystem,
    PropulsionSystem,
    SpacecraftOperationalState,
)
from constellation_control.domain.spacecraft_catalog import (
    CorrectionCatalogEntry,
    PropulsionCatalogEntry,
    SpacecraftSystemsCatalog,
    validate_operational_systems,
)


def _state(*, isp_s: float = 220.0, mode: str = "hybrid") -> SpacecraftOperationalState:
    return SpacecraftOperationalState(
        satellite_id="SAT-1",
        dry_mass_kg=500.0,
        current_propellant_mass_kg=50.0,
        propulsion=PropulsionSystem(
            system_type="chemical",
            model_id="ENG-A",
            thrust_n=10.0,
            isp_s=isp_s,
            propellant_type="hydrazine",
        ),
        correction_system=CorrectionSystem(system_type="orbit-control", mode=mode),
    )


def _catalog() -> SpacecraftSystemsCatalog:
    return SpacecraftSystemsCatalog(
        propulsion=(PropulsionCatalogEntry(
            model_id="ENG-A",
            system_type="chemical",
            thrust_n=10.0,
            isp_s=220.0,
            propellant_types=("hydrazine",),
        ),),
        correction=(CorrectionCatalogEntry(
            model_id="CORR-A",
            system_type="orbit-control",
            allowed_modes=("ground", "hybrid"),
        ),),
    )


def test_catalog_validates_declared_operational_systems_without_mutating_state() -> None:
    state = _state()
    findings = validate_operational_systems((state,), _catalog())
    assert len(findings) == 2
    assert all(item.valid for item in findings)
    assert state.propulsion is not None
    assert state.propulsion.isp_s == 220.0
    assert state.current_propellant_mass_kg == 50.0


def test_catalog_fails_closed_on_isp_mismatch() -> None:
    findings = validate_operational_systems((_state(isp_s=210.0),), _catalog())
    propulsion = next(item for item in findings if item.system_kind == "propulsion")
    assert propulsion.valid is False
    assert "propulsion isp_s does not match catalog" in propulsion.issues


def test_catalog_fails_closed_on_disallowed_correction_mode() -> None:
    findings = validate_operational_systems((_state(mode="autonomous"),), _catalog())
    correction = next(item for item in findings if item.system_kind == "correction")
    assert correction.valid is False
    assert "correction mode is not allowed by catalog" in correction.issues
