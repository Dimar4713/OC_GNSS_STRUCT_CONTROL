from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from constellation_control.application.run import load_scenario
from constellation_control.control.controllers import solve_impulsive_mpc
from constellation_control.control.execution import RecedingHorizonMPCController
from constellation_control.control.phase_target import delta_u_from_damico_roe
from constellation_control.domain.models import OsculatingState, PropagationResult
from constellation_control.mean_elements.roe import RelativeOrbitalElements, mean_from_damico_roe


def _solve_fixed_state(delta_lambda: float, delta_iy: float, half_width: float = 0.1):
    x0 = np.asarray([0.0, delta_lambda, 0.0, 0.0, 0.0, delta_iy], dtype=float)
    a = np.eye(6, dtype=float)[None, :, :]
    b = np.zeros((1, 6, 1), dtype=float)
    d = np.zeros((1, 6), dtype=float)
    lower = np.asarray([-1.0, -np.inf, -1.0, -1.0, -1.0, -1.0], dtype=float)
    upper = np.asarray([1.0, np.inf, 1.0, 1.0, 1.0, 1.0], dtype=float)
    return solve_impulsive_mpc(
        x0,
        a,
        b,
        d,
        lower,
        upper,
        np.asarray([0.0]),
        np.asarray([False]),
        (slice(0, 1),),
        target=x0,
        mean_phase_cot_i=1.0,
        mean_phase_half_width_rad=half_width,
    )


def test_linear_mpc_accepts_raw_delta_lambda_outside_when_mean_phase_is_inside() -> None:
    solution = _solve_fixed_state(delta_lambda=0.15, delta_iy=0.10)
    assert solution.states[1, 1] == pytest.approx(0.15)
    assert solution.states[1, 1] - solution.states[1, 5] == pytest.approx(0.05)


def test_linear_mpc_rejects_raw_delta_lambda_inside_when_mean_phase_is_outside() -> None:
    with pytest.raises(RuntimeError, match="MPC problem is not feasible"):
        _solve_fixed_state(delta_lambda=0.05, delta_iy=-0.10)


def test_linear_mpc_allows_exact_mean_phase_boundary() -> None:
    solution = _solve_fixed_state(delta_lambda=0.20, delta_iy=0.10)
    assert solution.states[1, 1] - solution.states[1, 5] == pytest.approx(0.10)


def test_linear_mpc_requires_complete_mean_phase_constraint_parameters() -> None:
    x0 = np.zeros(6)
    a = np.eye(6, dtype=float)[None, :, :]
    b = np.zeros((1, 6, 1), dtype=float)
    d = np.zeros((1, 6), dtype=float)
    lower = np.full(6, -np.inf)
    upper = np.full(6, np.inf)
    with pytest.raises(ValueError, match="must be supplied together"):
        solve_impulsive_mpc(
            x0,
            a,
            b,
            d,
            lower,
            upper,
            np.asarray([0.0]),
            np.asarray([False]),
            (slice(0, 1),),
            mean_phase_cot_i=1.0,
        )


def _replay_case(relative: RelativeOrbitalElements) -> tuple[object, PropagationResult, object, object, object]:
    scenario = load_scenario(Path(__file__).parents[1] / "scenarios" / "mvp_45deg.yaml")
    reference = next(sat for sat in scenario.constellation.satellites if sat.role == "reference")
    source_deputy = next(sat for sat in scenario.constellation.satellites if sat.role == "additional")
    deputy = source_deputy.model_copy(
        update={"mean_orbit": mean_from_damico_roe(reference.mean_orbit, relative)}
    )
    request = scenario.propagation_request().model_copy(update={"satellites": (reference, deputy)})
    zero_v = (0.0, 0.0, 0.0)
    ref_cart = OsculatingState(epoch_s=0.0, r_m=(0.0, 0.0, 0.0), v_m_s=zero_v)
    dep_cart = OsculatingState(epoch_s=0.0, r_m=(5000.0, 0.0, 0.0), v_m_s=zero_v)
    replay = PropagationResult(
        backend="test",
        backend_version="test",
        force_model_fingerprint=request.force_model.fingerprint(),
        times_s=(0.0,),
        mean_orbits={reference.satellite_id: (reference.mean_orbit,), deputy.satellite_id: (deputy.mean_orbit,)},
        cartesian_states={reference.satellite_id: (ref_cart,), deputy.satellite_id: (dep_cart,)},
    )
    return request, replay, scenario.constraints, deputy, reference


def test_nonlinear_replay_accepts_delta_lambda_outside_when_actual_delta_u_inside() -> None:
    scenario = load_scenario(Path(__file__).parents[1] / "scenarios" / "mvp_45deg.yaml")
    reference = next(sat for sat in scenario.constellation.satellites if sat.role == "reference")
    cot_i = RecedingHorizonMPCController._mean_phase_cot_i(reference)  # noqa: SLF001
    relative = RelativeOrbitalElements(0.0, 0.15, 0.0, 0.0, 0.0, (0.15 - 0.05) / cot_i)
    assert abs(relative.delta_lambda_rad) > scenario.constraints.phase_corridor_rad
    assert abs(delta_u_from_damico_roe(reference.mean_orbit, relative)) < scenario.constraints.phase_corridor_rad

    request, replay, constraints, deputy, reference = _replay_case(relative)
    reason, minimum_distance = RecedingHorizonMPCController._nonlinear_constraint_reason(  # noqa: SLF001
        request, replay, constraints, deputy, reference
    )
    assert reason is None
    assert minimum_distance == pytest.approx(5000.0)


def test_nonlinear_replay_rejects_delta_lambda_inside_when_actual_delta_u_outside() -> None:
    scenario = load_scenario(Path(__file__).parents[1] / "scenarios" / "mvp_45deg.yaml")
    reference = next(sat for sat in scenario.constellation.satellites if sat.role == "reference")
    cot_i = RecedingHorizonMPCController._mean_phase_cot_i(reference)  # noqa: SLF001
    relative = RelativeOrbitalElements(0.0, 0.05, 0.0, 0.0, 0.0, (0.05 - 0.15) / cot_i)
    assert abs(relative.delta_lambda_rad) < scenario.constraints.phase_corridor_rad
    assert abs(delta_u_from_damico_roe(reference.mean_orbit, relative)) > scenario.constraints.phase_corridor_rad

    request, replay, constraints, deputy, reference = _replay_case(relative)
    reason, _ = RecedingHorizonMPCController._nonlinear_constraint_reason(  # noqa: SLF001
        request, replay, constraints, deputy, reference
    )
    assert reason == "replay-mean-phase-corridor-violation"


def test_execution_mean_phase_linear_mapping_fails_closed_near_equator() -> None:
    scenario = load_scenario(Path(__file__).parents[1] / "scenarios" / "mvp_45deg.yaml")
    reference = next(sat for sat in scenario.constellation.satellites if sat.role == "reference")
    equatorial = reference.model_copy(update={"mean_orbit": reference.mean_orbit.model_copy(update={"ix": 0.0, "iy": 0.0})})
    with pytest.raises(ValueError, match="ill-conditioned near equatorial inclination"):
        RecedingHorizonMPCController._mean_phase_cot_i(equatorial)  # noqa: SLF001
