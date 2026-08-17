from math import isclose, pi

import numpy as np
from hypothesis import given, strategies as st

from constellation_control.adapters.synthetic.propagator import SyntheticMeanPropagator
from constellation_control.analysis.drift import harmonic_regression
from constellation_control.analysis.fuel import propellant_used_kg
from constellation_control.control.controllers import DeadbandCandidate, DeadbandController
from constellation_control.domain.models import (
    ForceModelConfig,
    ForceMode,
    IntegratorConfig,
    MeanElementDefinition,
    MeanOrbit,
    PropagationRequest,
    SatelliteSpec,
    SpacecraftModel,
)
from constellation_control.dynamics.j2 import first_order_j2_rates, mean_motion
from constellation_control.dynamics.orbits import (
    apply_tangential_impulse,
    mean_to_cartesian,
    mean_to_classical,
    semi_major_axis_from_state,
)
from constellation_control.mean_elements.roe import damico_roe


def force(j2: float = 0.00108262668) -> ForceModelConfig:
    return ForceModelConfig(
        mode=ForceMode.SCREENING,
        mu_m3_s2=3.986004418e14,
        reference_radius_m=6378137.0,
        j2=j2,
        earth_rotation_rate_rad_s=7.292115e-5,
        gravity_degree=2,
        gravity_order=0,
    )


def orbit(lambda_rad: float = 0.0, a_m: float = 26_560_000.0) -> MeanOrbit:
    return MeanOrbit(
        a_m=a_m,
        ex=0.001,
        ey=0.0,
        ix=0.2,
        iy=0.0,
        lambda_rad=lambda_rad,
        definition=MeanElementDefinition(theory="test", force_model_fingerprint="test"),
    )


def spacecraft() -> SpacecraftModel:
    return SpacecraftModel(
        dry_mass_kg=500.0,
        propellant_mass_kg=50.0,
        isp_s=220.0,
        area_m2=8.0,
        cr=1.3,
    )


def test_two_body_mean_motion_matches_kepler() -> None:
    elements = mean_to_classical(orbit())
    rates = first_order_j2_rates(elements, force(j2=0.0))
    assert rates.raan_rad_s == 0.0
    assert rates.argp_rad_s == 0.0
    assert isclose(
        rates.mean_anomaly_rad_s,
        mean_motion(elements.a_m, force().mu_m3_s2),
        rel_tol=1e-15,
    )


def test_identical_mean_orbits_with_phase_offset_have_zero_relative_secular_drift() -> None:
    ref = SatelliteSpec(
        satellite_id="R",
        plane_id="P",
        role="reference",
        mean_orbit=orbit(),
        spacecraft=spacecraft(),
    )
    dep = SatelliteSpec(
        satellite_id="D",
        plane_id="P",
        role="additional",
        reference_id="R",
        mean_orbit=orbit(pi / 4),
        spacecraft=spacecraft(),
    )
    request = PropagationRequest(
        scenario_id="test",
        satellites=(ref, dep),
        duration_s=86400.0,
        output_step_s=600.0,
        force_model=force(),
        integrator=IntegratorConfig(
            min_step_s=0.1,
            max_step_s=60.0,
            abs_tolerance=1e-9,
            rel_tolerance=1e-12,
        ),
        seed=1,
    )
    result = SyntheticMeanPropagator().propagate(request)
    phase = np.unwrap(
        np.array(
            [
                damico_roe(reference_orbit, deputy_orbit).delta_lambda_rad
                for reference_orbit, deputy_orbit in zip(
                    result.mean_orbits["R"],
                    result.mean_orbits["D"],
                    strict=True,
                )
            ]
        )
    )
    assert np.ptp(phase) < 1e-10


def test_harmonic_regression_recovers_secular_drift() -> None:
    t = np.linspace(0.0, 10000.0, 400)
    frequency = 2.0 * pi / 1000.0
    drift = 2.5e-6
    y = 0.3 + drift * t + 0.02 * np.sin(frequency * t) - 0.01 * np.cos(frequency * t)
    fit = harmonic_regression(t, y, (frequency,))
    assert isclose(fit.secular_drift_rad_s, drift, rel_tol=1e-9, abs_tol=1e-12)


def test_positive_tangential_impulse_increases_a_and_reduces_mean_motion() -> None:
    elements = mean_to_classical(orbit())
    r_m, v_m_s = mean_to_cartesian(elements, force().mu_m3_s2)
    new_v = apply_tangential_impulse(r_m, v_m_s, 0.1)
    new_a = semi_major_axis_from_state(r_m, new_v, force().mu_m3_s2)
    assert new_a > elements.a_m
    assert mean_motion(new_a, force().mu_m3_s2) < mean_motion(
        elements.a_m,
        force().mu_m3_s2,
    )


def test_deadband_rejects_unsafe_candidate() -> None:
    controller = DeadbandController(phase_limit_rad=0.1, min_distance_m=1000.0)
    baseline = np.array([0.0, 0.05, 0.2])
    distance = np.array([5000.0, 5000.0, 5000.0])
    unsafe = DeadbandCandidate(
        (0.0, 0.01, 0.0),
        np.array([0.0, 0.05, 0.08]),
        np.array([5000.0, 900.0, 5000.0]),
    )
    safe = DeadbandCandidate(
        (0.0, 0.02, 0.0),
        np.array([0.0, 0.04, 0.08]),
        np.array([5000.0, 5000.0, 5000.0]),
    )
    plan = controller.plan("D", baseline, distance, (unsafe, safe))
    assert plan.maneuvers[0].dv_rtn_m_s == safe.dv_rtn_m_s


@given(delta_v=st.floats(min_value=0.0, max_value=500.0, allow_nan=False, allow_infinity=False))
def test_fuel_equation_bounds(delta_v: float) -> None:
    used = propellant_used_kg(550.0, delta_v, 220.0)
    assert 0.0 <= used < 550.0
