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
) -> MPCSolution:
    import cvxpy as cp

    horizon, state_dim, _ = a_matrices.shape
    input_dim = b_matrices.shape[2]
    if b_matrices.shape[:2] != (horizon, state_dim):
        raise ValueError("A/B dimensions are inconsistent")
    if disturbances.shape != (horizon, state_dim):
        raise ValueError("disturbance dimensions are inconsistent")
    target_state = np.zeros(state_dim) if target is None else np.asarray(target, dtype=float)

    x = cp.Variable((horizon + 1, state_dim))
    u = cp.Variable((horizon, input_dim))
    z = cp.Variable(nonneg=True)
    constraints = [x[0] == x0]
    for k in range(horizon):
        constraints += [x[k + 1] == a_matrices[k] @ x[k] + b_matrices[k] @ u[k] + disturbances[k]]
        constraints += [x[k + 1] >= lower_state, x[k + 1] <= upper_state]
        constraints += [cp.abs(u[k]) <= max_abs_impulse]
        if not bool(maneuver_windows[k]):
            constraints += [u[k] == 0.0]
    for input_slice in spacecraft_input_slices:
        constraints += [cp.sum(cp.abs(u[:, input_slice])) <= z]

    objective = cp.Minimize(cp.norm1(u) + w_max * z + w_tracking * cp.sum_squares(x[1:] - target_state))
    problem = cp.Problem(objective, constraints)
    problem.solve()
    if problem.status not in {cp.OPTIMAL, cp.OPTIMAL_INACCURATE} or x.value is None or u.value is None:
        raise RuntimeError(f"MPC problem is not feasible: {problem.status}")
    return MPCSolution(np.asarray(x.value), np.asarray(u.value), float(problem.value))
