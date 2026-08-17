from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations
from math import hypot

import numpy as np

from constellation_control.analysis.fuel import propellant_used_kg
from constellation_control.control.controllers import MPCSolution, solve_impulsive_mpc
from constellation_control.control.linearization import FiniteDifferenceRoeLinearizationProvider
from constellation_control.domain.models import (
    ConstraintConfig,
    ForceMode,
    Maneuver,
    PropagationRequest,
    PropagationResult,
    SatelliteSpec,
)
from constellation_control.domain.protocols import Propagator
from constellation_control.dynamics.orbits import wrap_pi
from constellation_control.mean_elements.roe import RelativeOrbitalElements, damico_roe


@dataclass(frozen=True)
class MPCExecutionPolicy:
    """Execution-side limits that must not be hidden in the optimizer objective."""

    max_abs_impulse_rtn_m_s: tuple[float, float, float]
    min_impulse_bit_m_s: float
    trust_tolerances_roe: tuple[float, float, float, float, float, float]
    target_roe: tuple[float, float, float, float, float, float] = (0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
    w_tracking: float = 1.0
    w_max: float = 1.0

    def __post_init__(self) -> None:
        if any(not np.isfinite(value) or value <= 0.0 for value in self.max_abs_impulse_rtn_m_s):
            raise ValueError("max_abs_impulse_rtn_m_s must contain positive finite limits")
        if not np.isfinite(self.min_impulse_bit_m_s) or self.min_impulse_bit_m_s <= 0.0:
            raise ValueError("min_impulse_bit_m_s must be positive and finite")
        if any(not np.isfinite(value) or value <= 0.0 for value in self.trust_tolerances_roe):
            raise ValueError("trust_tolerances_roe must contain six positive finite tolerances")
        if any(not np.isfinite(value) for value in self.target_roe):
            raise ValueError("target_roe must be finite")
        if self.w_tracking < 0.0 or self.w_max < 0.0:
            raise ValueError("MPC weights must be non-negative")


@dataclass(frozen=True)
class ManeuverAuthorityEvidence:
    authorized: bool
    reason: str
    deputy_id: str
    reference_id: str
    first_maneuver: Maneuver | None
    predicted_next_roe: tuple[float, ...] | None
    replay_next_roe: tuple[float, ...] | None
    trust_error_ratio: float | None
    replay_min_pair_distance_m: float | None
    propellant_used_kg: float
    propellant_remaining_kg: float
    required_reserve_kg: float
    replay_backend: str | None
    replay_backend_metadata: dict[str, str]
    a_matrices: tuple[tuple[tuple[float, ...], ...], ...]
    b_matrices: tuple[tuple[tuple[float, ...], ...], ...]
    disturbances: tuple[tuple[float, ...], ...]
    mpc_states: tuple[tuple[float, ...], ...]
    mpc_impulses: tuple[tuple[float, ...], ...]
    mpc_objective: float
    requires_relinearization: bool = True


class RecedingHorizonMPCController:
    """Plan one MPC horizon and authorize at most its first RTN impulse.

    Every call derives fresh A/B/d matrices from the supplied validation propagator.
    The linear solution can propose a maneuver but cannot authorize it. Authorization
    requires a replay of that exact first impulse through an `orekit-numerical*`
    backend followed by nonlinear corridor, fleet-distance, fuel and trust checks.
    """

    def __init__(
        self,
        propagator: Propagator,
        policy: MPCExecutionPolicy,
        *,
        deputy_id: str | None = None,
        state_steps: np.ndarray | None = None,
        impulse_step_m_s: float = 1.0e-3,
    ) -> None:
        self._propagator = propagator
        self._policy = policy
        self._deputy_id = deputy_id
        self._linearizer = FiniteDifferenceRoeLinearizationProvider(
            propagator,
            deputy_id=deputy_id,
            state_steps=state_steps,
            impulse_step_m_s=impulse_step_m_s,
        )

    def authorize_first_maneuver(
        self,
        request: PropagationRequest,
        constraints: ConstraintConfig,
        times_s: np.ndarray,
        maneuver_windows: np.ndarray,
    ) -> ManeuverAuthorityEvidence:
        if request.force_model.mode != ForceMode.VALIDATION:
            raise ValueError("MPC execution authority requires validation force mode")
        if request.maneuvers:
            raise ValueError("MPC authority baseline request must not contain scheduled maneuvers")

        requested_times = np.asarray(times_s, dtype=float)
        windows = np.asarray(maneuver_windows, dtype=bool)
        if requested_times.ndim != 1 or requested_times.size < 2:
            raise ValueError("times_s must contain at least two epochs")
        if windows.shape != (requested_times.size - 1,):
            raise ValueError("maneuver_windows must have one entry per control interval")

        deputy, reference = self._resolve_pair(request.satellites)
        initial_roe = damico_roe(reference.mean_orbit, deputy.mean_orbit)
        x0 = np.asarray(initial_roe.as_tuple(), dtype=float)

        a_matrices, b_matrices, disturbances = self._linearizer.linearize(request, requested_times)
        lower_state, upper_state = self._state_bounds(reference, constraints)
        solution = solve_impulsive_mpc(
            x0,
            a_matrices,
            b_matrices,
            disturbances,
            lower_state,
            upper_state,
            np.asarray(self._policy.max_abs_impulse_rtn_m_s, dtype=float),
            windows,
            (slice(0, 3),),
            target=np.asarray(self._policy.target_roe, dtype=float),
            w_tracking=self._policy.w_tracking,
            w_max=self._policy.w_max,
            eccentricity_vector_max=constraints.delta_e_max,
            inclination_vector_max=constraints.delta_i_max_rad,
        )

        first_impulse = np.asarray(solution.impulses[0, :3], dtype=float)
        component_nonzero = np.abs(first_impulse) > 1.0e-10
        if not np.any(component_nonzero):
            return self._evidence(
                authorized=False,
                reason="no-maneuver-required",
                deputy=deputy,
                reference=reference,
                maneuver=None,
                predicted_next=solution.states[1],
                replay_next=None,
                trust_ratio=None,
                min_distance=None,
                used_kg=0.0,
                remaining_kg=deputy.spacecraft.propellant_mass_kg,
                reserve_kg=deputy.spacecraft.propellant_mass_kg * constraints.propellant_reserve_fraction,
                replay=None,
                a_matrices=a_matrices,
                b_matrices=b_matrices,
                disturbances=disturbances,
                solution=solution,
            )

        if np.any(np.abs(first_impulse[component_nonzero]) < self._policy.min_impulse_bit_m_s):
            return self._evidence(
                authorized=False,
                reason="minimum-impulse-bit-violation",
                deputy=deputy,
                reference=reference,
                maneuver=None,
                predicted_next=solution.states[1],
                replay_next=None,
                trust_ratio=None,
                min_distance=None,
                used_kg=0.0,
                remaining_kg=deputy.spacecraft.propellant_mass_kg,
                reserve_kg=deputy.spacecraft.propellant_mass_kg * constraints.propellant_reserve_fraction,
                replay=None,
                a_matrices=a_matrices,
                b_matrices=b_matrices,
                disturbances=disturbances,
                solution=solution,
            )

        delta_v = float(np.linalg.norm(first_impulse))
        used_kg = propellant_used_kg(deputy.spacecraft.initial_mass_kg, delta_v, deputy.spacecraft.isp_s)
        remaining_kg = deputy.spacecraft.propellant_mass_kg - used_kg
        reserve_kg = deputy.spacecraft.propellant_mass_kg * constraints.propellant_reserve_fraction
        if remaining_kg < reserve_kg:
            return self._evidence(
                authorized=False,
                reason="propellant-reserve-violation",
                deputy=deputy,
                reference=reference,
                maneuver=None,
                predicted_next=solution.states[1],
                replay_next=None,
                trust_ratio=None,
                min_distance=None,
                used_kg=used_kg,
                remaining_kg=remaining_kg,
                reserve_kg=reserve_kg,
                replay=None,
                a_matrices=a_matrices,
                b_matrices=b_matrices,
                disturbances=disturbances,
                solution=solution,
            )

        maneuver = Maneuver(
            satellite_id=deputy.satellite_id,
            time_s=0.0,
            dv_rtn_m_s=(float(first_impulse[0]), float(first_impulse[1]), float(first_impulse[2])),
        )
        replay_request = request.model_copy(update={"maneuvers": (maneuver,)})
        replay = self._propagator.propagate(replay_request)
        authority_reason = self._replay_authority_reason(request, replay)
        if authority_reason is not None:
            return self._evidence(
                authorized=False,
                reason=authority_reason,
                deputy=deputy,
                reference=reference,
                maneuver=maneuver,
                predicted_next=solution.states[1],
                replay_next=None,
                trust_ratio=None,
                min_distance=None,
                used_kg=used_kg,
                remaining_kg=remaining_kg,
                reserve_kg=reserve_kg,
                replay=replay,
                a_matrices=a_matrices,
                b_matrices=b_matrices,
                disturbances=disturbances,
                solution=solution,
            )

        replay_times = np.asarray(replay.times_s, dtype=float)
        if replay_times.shape != requested_times.shape or not np.allclose(
            replay_times,
            requested_times,
            rtol=0.0,
            atol=1.0e-9,
        ):
            return self._evidence(
                authorized=False,
                reason="numerical-replay-grid-mismatch",
                deputy=deputy,
                reference=reference,
                maneuver=maneuver,
                predicted_next=solution.states[1],
                replay_next=None,
                trust_ratio=None,
                min_distance=None,
                used_kg=used_kg,
                remaining_kg=remaining_kg,
                reserve_kg=reserve_kg,
                replay=replay,
                a_matrices=a_matrices,
                b_matrices=b_matrices,
                disturbances=disturbances,
                solution=solution,
            )

        hard_reason, min_distance = self._nonlinear_constraint_reason(request, replay, constraints, deputy, reference)
        ref_history = replay.mean_orbits[reference.satellite_id]
        dep_history = replay.mean_orbits[deputy.satellite_id]
        replay_next = np.asarray(damico_roe(ref_history[1], dep_history[1]).as_tuple(), dtype=float)
        predicted_next = np.asarray(solution.states[1], dtype=float)
        difference = replay_next - predicted_next
        difference[1] = wrap_pi(float(difference[1]))
        tolerances = np.asarray(self._policy.trust_tolerances_roe, dtype=float)
        trust_ratio = float(np.max(np.abs(difference) / tolerances))

        if hard_reason is not None:
            return self._evidence(
                authorized=False,
                reason=hard_reason,
                deputy=deputy,
                reference=reference,
                maneuver=maneuver,
                predicted_next=predicted_next,
                replay_next=replay_next,
                trust_ratio=trust_ratio,
                min_distance=min_distance,
                used_kg=used_kg,
                remaining_kg=remaining_kg,
                reserve_kg=reserve_kg,
                replay=replay,
                a_matrices=a_matrices,
                b_matrices=b_matrices,
                disturbances=disturbances,
                solution=solution,
            )
        if trust_ratio > 1.0:
            return self._evidence(
                authorized=False,
                reason="linear-model-trust-violation",
                deputy=deputy,
                reference=reference,
                maneuver=maneuver,
                predicted_next=predicted_next,
                replay_next=replay_next,
                trust_ratio=trust_ratio,
                min_distance=min_distance,
                used_kg=used_kg,
                remaining_kg=remaining_kg,
                reserve_kg=reserve_kg,
                replay=replay,
                a_matrices=a_matrices,
                b_matrices=b_matrices,
                disturbances=disturbances,
                solution=solution,
            )

        return self._evidence(
            authorized=True,
            reason="authorized-by-numerical-replay",
            deputy=deputy,
            reference=reference,
            maneuver=maneuver,
            predicted_next=predicted_next,
            replay_next=replay_next,
            trust_ratio=trust_ratio,
            min_distance=min_distance,
            used_kg=used_kg,
            remaining_kg=remaining_kg,
            reserve_kg=reserve_kg,
            replay=replay,
            a_matrices=a_matrices,
            b_matrices=b_matrices,
            disturbances=disturbances,
            solution=solution,
        )

    def _resolve_pair(self, satellites: tuple[SatelliteSpec, ...]) -> tuple[SatelliteSpec, SatelliteSpec]:
        by_id = {sat.satellite_id: sat for sat in satellites}
        additional = [sat for sat in satellites if sat.role == "additional"]
        if self._deputy_id is None:
            if len(additional) != 1:
                raise ValueError("deputy_id is required unless exactly one additional satellite is present")
            deputy = additional[0]
        else:
            matches = [sat for sat in additional if sat.satellite_id == self._deputy_id]
            if len(matches) != 1:
                raise ValueError(f"unknown or non-additional deputy_id: {self._deputy_id}")
            deputy = matches[0]
        if deputy.reference_id is None:
            raise ValueError("controlled deputy requires reference_id")
        return deputy, by_id[deputy.reference_id]

    @staticmethod
    def _state_bounds(reference: SatelliteSpec, constraints: ConstraintConfig) -> tuple[np.ndarray, np.ndarray]:
        delta_a_low, delta_a_high = constraints.delta_a_bounds_m
        lower = np.asarray(
            [
                delta_a_low / reference.mean_orbit.a_m,
                -constraints.phase_corridor_rad,
                -constraints.delta_e_max,
                -constraints.delta_e_max,
                -constraints.delta_i_max_rad,
                -constraints.delta_i_max_rad,
            ],
            dtype=float,
        )
        upper = np.asarray(
            [
                delta_a_high / reference.mean_orbit.a_m,
                constraints.phase_corridor_rad,
                constraints.delta_e_max,
                constraints.delta_e_max,
                constraints.delta_i_max_rad,
                constraints.delta_i_max_rad,
            ],
            dtype=float,
        )
        return lower, upper

    @staticmethod
    def _replay_authority_reason(request: PropagationRequest, replay: PropagationResult) -> str | None:
        if not replay.backend.lower().startswith("orekit-numerical"):
            return "non-authoritative-replay-backend"
        if replay.force_model_fingerprint != request.force_model.fingerprint():
            return "replay-force-model-fingerprint-mismatch"
        expected_gravity = request.force_model.gravity_model.value if request.force_model.gravity_model else None
        if expected_gravity is None or replay.backend_metadata.get("gravity_model") != expected_gravity:
            return "replay-gravity-authority-mismatch"
        for key in ("orekit_version", "orekit_data_revision", "orekit_data_sha256"):
            if not replay.backend_metadata.get(key):
                return f"replay-missing-{key.replace('_', '-')}"
        return None

    @staticmethod
    def _nonlinear_constraint_reason(
        request: PropagationRequest,
        replay: PropagationResult,
        constraints: ConstraintConfig,
        deputy: SatelliteSpec,
        reference: SatelliteSpec,
    ) -> tuple[str | None, float]:
        ref_history = replay.mean_orbits[reference.satellite_id]
        dep_history = replay.mean_orbits[deputy.satellite_id]
        delta_a_low, delta_a_high = constraints.delta_a_bounds_m
        for ref_mean, dep_mean in zip(ref_history, dep_history, strict=True):
            relative: RelativeOrbitalElements = damico_roe(ref_mean, dep_mean)
            delta_a_m = relative.delta_a * ref_mean.a_m
            if delta_a_m < delta_a_low or delta_a_m > delta_a_high:
                return "replay-delta-a-corridor-violation", float("nan")
            if abs(relative.delta_lambda_rad) > constraints.phase_corridor_rad:
                return "replay-phase-corridor-violation", float("nan")
            if hypot(relative.delta_ex, relative.delta_ey) > constraints.delta_e_max:
                return "replay-eccentricity-corridor-violation", float("nan")
            if hypot(relative.delta_ix, relative.delta_iy) > constraints.delta_i_max_rad:
                return "replay-inclination-corridor-violation", float("nan")

        minimum_distance = float("inf")
        satellite_ids = [sat.satellite_id for sat in request.satellites]
        for left_id, right_id in combinations(satellite_ids, 2):
            left_history = replay.cartesian_states[left_id]
            right_history = replay.cartesian_states[right_id]
            for left, right in zip(left_history, right_history, strict=True):
                distance = float(np.linalg.norm(np.asarray(left.r_m) - np.asarray(right.r_m)))
                minimum_distance = min(minimum_distance, distance)
        if not np.isfinite(minimum_distance):
            raise RuntimeError("numerical replay produced no pairwise Cartesian distance evidence")
        if minimum_distance < constraints.min_pair_distance_m:
            return "replay-minimum-distance-violation", minimum_distance
        return None, minimum_distance

    @staticmethod
    def _array3(array: np.ndarray) -> tuple[tuple[tuple[float, ...], ...], ...]:
        return tuple(tuple(tuple(float(value) for value in row) for row in matrix) for matrix in array)

    @staticmethod
    def _array2(array: np.ndarray) -> tuple[tuple[float, ...], ...]:
        return tuple(tuple(float(value) for value in row) for row in array)

    def _evidence(
        self,
        *,
        authorized: bool,
        reason: str,
        deputy: SatelliteSpec,
        reference: SatelliteSpec,
        maneuver: Maneuver | None,
        predicted_next: np.ndarray | None,
        replay_next: np.ndarray | None,
        trust_ratio: float | None,
        min_distance: float | None,
        used_kg: float,
        remaining_kg: float,
        reserve_kg: float,
        replay: PropagationResult | None,
        a_matrices: np.ndarray,
        b_matrices: np.ndarray,
        disturbances: np.ndarray,
        solution: MPCSolution,
    ) -> ManeuverAuthorityEvidence:
        return ManeuverAuthorityEvidence(
            authorized=authorized,
            reason=reason,
            deputy_id=deputy.satellite_id,
            reference_id=reference.satellite_id,
            first_maneuver=maneuver,
            predicted_next_roe=(
                None if predicted_next is None else tuple(float(value) for value in np.asarray(predicted_next))
            ),
            replay_next_roe=None if replay_next is None else tuple(float(value) for value in np.asarray(replay_next)),
            trust_error_ratio=trust_ratio,
            replay_min_pair_distance_m=min_distance,
            propellant_used_kg=float(used_kg),
            propellant_remaining_kg=float(remaining_kg),
            required_reserve_kg=float(reserve_kg),
            replay_backend=None if replay is None else replay.backend,
            replay_backend_metadata={} if replay is None else dict(sorted(replay.backend_metadata.items())),
            a_matrices=self._array3(a_matrices),
            b_matrices=self._array3(b_matrices),
            disturbances=self._array2(disturbances),
            mpc_states=self._array2(solution.states),
            mpc_impulses=self._array2(solution.impulses),
            mpc_objective=float(solution.objective),
        )
