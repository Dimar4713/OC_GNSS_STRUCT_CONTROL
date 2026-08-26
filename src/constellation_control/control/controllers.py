from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from constellation_control.domain.models import Maneuver, ManeuverPlan


@dataclass(frozen=True)
class DeadbandCandidate:
    dv_rtn_m_s: tuple[float, float, float]
    predicted_delta_lambda_rad: np.ndarray
    predicted_min_distance_m: np.ndarray


class DeadbandController:
    def __init__(self, phase_limit_rad: float, min_distance_m: float) -> None:
        self.phase_limit_rad = phase_limit_rad
        self.min_distance_m = min_distance_m

    def _safe_horizon(self, phase: np.ndarray, distance: np.ndarray) -> int:
        valid = (np.abs(phase) <= self.phase_limit_rad) & (distance >= self.min_distance_m)
        failed = np.flatnonzero(~valid)
        return int(failed[0]) if failed.size else len(valid)

    def plan(
        self,
        satellite_id: str,
        baseline_phase: np.ndarray,
        baseline_distance: np.ndarray,
        candidates: tuple[DeadbandCandidate, ...],
    ) -> ManeuverPlan:
        if self._safe_horizon(baseline_phase, baseline_distance) == len(baseline_phase):
            return ManeuverPlan()
        ranked: list[tuple[int, float, DeadbandCandidate]] = []
        for candidate in candidates:
            horizon = self._safe_horizon(candidate.predicted_delta_lambda_rad, candidate.predicted_min_distance_m)
            dv = float(np.linalg.norm(candidate.dv_rtn_m_s))
            if horizon > 0:
                ranked.append((horizon, -dv, candidate))
        if not ranked:
            raise RuntimeError("no deadband maneuver candidate satisfies hard safety constraints")
        _, _, selected = max(ranked, key=lambda item: (item[0], item[1]))
        return ManeuverPlan(maneuvers=(Maneuver(satellite_id=satellite_id, time_s=0.0, dv_rtn_m_s=selected.dv_rtn_m_s),))


@dataclass(frozen=True)
class MPCSolution:
    states: np.ndarray
    impulses: np.ndarray
    objective: float


def solve_impulsive_mpc(
    x0: np.ndarray,
    a_matrices: np.ndarray,
    b_matrices: np.ndarray,
    disturbances: np.ndarray,
    lower_state: np.ndarray,
    upper_state: np.ndarray,
    max_abs_impulse: np.ndarray,
    maneuver_windows: np.ndarray,
    spacecraft_input_slices: tuple[slice, ...],
    target: np.ndarray | None = None,
    w_tracking: float = 1.0,
    w_max: float = 1.0,
    eccentricity_vector_max: float | None = None,
    inclination_vector_max: float | None = None,
    mean_phase_cot_i: float | None = None,
    mean_phase_half_width_rad: float | None = None,
) -> MPCSolution:
    """Solve a convex impulsive MPC problem in D'Amico ROE coordinates.

    State ordering is `[delta_a, delta_lambda, delta_ex, delta_ey, delta_ix, delta_iy]`.
    Finite component-wise bounds are complemented by optional vector corridors and
    an operational mean-phase corridor
    `|delta_lambda - cot(i_ref) * delta_iy| <= half_width`.
    Infinite lower/upper entries explicitly mean that a component has no independent
    box bound. Minimum-impulse-bit and nonlinear safety replay are intentionally
    handled by the execution-authority layer because they are not convex constraints
    in this formulation.
    """

    import cvxpy as cp

    x0_array = np.asarray(x0, dtype=float)
    lower = np.asarray(lower_state, dtype=float)
    upper = np.asarray(upper_state, dtype=float)
    max_impulse = np.asarray(max_abs_impulse, dtype=float)
    windows = np.asarray(maneuver_windows, dtype=bool)

    if a_matrices.ndim != 3 or a_matrices.shape[1] != a_matrices.shape[2]:
        raise ValueError("A matrices must have shape (horizon, state_dim, state_dim)")
    horizon, state_dim, _ = a_matrices.shape
    if b_matrices.shape[:2] != (horizon, state_dim):
        raise ValueError("A/B dimensions are inconsistent")
    input_dim = b_matrices.shape[2]
    if disturbances.shape != (horizon, state_dim):
        raise ValueError("disturbance dimensions are inconsistent")
    if x0_array.shape != (state_dim,) or lower.shape != (state_dim,) or upper.shape != (state_dim,):
        raise ValueError("x0/lower/upper must match the MPC state dimension")
    if np.any(np.isnan(lower)) or np.any(np.isnan(upper)):
        raise ValueError("lower_state and upper_state must not contain NaN")
    if np.any(lower > upper):
        raise ValueError("lower_state must not exceed upper_state")
    if max_impulse.shape != (input_dim,) or np.any(max_impulse < 0.0):
        raise ValueError("max_abs_impulse must match input dimension and be non-negative")
    if windows.shape != (horizon,):
        raise ValueError("maneuver_windows must have one boolean per horizon interval")
    if state_dim < 6 and (
        eccentricity_vector_max is not None
        or inclination_vector_max is not None
        or mean_phase_cot_i is not None
        or mean_phase_half_width_rad is not None
    ):
        raise ValueError("ROE vector/mean-phase corridors require at least six state components")
    if eccentricity_vector_max is not None and eccentricity_vector_max <= 0.0:
        raise ValueError("eccentricity_vector_max must be positive")
    if inclination_vector_max is not None and inclination_vector_max <= 0.0:
        raise ValueError("inclination_vector_max must be positive")
    if (mean_phase_cot_i is None) != (mean_phase_half_width_rad is None):
        raise ValueError("mean_phase_cot_i and mean_phase_half_width_rad must be supplied together")
    if mean_phase_cot_i is not None and not np.isfinite(mean_phase_cot_i):
        raise ValueError("mean_phase_cot_i must be finite")
    if mean_phase_half_width_rad is not None and (
        not np.isfinite(mean_phase_half_width_rad) or mean_phase_half_width_rad <= 0.0
    ):
        raise ValueError("mean_phase_half_width_rad must be positive and finite")
    for input_slice in spacecraft_input_slices:
        start = 0 if input_slice.start is None else input_slice.start
        stop = input_dim if input_slice.stop is None else input_slice.stop
        if start < 0 or stop > input_dim or start >= stop:
            raise ValueError("spacecraft input slice lies outside MPC input dimension")

    target_state = np.zeros(state_dim) if target is None else np.asarray(target, dtype=float)
    if target_state.shape != (state_dim,):
        raise ValueError("target must match the MPC state dimension")

    finite_lower = np.flatnonzero(np.isfinite(lower))
    finite_upper = np.flatnonzero(np.isfinite(upper))
    x = cp.Variable((horizon + 1, state_dim))
    u = cp.Variable((horizon, input_dim))
    z = cp.Variable(nonneg=True)
    constraints = [x[0] == x0_array]
    for k in range(horizon):
        constraints += [x[k + 1] == a_matrices[k] @ x[k] + b_matrices[k] @ u[k] + disturbances[k]]
        if finite_lower.size:
            constraints += [x[k + 1, finite_lower] >= lower[finite_lower]]
        if finite_upper.size:
            constraints += [x[k + 1, finite_upper] <= upper[finite_upper]]
        constraints += [cp.abs(u[k]) <= max_impulse]
        if eccentricity_vector_max is not None:
            constraints += [cp.norm2(x[k + 1, 2:4]) <= eccentricity_vector_max]
        if inclination_vector_max is not None:
            constraints += [cp.norm2(x[k + 1, 4:6]) <= inclination_vector_max]
        if mean_phase_cot_i is not None and mean_phase_half_width_rad is not None:
            delta_u = x[k + 1, 1] - mean_phase_cot_i * x[k + 1, 5]
            constraints += [cp.abs(delta_u) <= mean_phase_half_width_rad]
        if not bool(windows[k]):
            constraints += [u[k] == 0.0]
    for input_slice in spacecraft_input_slices:
        constraints += [cp.sum(cp.abs(u[:, input_slice])) <= z]

    objective = cp.Minimize(cp.norm1(u) + w_max * z + w_tracking * cp.sum_squares(x[1:] - target_state))
    problem = cp.Problem(objective, constraints)
    problem.solve()
    if problem.status not in {cp.OPTIMAL, cp.OPTIMAL_INACCURATE} or x.value is None or u.value is None:
        raise RuntimeError(f"MPC problem is not feasible: {problem.status}")
    return MPCSolution(np.asarray(x.value), np.asarray(u.value), float(problem.value))
