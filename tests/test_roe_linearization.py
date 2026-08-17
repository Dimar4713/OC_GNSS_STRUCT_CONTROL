from __future__ import annotations

from datetime import UTC, datetime

import numpy as np

from constellation_control.control.linearization import FiniteDifferenceRoeLinearizationProvider
from constellation_control.domain.models import (
    ForceModelConfig,
    ForceMode,
    FrameName,
    IntegratorConfig,
    Maneuver,
    MeanElementDefinition,
    MeanOrbit,
    OsculatingState,
    PropagationRequest,
    PropagationResult,
    SatelliteSpec,
    SpacecraftModel,
    TimeScaleName,
)
from constellation_control.mean_elements.roe import (
    RelativeOrbitalElements,
    damico_roe,
    mean_from_damico_roe,
)


A_TRUE = np.eye(6)
A_TRUE[1, 0] = -0.35
A_TRUE[3, 2] = 0.12
A_TRUE[5, 4] = -0.08
B_TRUE = np.zeros((6, 3))
B_TRUE[0, 1] = 2.0e-4
B_TRUE[1, 1] = 3.0e-3
B_TRUE[2, 0] = 4.0e-4
B_TRUE[3, 0] = -2.0e-4
B_TRUE[4, 2] = 5.0e-4
B_TRUE[5, 2] = 1.0e-4
D_TRUE = np.asarray([1.0e-7, -2.0e-6, 3.0e-7, -4.0e-7, 2.0e-7, 5.0e-7])


def _force() -> ForceModelConfig:
    return ForceModelConfig(
        mode=ForceMode.VALIDATION,
        mu_m3_s2=3.986004418e14,
        reference_radius_m=6_378_137.0,
        flattening=1.0 / 298.257223563,
        j2=0.00108262668,
        earth_rotation_rate_rad_s=7.292115e-5,
        gravity_degree=2,
        gravity_order=0,
    )


def _reference() -> MeanOrbit:
    force = _force()
    return MeanOrbit(
        a_m=26_560_000.0,
        ex=0.001,
        ey=0.0002,
        ix=0.20,
        iy=0.02,
        lambda_rad=0.3,
        definition=MeanElementDefinition(
            theory="toy-validation-mean",
            force_model_fingerprint=force.fingerprint(),
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


def _request() -> PropagationRequest:
    reference_mean = _reference()
    relative = RelativeOrbitalElements(
        delta_a=2.0e-5,
        delta_lambda_rad=0.05,
        delta_ex=1.0e-4,
        delta_ey=-2.0e-4,
        delta_ix=3.0e-4,
        delta_iy=-1.0e-4,
    )
    deputy_mean = mean_from_damico_roe(reference_mean, relative)
    reference = SatelliteSpec(
        satellite_id="REF",
        plane_id="P",
        role="reference",
        mean_orbit=reference_mean,
        spacecraft=_spacecraft(),
    )
    deputy = SatelliteSpec(
        satellite_id="DEP",
        plane_id="P",
        role="additional",
        reference_id="REF",
        mean_orbit=deputy_mean,
        spacecraft=_spacecraft(),
    )
    return PropagationRequest(
        scenario_id="toy-linearization",
        epoch=datetime(2026, 1, 1, tzinfo=UTC),
        frame=FrameName.EME2000,
        time_scale=TimeScaleName.UTC,
        satellites=(reference, deputy),
        duration_s=2.0,
        output_step_s=1.0,
        force_model=_force(),
        integrator=IntegratorConfig(
            min_step_s=0.01,
            max_step_s=1.0,
            abs_tolerance=1e-9,
            rel_tolerance=1e-12,
        ),
        seed=4713,
    )


class ToyValidationPropagator:
    def propagate(self, request: PropagationRequest) -> PropagationResult:
        reference = next(sat for sat in request.satellites if sat.role == "reference")
        deputy = next(sat for sat in request.satellites if sat.role == "additional")
        current = np.asarray(damico_roe(reference.mean_orbit, deputy.mean_orbit).as_tuple(), dtype=float)
        count = int(round(request.duration_s / request.output_step_s))
        times = [0.0]
        ref_history = [reference.mean_orbit]
        dep_history = [deputy.mean_orbit]
        zero = OsculatingState(epoch_s=0.0, r_m=(1.0, 0.0, 0.0), v_m_s=(0.0, 1.0, 0.0))
        ref_cart = [zero]
        dep_cart = [zero]

        impulse = np.zeros(3)
        for maneuver in request.maneuvers:
            if maneuver.satellite_id == deputy.satellite_id and maneuver.time_s == 0.0:
                impulse += np.asarray(maneuver.dv_rtn_m_s)

        for index in range(count):
            control = impulse if index == 0 else np.zeros(3)
            current = A_TRUE @ current + B_TRUE @ control + D_TRUE
            current[1] = float(np.arctan2(np.sin(current[1]), np.cos(current[1])))
            relative = RelativeOrbitalElements(*[float(value) for value in current])
            dep_mean = mean_from_damico_roe(reference.mean_orbit, relative)
            time_s = (index + 1) * request.output_step_s
            times.append(float(time_s))
            ref_history.append(reference.mean_orbit)
            dep_history.append(dep_mean)
            state = OsculatingState(
                epoch_s=float(time_s),
                r_m=(1.0, 0.0, 0.0),
                v_m_s=(0.0, 1.0, 0.0),
            )
            ref_cart.append(state)
            dep_cart.append(state)

        return PropagationResult(
            backend="orekit-toy-validation",
            backend_version="test",
            force_model_fingerprint=request.force_model.fingerprint(),
            backend_metadata={"orekit_data_sha256": "a" * 64},
            times_s=tuple(times),
            mean_orbits={
                reference.satellite_id: tuple(ref_history),
                deputy.satellite_id: tuple(dep_history),
            },
            cartesian_states={
                reference.satellite_id: tuple(ref_cart),
                deputy.satellite_id: tuple(dep_cart),
            },
        )


def test_inverse_damico_mapping_round_trip() -> None:
    reference = _reference()
    target = RelativeOrbitalElements(2e-5, 0.05, 1e-4, -2e-4, 3e-4, -1e-4)
    deputy = mean_from_damico_roe(reference, target)
    recovered = np.asarray(damico_roe(reference, deputy).as_tuple())
    assert np.allclose(recovered, np.asarray(target.as_tuple()), rtol=0.0, atol=5e-14)
    assert deputy.definition == reference.definition


def test_finite_difference_provider_recovers_time_varying_mpc_contract() -> None:
    request = _request()
    provider = FiniteDifferenceRoeLinearizationProvider(
        ToyValidationPropagator(),
        deputy_id="DEP",
        state_steps=np.full(6, 1.0e-6),
        impulse_step_m_s=1.0e-3,
    )
    a_matrices, b_matrices, disturbances = provider.linearize(request, np.asarray([0.0, 1.0, 2.0]))

    assert a_matrices.shape == (2, 6, 6)
    assert b_matrices.shape == (2, 6, 3)
    assert disturbances.shape == (2, 6)
    assert np.allclose(a_matrices, np.stack([A_TRUE, A_TRUE]), rtol=0.0, atol=2e-8)
    assert np.allclose(b_matrices, np.stack([B_TRUE, B_TRUE]), rtol=0.0, atol=2e-8)
    assert np.allclose(disturbances, np.stack([D_TRUE, D_TRUE]), rtol=0.0, atol=2e-8)


def test_linearization_rejects_non_validation_authority() -> None:
    request = _request()
    screening = request.model_copy(
        update={"force_model": request.force_model.model_copy(update={"mode": ForceMode.SCREENING})}
    )
    provider = FiniteDifferenceRoeLinearizationProvider(ToyValidationPropagator())
    try:
        provider.linearize(screening, np.asarray([0.0, 1.0, 2.0]))
    except ValueError as error:
        assert "validation force mode" in str(error)
    else:
        raise AssertionError("screening authority must not generate MPC matrices")
