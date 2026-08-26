from __future__ import annotations

from pathlib import Path

import pytest

from constellation_control.application.run import load_scenario
from constellation_control.control.phase_target import (
    delta_u_from_damico_roe,
    roe_target_for_delta_u,
)
from constellation_control.mean_elements.roe import RelativeOrbitalElements


def _reference():
    scenario = load_scenario(Path(__file__).parents[1] / "scenarios" / "mvp_45deg.yaml")
    return scenario.constellation.satellites[0].mean_orbit


def test_phase_target_mapping_preserves_non_phase_roe_coordinates() -> None:
    reference = _reference()
    current = RelativeOrbitalElements(
        delta_a=1.5e-4,
        delta_lambda_rad=0.35,
        delta_ex=2.0e-4,
        delta_ey=-3.0e-4,
        delta_ix=4.0e-4,
        delta_iy=0.02,
    )

    target = roe_target_for_delta_u(reference, current, 0.1)

    assert target.delta_a == current.delta_a
    assert target.delta_ex == current.delta_ex
    assert target.delta_ey == current.delta_ey
    assert target.delta_ix == current.delta_ix
    assert target.delta_iy == current.delta_iy
    assert target.delta_lambda_rad != pytest.approx(0.1)
    assert delta_u_from_damico_roe(reference, target) == pytest.approx(0.1)


def test_nonzero_nodal_offset_proves_delta_u_is_not_damico_delta_lambda() -> None:
    reference = _reference()
    relative = RelativeOrbitalElements(
        delta_a=0.0,
        delta_lambda_rad=0.3,
        delta_ex=0.0,
        delta_ey=0.0,
        delta_ix=0.0,
        delta_iy=0.04,
    )

    recovered_delta_u = delta_u_from_damico_roe(reference, relative)

    assert recovered_delta_u != pytest.approx(relative.delta_lambda_rad)
    rebuilt = roe_target_for_delta_u(reference, relative, recovered_delta_u)
    assert rebuilt.delta_lambda_rad == pytest.approx(relative.delta_lambda_rad)


@pytest.mark.parametrize("target_delta_u", (-0.9, -0.1, 0.0, 0.1, 0.9))
def test_delta_u_to_roe_round_trip(target_delta_u: float) -> None:
    reference = _reference()
    current = RelativeOrbitalElements(
        delta_a=-1.0e-4,
        delta_lambda_rad=-0.2,
        delta_ex=1.0e-4,
        delta_ey=2.0e-4,
        delta_ix=-3.0e-4,
        delta_iy=-0.03,
    )

    target = roe_target_for_delta_u(reference, current, target_delta_u)
    recovered = delta_u_from_damico_roe(reference, target)

    assert recovered == pytest.approx(target_delta_u)


def test_phase_target_mapping_fails_closed_near_equatorial_inclination() -> None:
    reference = _reference().model_copy(update={"ix": 0.0, "iy": 0.0})
    current = RelativeOrbitalElements(
        delta_a=0.0,
        delta_lambda_rad=0.1,
        delta_ex=0.0,
        delta_ey=0.0,
        delta_ix=0.0,
        delta_iy=0.01,
    )

    with pytest.raises(ValueError, match="ill-conditioned near equatorial inclination"):
        delta_u_from_damico_roe(reference, current)
    with pytest.raises(ValueError, match="ill-conditioned near equatorial inclination"):
        roe_target_for_delta_u(reference, current, 0.0)


def test_phase_target_rejects_non_finite_policy_target() -> None:
    reference = _reference()
    current = RelativeOrbitalElements(0.0, 0.0, 0.0, 0.0, 0.0, 0.0)

    with pytest.raises(ValueError, match="target_delta_u_rad must be finite"):
        roe_target_for_delta_u(reference, current, float("nan"))
