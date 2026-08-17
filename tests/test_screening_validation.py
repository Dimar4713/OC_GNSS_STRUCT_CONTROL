from math import isclose, pi
from pathlib import Path

import numpy as np

from constellation_control.adapters.synthetic.propagator import SyntheticMeanPropagator
from constellation_control.analysis.drift import linear_rate
from constellation_control.application.run import load_scenario
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
from constellation_control.dynamics.j2 import first_order_j2_rates
from constellation_control.dynamics.orbits import mean_to_classical
from constellation_control.mean_elements.roe import damico_roe


def _force() -> ForceModelConfig:
    return ForceModelConfig(
        mode=ForceMode.SCREENING,
        mu_m3_s2=3.986004418e14,
        reference_radius_m=6378137.0,
        j2=0.00108262668,
        earth_rotation_rate_rad_s=7.292115e-5,
        gravity_degree=2,
        gravity_order=0,
    )


def _orbit(lambda_rad: float) -> MeanOrbit:
    return MeanOrbit(
        a_m=26_560_000.0,
        ex=0.0012,
        ey=0.0004,
        ix=0.19,
        iy=0.03,
        lambda_rad=lambda_rad,
        definition=MeanElementDefinition(
            theory="screening-j2-first-order",
            force_model_fingerprint="test",
        ),
    )


def _spacecraft() -> SpacecraftModel:
    return SpacecraftModel(
        dry_mass_kg=500.0,
        propellant_mass_kg=50.0,
        isp_s=220.0,
        area_m2=8.0,
        cr=1.3,
    )


def _request(satellites: tuple[SatelliteSpec, ...]) -> PropagationRequest:
    return PropagationRequest(
        scenario_id="screening-validation",
        satellites=satellites,
        duration_s=2.0 * 86400.0,
        output_step_s=600.0,
        force_model=_force(),
        integrator=IntegratorConfig(
            min_step_s=0.1,
            max_step_s=300.0,
            abs_tolerance=1e-9,
            rel_tolerance=1e-12,
        ),
        seed=4713,
    )


def test_j2_rates_recovered_from_propagated_mean_element_history() -> None:
    satellite = SatelliteSpec(
        satellite_id="S",
        plane_id="P",
        role="reference",
        mean_orbit=_orbit(0.2),
        spacecraft=_spacecraft(),
    )
    request = _request((satellite,))
    result = SyntheticMeanPropagator().propagate(request)
    elements = [mean_to_classical(item) for item in result.mean_orbits["S"]]
    times = np.asarray(result.times_s)

    raan = np.unwrap(np.asarray([item.raan_rad for item in elements]))
    argp = np.unwrap(np.asarray([item.argp_rad for item in elements]))
    mean_anomaly = np.unwrap(np.asarray([item.mean_anomaly_rad for item in elements]))
    expected = first_order_j2_rates(mean_to_classical(satellite.mean_orbit), request.force_model)

    assert isclose(linear_rate(times, raan), expected.raan_rad_s, rel_tol=2e-9, abs_tol=1e-14)
    assert isclose(linear_rate(times, argp), expected.argp_rad_s, rel_tol=2e-9, abs_tol=1e-14)
    assert isclose(
        linear_rate(times, mean_anomaly),
        expected.mean_anomaly_rad_s,
        rel_tol=2e-9,
        abs_tol=1e-14,
    )


def test_phase_symmetric_spacecraft_have_symmetric_screening_metrics() -> None:
    reference = SatelliteSpec(
        satellite_id="REF",
        plane_id="P",
        role="reference",
        mean_orbit=_orbit(0.0),
        spacecraft=_spacecraft(),
    )
    plus = SatelliteSpec(
        satellite_id="PLUS",
        plane_id="P",
        role="additional",
        reference_id="REF",
        mean_orbit=_orbit(pi / 4.0),
        spacecraft=_spacecraft(),
    )
    minus = SatelliteSpec(
        satellite_id="MINUS",
        plane_id="P",
        role="additional",
        reference_id="REF",
        mean_orbit=_orbit(-pi / 4.0),
        spacecraft=_spacecraft(),
    )
    result = SyntheticMeanPropagator().propagate(_request((reference, plus, minus)))

    plus_phase = np.asarray(
        [
            damico_roe(ref, dep).delta_lambda_rad
            for ref, dep in zip(
                result.mean_orbits["REF"],
                result.mean_orbits["PLUS"],
                strict=True,
            )
        ]
    )
    minus_phase = np.asarray(
        [
            damico_roe(ref, dep).delta_lambda_rad
            for ref, dep in zip(
                result.mean_orbits["REF"],
                result.mean_orbits["MINUS"],
                strict=True,
            )
        ]
    )
    assert np.allclose(plus_phase, -minus_phase, rtol=0.0, atol=2e-12)

    plus_distance = np.asarray(
        [
            np.linalg.norm(np.asarray(dep.r_m) - np.asarray(ref.r_m))
            for ref, dep in zip(
                result.cartesian_states["REF"],
                result.cartesian_states["PLUS"],
                strict=True,
            )
        ]
    )
    minus_distance = np.asarray(
        [
            np.linalg.norm(np.asarray(dep.r_m) - np.asarray(ref.r_m))
            for ref, dep in zip(
                result.cartesian_states["REF"],
                result.cartesian_states["MINUS"],
                strict=True,
            )
        ]
    )
    assert np.allclose(plus_distance, minus_distance, rtol=1e-12, atol=1e-5)


def test_scenario_mean_element_definition_is_bound_to_force_model() -> None:
    scenario_path = Path(__file__).parents[1] / "scenarios" / "mvp_45deg.yaml"
    scenario = load_scenario(scenario_path)
    fingerprint = scenario.force_model.fingerprint()
    assert all(
        satellite.mean_orbit.definition.force_model_fingerprint == fingerprint
        for satellite in scenario.constellation.satellites
    )
