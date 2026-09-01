from __future__ import annotations

import math
import shutil
from pathlib import Path

import pytest
from pydantic import ValidationError

from constellation_control.dynamics.j2 import first_order_j2_rates
from constellation_control.dynamics.orbits import ClassicalElements
from constellation_control.preview.constellation_editor import GravityModelEditRequest, apply_gravity_model_edit
from constellation_control.application.run import load_scenario


def _copy_scenario(tmp_path: Path, name: str) -> str:
    target = tmp_path / name
    shutil.copy(Path("scenarios") / name, target)
    return target.name


def test_gravity_request_accepts_full_32x32_range_and_rejects_invalid_shapes() -> None:
    request = GravityModelEditRequest(
        source_scenario_name="source.yaml",
        gravity_degree=32,
        gravity_order=32,
        target_scenario_name="target.yaml",
        new_scenario_id="target",
    )
    assert (request.gravity_degree, request.gravity_order) == (32, 32)

    with pytest.raises(ValidationError):
        GravityModelEditRequest(
            source_scenario_name="source.yaml",
            gravity_degree=33,
            gravity_order=0,
            target_scenario_name="target.yaml",
            new_scenario_id="target",
        )
    with pytest.raises(ValidationError):
        GravityModelEditRequest(
            source_scenario_name="source.yaml",
            gravity_degree=8,
            gravity_order=9,
            target_scenario_name="target.yaml",
            new_scenario_id="target",
        )


def test_validation_scenario_can_create_32x32_variant_with_new_fingerprint(tmp_path: Path) -> None:
    source_name = _copy_scenario(tmp_path, "orekit_validation_smoke.yaml")
    result = apply_gravity_model_edit(
        tmp_path,
        GravityModelEditRequest(
            source_scenario_name=source_name,
            gravity_degree=32,
            gravity_order=32,
            target_scenario_name="gravity-32x32.yaml",
            new_scenario_id="gravity-32x32",
        ),
    )

    child = load_scenario(tmp_path / "gravity-32x32.yaml")
    assert child.force_model.gravity_degree == 32
    assert child.force_model.gravity_order == 32
    assert result["force_model_fingerprint"] == child.force_model.fingerprint()
    assert all(
        sat.mean_orbit.definition.force_model_fingerprint == child.force_model.fingerprint()
        for sat in child.constellation.satellites
    )


def test_kepler_variant_can_disable_all_non_gravity_perturbations(tmp_path: Path) -> None:
    source_name = _copy_scenario(tmp_path, "orekit_validation_smoke.yaml")
    apply_gravity_model_edit(
        tmp_path,
        GravityModelEditRequest(
            source_scenario_name=source_name,
            gravity_degree=0,
            gravity_order=0,
            non_gravity_mode="off",
            target_scenario_name="kepler.yaml",
            new_scenario_id="kepler",
        ),
    )

    child = load_scenario(tmp_path / "kepler.yaml")
    force = child.force_model
    assert (force.gravity_degree, force.gravity_order) == (0, 0)
    assert not force.moon
    assert not force.sun
    assert not force.srp
    assert not force.tides
    assert not force.relativity


def test_screening_rejects_harmonics_above_j2(tmp_path: Path) -> None:
    source_name = _copy_scenario(tmp_path, "design_pipeline_screening_smoke.yaml")
    with pytest.raises(ValueError, match="SCREENING backend supports only"):
        apply_gravity_model_edit(
            tmp_path,
            GravityModelEditRequest(
                source_scenario_name=source_name,
                gravity_degree=4,
                gravity_order=4,
                target_scenario_name="invalid-screening.yaml",
                new_scenario_id="invalid-screening",
            ),
        )


def test_degree_zero_screening_rates_are_true_kepler_even_if_j2_constant_is_nonzero() -> None:
    source = load_scenario(Path("scenarios/design_pipeline_screening_smoke.yaml"))
    force = source.force_model.model_copy(update={"gravity_degree": 0, "gravity_order": 0})
    elements = ClassicalElements(
        a_m=25_500_000.0,
        e=0.001,
        i_rad=math.radians(64.8),
        raan_rad=0.0,
        argp_rad=0.0,
        mean_anomaly_rad=0.0,
    )
    rates = first_order_j2_rates(elements, force)
    assert rates.raan_rad_s == 0.0
    assert rates.argp_rad_s == 0.0
    assert rates.mean_anomaly_rad_s > 0.0
