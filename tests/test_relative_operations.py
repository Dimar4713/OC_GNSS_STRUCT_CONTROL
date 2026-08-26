import math

import numpy as np
import pytest

from constellation_control.analysis.relative_operations import (
    angular_rate_engineering_units,
    analyze_relative_operations,
    mean_phase_rad,
    relative_mean_phase_series_rad,
)
from constellation_control.domain.models import MeanElementDefinition, MeanOrbit

DEFINITION = MeanElementDefinition(
    theory="engineer-feedback-regression",
    force_model_fingerprint="test",
)
A_M = 25508039.165499


def _orbit(ix: float, iy: float, lambda_rad: float, *, a_m: float = A_M) -> MeanOrbit:
    return MeanOrbit(
        a_m=a_m,
        ex=0.0,
        ey=0.0,
        ix=ix,
        iy=iy,
        lambda_rad=lambda_rad,
        definition=DEFINITION,
    )


def test_mean_phase_recovers_engineer_feedback_15_degree_interplane_offset() -> None:
    p1 = _orbit(-0.6128512204797385, -0.16478784655405554, 2.8463677578328666)
    p2 = _orbit(0.44912582134044515, -0.44836107036706313, -1.080646437586683)

    direct_lambda_deg = math.degrees(p2.lambda_rad - p1.lambda_rad) % 360.0
    delta_u_deg = math.degrees(mean_phase_rad(p2) - mean_phase_rad(p1)) % 360.0

    assert direct_lambda_deg == pytest.approx(134.9986605145, abs=1e-9)
    assert delta_u_deg == pytest.approx(14.9999704025, abs=1e-9)


def test_relative_mean_phase_unwraps_through_plus_minus_pi_boundary() -> None:
    reference = [_orbit(1.0, 0.0, 0.0), _orbit(1.0, 0.0, 0.0)]
    deputy = [
        _orbit(1.0, 0.0, math.radians(179.0)),
        _orbit(1.0, 0.0, math.radians(-179.0)),
    ]

    delta_u = relative_mean_phase_series_rad(reference, deputy)

    assert math.degrees(delta_u[0]) == pytest.approx(179.0)
    assert math.degrees(delta_u[1]) == pytest.approx(181.0)


def test_engineer_reported_drift_has_explicit_day_and_julian_year_units() -> None:
    units = angular_rate_engineering_units(-1.3969570983e-8)

    assert units.rad_s == pytest.approx(-1.3969570983e-8)
    assert units.deg_day == pytest.approx(-0.069154, abs=1e-6)
    assert units.deg_julian_year == pytest.approx(-25.2585, abs=2e-3)


def test_relative_operations_reports_mean_phase_and_along_track_arc_proxy() -> None:
    times = np.asarray([0.0, 86400.0, 2.0 * 86400.0])
    reference = [_orbit(1.0, 0.0, 0.0) for _ in times]
    deputy = [
        _orbit(1.0, 0.0, math.radians(value))
        for value in (1.0, 1.5, 2.0)
    ]

    diagnostics, delta_u, along_track = analyze_relative_operations(times, reference, deputy)

    assert np.rad2deg(delta_u).tolist() == pytest.approx([1.0, 1.5, 2.0])
    assert along_track == pytest.approx(A_M * delta_u)
    assert diagnostics.initial_delta_u_deg == pytest.approx(1.0)
    assert diagnostics.final_delta_u_deg == pytest.approx(2.0)
    assert diagnostics.secular_delta_u_rate_deg_day == pytest.approx(0.5)
    expected_rate = A_M * math.radians(0.5) / 86400.0
    assert diagnostics.secular_along_track_proxy_rate_m_s == pytest.approx(expected_rate)
