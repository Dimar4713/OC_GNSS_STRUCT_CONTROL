from __future__ import annotations

from datetime import timedelta

import numpy as np

from constellation_control.domain.models import (
    ForceMode,
    Maneuver,
    MeanOrbit,
    PropagationRequest,
    SatelliteSpec,
)
from constellation_control.domain.protocols import Propagator
from constellation_control.dynamics.orbits import wrap_pi
from constellation_control.mean_elements.roe import (
    RelativeOrbitalElements,
    damico_roe,
    mean_from_damico_roe,
)


_DEFAULT_STATE_STEPS = np.asarray([1.0e-8, 1.0e-8, 1.0e-8, 1.0e-8, 1.0e-8, 1.0e-8])


class FiniteDifferenceRoeLinearizationProvider:
    """Build local ROE dynamics from repeated authoritative propagation.

    For each interval this provider central-differences all six D'Amico ROE
    state coordinates and all three RTN impulse coordinates. It deliberately
    requires validation mode so MPC matrices cannot silently come from the
    screening backend.
    """

    def __init__(
        self,
        propagator: Propagator,
        deputy_id: str | None = None,
        state_steps: np.ndarray | None = None,
        impulse_step_m_s: float = 1.0e-4,
    ) -> None:
        self._propagator = propagator
        self._deputy_id = deputy_id
        self._state_steps = np.asarray(
            _DEFAULT_STATE_STEPS if state_steps is None else state_steps,
            dtype=float,
        )
        if (
            self._state_steps.shape != (6,)
            or not np.all(np.isfinite(self._state_steps))
            or np.any(self._state_steps <= 0.0)
        ):
            raise ValueError("state_steps must contain six positive finite-difference steps")
        if not np.isfinite(impulse_step_m_s) or impulse_step_m_s <= 0.0:
            raise ValueError("impulse_step_m_s must be positive and finite")
        self._impulse_step_m_s = float(impulse_step_m_s)

    def linearize(
        self,
        request: PropagationRequest,
        times_s: np.ndarray,
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        if request.force_model.mode != ForceMode.VALIDATION:
            raise ValueError("ROE finite-difference linearization requires validation force mode")
        if request.maneuvers:
            raise ValueError("linearization baseline request must not contain scheduled maneuvers")

        requested_times = np.asarray(times_s, dtype=float)
        if requested_times.ndim != 1 or requested_times.size < 2:
            raise ValueError("times_s must be a one-dimensional grid with at least two epochs")
        if not np.all(np.isfinite(requested_times)) or requested_times[0] != 0.0:
            raise ValueError("times_s must be finite and start at zero")
        if np.any(np.diff(requested_times) <= 0.0):
            raise ValueError("times_s must be strictly increasing")

        baseline = self._propagator.propagate(request)
        baseline_times = np.asarray(baseline.times_s, dtype=float)
        if baseline_times.shape != requested_times.shape or not np.allclose(
            baseline_times,
            requested_times,
            rtol=0.0,
            atol=1.0e-9,
        ):
            raise ValueError("times_s must match the authoritative propagation output grid")

        satellite_by_id = {sat.satellite_id: sat for sat in request.satellites}
        deputy = self._resolve_deputy(request.satellites)
        if deputy.reference_id is None:
            raise ValueError("deputy must declare reference_id")
        reference = satellite_by_id[deputy.reference_id]

        horizon = requested_times.size - 1
        a_matrices = np.empty((horizon, 6, 6), dtype=float)
        b_matrices = np.empty((horizon, 6, 3), dtype=float)
        disturbances = np.empty((horizon, 6), dtype=float)

        ref_history = baseline.mean_orbits[reference.satellite_id]
        dep_history = baseline.mean_orbits[deputy.satellite_id]

        for k in range(horizon):
            time_s = float(requested_times[k])
            dt_s = float(requested_times[k + 1] - requested_times[k])
            ref_now = ref_history[k]
            dep_now = dep_history[k]
            current = damico_roe(ref_now, dep_now)
            current_vector = self._vector(current)
            baseline_next = self._vector(damico_roe(ref_history[k + 1], dep_history[k + 1]))

            local_reference = reference.model_copy(update={"mean_orbit": ref_now})
            local_deputy = deputy.model_copy(update={"mean_orbit": dep_now})
            local_request = request.model_copy(
                update={
                    "epoch": request.epoch + timedelta(seconds=time_s),
                    "satellites": (local_reference, local_deputy),
                    "maneuvers": (),
                    "duration_s": dt_s,
                    "output_step_s": dt_s,
                }
            )

            for component, step in enumerate(self._state_steps):
                plus = self._perturb_relative(current, component, float(step))
                minus = self._perturb_relative(current, component, -float(step))
                plus_next = self._next_roe(
                    local_request,
                    local_reference,
                    local_deputy,
                    mean_from_damico_roe(ref_now, plus),
                    None,
                )
                minus_next = self._next_roe(
                    local_request,
                    local_reference,
                    local_deputy,
                    mean_from_damico_roe(ref_now, minus),
                    None,
                )
                a_matrices[k, :, component] = self._difference(plus_next, minus_next) / (2.0 * step)

            for component in range(3):
                plus_dv = [0.0, 0.0, 0.0]
                minus_dv = [0.0, 0.0, 0.0]
                plus_dv[component] = self._impulse_step_m_s
                minus_dv[component] = -self._impulse_step_m_s
                plus_next = self._next_roe(
                    local_request,
                    local_reference,
                    local_deputy,
                    dep_now,
                    (plus_dv[0], plus_dv[1], plus_dv[2]),
                )
                minus_next = self._next_roe(
                    local_request,
                    local_reference,
                    local_deputy,
                    dep_now,
                    (minus_dv[0], minus_dv[1], minus_dv[2]),
                )
                b_matrices[k, :, component] = self._difference(plus_next, minus_next) / (
                    2.0 * self._impulse_step_m_s
                )

            disturbances[k] = baseline_next - a_matrices[k] @ current_vector
            disturbances[k, 1] = wrap_pi(float(disturbances[k, 1]))

        return a_matrices, b_matrices, disturbances

    def _resolve_deputy(self, satellites: tuple[SatelliteSpec, ...]) -> SatelliteSpec:
        additional = [sat for sat in satellites if sat.role == "additional"]
        if self._deputy_id is not None:
            matches = [sat for sat in additional if sat.satellite_id == self._deputy_id]
            if len(matches) != 1:
                raise ValueError(f"unknown or non-additional deputy_id: {self._deputy_id}")
            return matches[0]
        if len(additional) != 1:
            raise ValueError("deputy_id is required unless the request contains exactly one additional satellite")
        return additional[0]

    def _next_roe(
        self,
        request: PropagationRequest,
        reference: SatelliteSpec,
        deputy: SatelliteSpec,
        deputy_mean: MeanOrbit,
        dv_rtn_m_s: tuple[float, float, float] | None,
    ) -> np.ndarray:
        deputy_updated = deputy.model_copy(update={"mean_orbit": deputy_mean})
        maneuvers: tuple[Maneuver, ...] = ()
        if dv_rtn_m_s is not None:
            maneuvers = (
                Maneuver(
                    satellite_id=deputy.satellite_id,
                    time_s=0.0,
                    dv_rtn_m_s=dv_rtn_m_s,
                ),
            )
        perturbed = request.model_copy(
            update={
                "satellites": (reference, deputy_updated),
                "maneuvers": maneuvers,
            }
        )
        result = self._propagator.propagate(perturbed)
        ref_next = result.mean_orbits[reference.satellite_id][-1]
        dep_next = result.mean_orbits[deputy.satellite_id][-1]
        return self._vector(damico_roe(ref_next, dep_next))

    @staticmethod
    def _vector(relative: RelativeOrbitalElements) -> np.ndarray:
        return np.asarray(relative.as_tuple(), dtype=float)

    @staticmethod
    def _difference(plus: np.ndarray, minus: np.ndarray) -> np.ndarray:
        delta = np.asarray(plus - minus, dtype=float)
        delta[1] = wrap_pi(float(plus[1] - minus[1]))
        return delta

    @staticmethod
    def _perturb_relative(
        relative: RelativeOrbitalElements,
        component: int,
        increment: float,
    ) -> RelativeOrbitalElements:
        values = list(relative.as_tuple())
        values[component] += increment
        if component == 1:
            values[component] = wrap_pi(values[component])
        return RelativeOrbitalElements(*values)
