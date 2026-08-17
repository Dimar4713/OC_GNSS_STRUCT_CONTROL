from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

import numpy as np

from constellation_control.control.execution import MPCExecutionPolicy, RecedingHorizonMPCController
from constellation_control.domain.models import (
    ConstraintConfig,
    ForceModelConfig,
    ForceMode,
    FrameName,
    GravityModelName,
    IntegratorConfig,
    MeanElementDefinition,
    MeanOrbit,
    OsculatingState,
    PropagationRequest,
    PropagationResult,
    SatelliteSpec,
    SpacecraftModel,
    TimeScaleName,
)
from constellation_control.mean_elements.roe import RelativeOrbitalElements, damico_roe, mean_from_damico_roe


class FixedLinearizer:
    def linearize(
        self,
        request: PropagationRequest,
        times_s: np.ndarray,
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        del request
        assert np.allclose(times_s, np.asarray([0.0, 60.0]))
        a = np.eye(6, dtype=float)[None, :, :]
        b = np.zeros((1, 6, 3), dtype=float)
        b[0, 1, 1] = 1.0  # tangential impulse controls relative phase in this local test model
        d = np.zeros((1, 6), dtype=float)
        return a, b, d


@dataclass
class ReplayPropagator:
    backend: str = "orekit-numerical-validation"
    minimum_distance_m: float = 5000.0
    phase_bias_rad: float = 0.0
    fingerprint_matches: bool = True
    calls: int = 0

    def propagate(self, request: PropagationRequest) -> PropagationResult:
        self.calls += 1
        assert len(request.maneuvers) == 1
        maneuver = request.maneuvers[0]
        reference = next(sat for sat in request.satellites if sat.role == "reference")
        deputy = next(sat for sat in request.satellites if sat.role == "additional")
        initial = damico_roe(reference.mean_orbit, deputy.mean_orbit)
        next_relative = RelativeOrbitalElements(
            delta_a=initial.delta_a,
            delta_lambda_rad=initial.delta_lambda_rad + maneuver.dv_rtn_m_s[1] + self.phase_bias_rad,
            delta_ex=initial.delta_ex,
            delta_ey=initial.delta_ey,
            delta_ix=initial.delta_ix,
            delta_iy=initial.delta_iy,
        )
        deputy_next = mean_from_damico_roe(reference.mean_orbit, next_relative)
        zero_velocity = (0.0, 0.0, 0.0)
        ref_cart = (
            OsculatingState(epoch_s=0.0, r_m=(0.0, 0.0, 0.0), v_m_s=zero_velocity),
            OsculatingState(epoch_s=60.0, r_m=(0.0, 0.0, 0.0), v_m_s=zero_velocity),
        )
        dep_cart = (
            OsculatingState(epoch_s=0.0, r_m=(self.minimum_distance_m, 0.0, 0.0), v_m_s=zero_velocity),
            OsculatingState(epoch_s=60.0, r_m=(self.minimum_distance_m, 0.0, 0.0), v_m_s=zero_velocity),
        )
        fingerprint = request.force_model.fingerprint() if self.fingerprint_matches else "0" * 64
        return PropagationResult(
            backend=self.backend,
            backend_version="13.1.7",
            force_model_fingerprint=fingerprint,
            backend_metadata={
                "orekit_version": "13.1.7",
                "orekit_data_revision": "baf158744d38ec76cf94e2d396280d545b9f0ba2",
                "orekit_data_sha256": "7c0387b0bf7f08f0393b724090c9b926870cae4dde1d02823d57291eab0a3fcf",
                "gravity_model": "EIGEN-6S",
            },
            times_s=(0.0, 60.0),
            mean_orbits={
                reference.satellite_id: (reference.mean_orbit, reference.mean_orbit),
                deputy.satellite_id: (deputy.mean_orbit, deputy_next),
            },
            cartesian_states={reference.satellite_id: ref_cart, deputy.satellite_id: dep_cart},
        )


def _force() -> ForceModelConfig:
    return ForceModelConfig(
        mode=ForceMode.VALIDATION,
        gravity_model=GravityModelName.EIGEN_6S,
        mu_m3_s2=3.986004418e14,
        reference_radius_m=6378137.0,
        flattening=1.0 / 298.257223563,
        j2=0.00108262668,
        earth_rotation_rate_rad_s=7.292115e-5,
        gravity_degree=8,
        gravity_order=8,
        moon=True,
        sun=True,
        srp=True,
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
    force = _force()
    definition = MeanElementDefinition(theory="test-validation-mean", force_model_fingerprint=force.fingerprint())
    reference_mean = MeanOrbit(
        a_m=26_560_000.0,
        ex=0.001,
        ey=0.0002,
        ix=0.20,
        iy=0.02,
        lambda_rad=0.30,
        definition=definition,
    )
    deputy_mean = mean_from_damico_roe(
        reference_mean,
        RelativeOrbitalElements(
            delta_a=0.0,
            delta_lambda_rad=0.08,
            delta_ex=0.0,
            delta_ey=0.0,
            delta_ix=0.0,
            delta_iy=0.0,
        ),
    )
    reference = SatelliteSpec(
        satellite_id="REF",
        plane_id="P1",
        role="reference",
        mean_orbit=reference_mean,
        spacecraft=_spacecraft(),
    )
    deputy = SatelliteSpec(
        satellite_id="DEP",
        plane_id="P1",
        role="additional",
        reference_id="REF",
        mean_orbit=deputy_mean,
        spacecraft=_spacecraft(),
    )
    return PropagationRequest(
        scenario_id="mpc-authority-test",
        epoch=datetime(2026, 1, 1, tzinfo=UTC),
        frame=FrameName.EME2000,
        time_scale=TimeScaleName.UTC,
        satellites=(reference, deputy),
        duration_s=60.0,
        output_step_s=60.0,
        force_model=force,
        integrator=IntegratorConfig(
            min_step_s=0.1,
            max_step_s=30.0,
            abs_tolerance=1.0e-6,
            rel_tolerance=1.0e-12,
        ),
        seed=4713,
    )


def _constraints(minimum_distance_m: float = 1000.0, reserve: float = 0.1) -> ConstraintConfig:
    return ConstraintConfig(
        min_pair_distance_m=minimum_distance_m,
        delta_a_bounds_m=(-5000.0, 5000.0),
        delta_e_max=0.01,
        delta_i_max_rad=0.01,
        phase_corridor_rad=0.1,
        propellant_reserve_fraction=reserve,
    )


def _controller(propagator: ReplayPropagator, *, mib: float = 1.0e-3, trust_phase: float = 1.0e-3) -> RecedingHorizonMPCController:
    controller = RecedingHorizonMPCController(
        propagator,
        MPCExecutionPolicy(
            max_abs_impulse_rtn_m_s=(0.2, 0.2, 0.2),
            min_impulse_bit_m_s=mib,
            trust_tolerances_roe=(1.0e-6, trust_phase, 1.0e-6, 1.0e-6, 1.0e-6, 1.0e-6),
            w_tracking=100.0,
            w_max=0.0,
        ),
        deputy_id="DEP",
    )
    controller._linearizer = FixedLinearizer()  # noqa: SLF001 - deterministic authority-unit fixture
    return controller


def _run(controller: RecedingHorizonMPCController):
    return controller.authorize_first_maneuver(
        _request(),
        _constraints(),
        np.asarray([0.0, 60.0]),
        np.asarray([True]),
    )


def test_authorizes_only_first_maneuver_after_numerical_replay() -> None:
    propagator = ReplayPropagator()
    evidence = _run(_controller(propagator))

    assert evidence.authorized
    assert evidence.reason == "authorized-by-numerical-replay"
    assert evidence.first_maneuver is not None
    assert evidence.first_maneuver.time_s == 0.0
    assert evidence.first_maneuver.dv_rtn_m_s[1] < 0.0
    assert evidence.replay_backend == "orekit-numerical-validation"
    assert evidence.trust_error_ratio is not None and evidence.trust_error_ratio < 1.0
    assert evidence.replay_min_pair_distance_m == 5000.0
    assert evidence.requires_relinearization
    assert propagator.calls == 1


def test_rejects_dsst_or_screening_identity_as_execution_authority() -> None:
    propagator = ReplayPropagator(backend="orekit-dsst-design")
    evidence = _run(_controller(propagator))
    assert not evidence.authorized
    assert evidence.reason == "non-authoritative-replay-backend"


def test_rejects_numerical_replay_minimum_distance_violation() -> None:
    propagator = ReplayPropagator(minimum_distance_m=500.0)
    evidence = _run(_controller(propagator))
    assert not evidence.authorized
    assert evidence.reason == "replay-minimum-distance-violation"
    assert evidence.replay_min_pair_distance_m == 500.0


def test_rejects_linear_model_trust_violation() -> None:
    propagator = ReplayPropagator(phase_bias_rad=0.01)
    evidence = _run(_controller(propagator, trust_phase=0.001))
    assert not evidence.authorized
    assert evidence.reason == "linear-model-trust-violation"
    assert evidence.trust_error_ratio is not None and evidence.trust_error_ratio > 1.0


def test_rejects_sub_minimum_impulse_before_replay() -> None:
    propagator = ReplayPropagator()
    evidence = _run(_controller(propagator, mib=0.1))
    assert not evidence.authorized
    assert evidence.reason == "minimum-impulse-bit-violation"
    assert propagator.calls == 0


def test_rejects_force_model_fingerprint_mismatch() -> None:
    propagator = ReplayPropagator(fingerprint_matches=False)
    evidence = _run(_controller(propagator))
    assert not evidence.authorized
    assert evidence.reason == "replay-force-model-fingerprint-mismatch"
