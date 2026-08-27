from __future__ import annotations

import hashlib
import json
from datetime import timedelta
from math import cos, sin
from pathlib import Path

import numpy as np
from pydantic import BaseModel, ConfigDict, Field

from constellation_control.adapters.orekit.adapter import OrekitSidecarPropagator
from constellation_control.analysis.campaign_hard_margins import reduce_trajectory_hard_margins
from constellation_control.analysis.fuel import propellant_used_kg
from constellation_control.application.run import load_scenario
from constellation_control.control.closed_loop import event_request_from_coast
from constellation_control.control.controllers import solve_impulsive_mpc
from constellation_control.control.optimized_policy import evaluate_optimized_correction_policy
from constellation_control.control.phase_target import roe_target_for_delta_u
from constellation_control.control.policies import CorrectionPolicyState
from constellation_control.domain.models import (
    ConstraintConfig,
    ForceMode,
    Maneuver,
    MeanOrbit,
    PropagationRequest,
    SatelliteSpec,
    ScenarioConfig,
)
from constellation_control.domain.protocols import Propagator
from constellation_control.dynamics.orbits import mean_to_classical, wrap_pi
from constellation_control.mean_elements.roe import (
    RelativeOrbitalElements,
    damico_roe,
    mean_from_damico_roe,
)
from constellation_control.optimization.operational_policy_search import (
    OperationalPolicyEvaluation,
    OperationalPolicyParameters,
)
from constellation_control.optimization.operations import ObjectiveDirection
from constellation_control.optimization.optimized_hybrid_execution import _scan_optimized_trigger
from constellation_control.preview.optimal_operations_profile import (
    PreviewOptimalOperationsStudyProfile,
    preflight_optimal_operations_study,
    scenario_constraints_identity,
)

JULIAN_YEAR_S = 365.25 * 86_400.0
_STATE_STEPS = np.asarray([1.0e-8] * 6, dtype=float)
_IMPULSE_STEP_M_S = 1.0e-4


class PreviewScreeningCampaignEvidence(BaseModel):
    """Physical but explicitly non-authoritative DSST policy-campaign evidence."""

    model_config = ConfigDict(frozen=True)

    candidate_id: str
    trigger_fraction: float
    target_fraction: float
    screening_backend: str
    screening_force_model_fingerprint: str
    elapsed_time_s: float = Field(gt=0.0)
    correction_count: int = Field(ge=0)
    cumulative_delta_v_m_s: float = Field(ge=0.0)
    cumulative_propellant_used_kg: float = Field(ge=0.0)
    phase_corridor_margin_rad: float
    minimum_fleet_distance_margin_m: float
    propellant_reserve_margin_kg: float
    termination_reason: str


class _DesignFiniteDifferenceRoeLinearizer:
    """DSST-only local ROE linearization for screening; never an authority source."""

    def __init__(self, propagator: Propagator, deputy_id: str) -> None:
        self._propagator = propagator
        self._deputy_id = deputy_id

    def linearize(
        self,
        request: PropagationRequest,
        times_s: np.ndarray,
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        if request.force_model.mode != ForceMode.DESIGN:
            raise ValueError("screening ROE linearization requires DESIGN force mode")
        if request.maneuvers:
            raise ValueError("screening linearization baseline request cannot contain maneuvers")
        times = np.asarray(times_s, dtype=float)
        if times.ndim != 1 or times.size < 2 or times[0] != 0.0:
            raise ValueError("screening linearization times must start at zero")
        if np.any(~np.isfinite(times)) or np.any(np.diff(times) <= 0.0):
            raise ValueError("screening linearization times must be finite and strictly increasing")

        baseline = self._propagator.propagate(request)
        if not baseline.backend.startswith("orekit-dsst"):
            raise ValueError("screening linearization requires Orekit DSST backend")
        if baseline.force_model_fingerprint != request.force_model.fingerprint():
            raise ValueError("screening linearization force fingerprint mismatch")
        actual_times = np.asarray(baseline.times_s, dtype=float)
        if actual_times.shape != times.shape or not np.allclose(actual_times, times, rtol=0.0, atol=1.0e-9):
            raise ValueError("screening linearization grid does not match requested authority grid")

        by_id = {sat.satellite_id: sat for sat in request.satellites}
        deputy = by_id[self._deputy_id]
        if deputy.reference_id is None or deputy.reference_id not in by_id:
            raise ValueError("screening deputy requires a valid reference_id")
        reference = by_id[deputy.reference_id]
        ref_history = baseline.mean_orbits[reference.satellite_id]
        dep_history = baseline.mean_orbits[deputy.satellite_id]

        horizon = times.size - 1
        a_matrices = np.empty((horizon, 6, 6), dtype=float)
        b_matrices = np.empty((horizon, 6, 3), dtype=float)
        disturbances = np.empty((horizon, 6), dtype=float)

        for index in range(horizon):
            time_s = float(times[index])
            dt_s = float(times[index + 1] - times[index])
            ref_now = ref_history[index]
            dep_now = dep_history[index]
            current = damico_roe(ref_now, dep_now)
            current_vector = self._vector(current)
            baseline_next = self._vector(damico_roe(ref_history[index + 1], dep_history[index + 1]))
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

            for component, step in enumerate(_STATE_STEPS):
                plus = self._perturb(current, component, float(step))
                minus = self._perturb(current, component, -float(step))
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
                a_matrices[index, :, component] = self._difference(plus_next, minus_next) / (2.0 * step)

            for component in range(3):
                plus_dv = [0.0, 0.0, 0.0]
                minus_dv = [0.0, 0.0, 0.0]
                plus_dv[component] = _IMPULSE_STEP_M_S
                minus_dv[component] = -_IMPULSE_STEP_M_S
                plus_next = self._next_roe(
                    local_request,
                    local_reference,
                    local_deputy,
                    dep_now,
                    tuple(plus_dv),
                )
                minus_next = self._next_roe(
                    local_request,
                    local_reference,
                    local_deputy,
                    dep_now,
                    tuple(minus_dv),
                )
                b_matrices[index, :, component] = self._difference(plus_next, minus_next) / (
                    2.0 * _IMPULSE_STEP_M_S
                )

            disturbances[index] = baseline_next - a_matrices[index] @ current_vector
            disturbances[index, 1] = wrap_pi(float(disturbances[index, 1]))
        return a_matrices, b_matrices, disturbances

    def _next_roe(
        self,
        request: PropagationRequest,
        reference: SatelliteSpec,
        deputy: SatelliteSpec,
        deputy_mean: MeanOrbit,
        dv_rtn_m_s: tuple[float, float, float] | None,
    ) -> np.ndarray:
        maneuvers: tuple[Maneuver, ...] = ()
        if dv_rtn_m_s is not None:
            maneuvers = (Maneuver(satellite_id=deputy.satellite_id, time_s=0.0, dv_rtn_m_s=dv_rtn_m_s),)
        perturbed = request.model_copy(
            update={
                "satellites": (
                    reference,
                    deputy.model_copy(update={"mean_orbit": deputy_mean}),
                ),
                "maneuvers": maneuvers,
            }
        )
        result = self._propagator.propagate(perturbed)
        if not result.backend.startswith("orekit-dsst"):
            raise ValueError("screening finite difference escaped DSST backend")
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
    def _perturb(
        relative: RelativeOrbitalElements,
        component: int,
        increment: float,
    ) -> RelativeOrbitalElements:
        values = list(relative.as_tuple())
        values[component] += increment
        if component == 1:
            values[component] = wrap_pi(values[component])
        return RelativeOrbitalElements(*values)


def _initial_request(scenario: ScenarioConfig, seed: int) -> PropagationRequest:
    return PropagationRequest(
        scenario_id=scenario.scenario_id,
        epoch=scenario.epoch,
        frame=scenario.frame,
        time_scale=scenario.time_scale,
        satellites=scenario.constellation.satellites,
        maneuvers=(),
        duration_s=scenario.duration_s,
        output_step_s=scenario.output_step_s,
        force_model=scenario.force_model,
        integrator=scenario.integrator,
        seed=seed,
    )


def _request_from_result_sample(
    source: PropagationRequest,
    result: object,
    sample_index: int,
) -> PropagationRequest:
    from constellation_control.domain.models import PropagationResult

    if not isinstance(result, PropagationResult):
        raise TypeError("screening continuation requires PropagationResult")
    rebuilt = []
    for satellite in source.satellites:
        rebuilt.append(
            satellite.model_copy(update={"mean_orbit": result.mean_orbits[satellite.satellite_id][sample_index]})
        )
    return source.model_copy(
        update={
            "epoch": source.epoch + timedelta(seconds=float(result.times_s[sample_index])),
            "satellites": tuple(rebuilt),
            "maneuvers": (),
        }
    )


def _state_bounds(reference: SatelliteSpec, constraints: ConstraintConfig) -> tuple[np.ndarray, np.ndarray]:
    delta_a_low, delta_a_high = constraints.delta_a_bounds_m
    lower = np.asarray(
        [
            delta_a_low / reference.mean_orbit.a_m,
            -np.inf,
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
            np.inf,
            constraints.delta_e_max,
            constraints.delta_e_max,
            constraints.delta_i_max_rad,
            constraints.delta_i_max_rad,
        ],
        dtype=float,
    )
    return lower, upper


def _screening_impulse(
    propagator: Propagator,
    request: PropagationRequest,
    scenario: ScenarioConfig,
    profile: PreviewOptimalOperationsStudyProfile,
    parameters: OperationalPolicyParameters,
    boundary_sign: int,
) -> tuple[float, float, float]:
    times = np.asarray(profile.authority_times_s, dtype=float)
    windows = np.asarray(profile.maneuver_windows, dtype=bool)
    linearizer = _DesignFiniteDifferenceRoeLinearizer(propagator, profile.controlled_deputy_id)
    a_matrices, b_matrices, disturbances = linearizer.linearize(request, times)
    by_id = {sat.satellite_id: sat for sat in request.satellites}
    deputy = by_id[profile.controlled_deputy_id]
    if deputy.reference_id is None:
        raise ValueError("screening controlled deputy requires reference_id")
    reference = by_id[deputy.reference_id]
    current = damico_roe(reference.mean_orbit, deputy.mean_orbit)
    target_delta_u = parameters.guidance_target_delta_u_rad(boundary_sign, scenario.constraints.phase_corridor_rad)
    target = roe_target_for_delta_u(reference.mean_orbit, current, target_delta_u)
    target_vector = np.asarray(target.as_tuple(), dtype=float)
    x0 = np.asarray(current.as_tuple(), dtype=float)
    lower, upper = _state_bounds(reference, scenario.constraints)
    inclination = mean_to_classical(reference.mean_orbit).i_rad
    if abs(sin(inclination)) < 1.0e-8:
        raise ValueError("screening mean-phase MPC corridor is ill-conditioned near equatorial inclination")
    solution = solve_impulsive_mpc(
        x0,
        a_matrices,
        b_matrices,
        disturbances,
        lower,
        upper,
        np.asarray(profile.execution_policy.max_abs_impulse_rtn_m_s, dtype=float),
        windows,
        (slice(0, 3),),
        target=target_vector,
        w_tracking=profile.execution_policy.w_tracking,
        w_max=profile.execution_policy.w_max,
        eccentricity_vector_max=scenario.constraints.delta_e_max,
        inclination_vector_max=scenario.constraints.delta_i_max_rad,
        mean_phase_cot_i=cos(inclination) / sin(inclination),
        mean_phase_half_width_rad=scenario.constraints.phase_corridor_rad,
    )
    impulse = np.asarray(solution.impulses[0, :3], dtype=float)
    return float(impulse[0]), float(impulse[1]), float(impulse[2])


def _candidate_id(parameters: OperationalPolicyParameters) -> str:
    raw = json.dumps(
        {
            "trigger_fraction": parameters.trigger_fraction,
            "target_fraction": parameters.target_fraction,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return f"dsst-{hashlib.sha256(raw.encode()).hexdigest()[:16]}"


def _validate_screening_compatibility(
    screening: ScenarioConfig,
    validation: ScenarioConfig,
    profile: PreviewOptimalOperationsStudyProfile,
) -> None:
    if screening.force_model.mode != ForceMode.DESIGN:
        raise ValueError("operational policy screening requires DESIGN force mode")
    if not screening.orekit_sidecar_url:
        raise ValueError("operational policy screening requires Orekit sidecar URL")
    checks = (
        ("epoch", screening.epoch, validation.epoch),
        ("frame", screening.frame, validation.frame),
        ("time scale", screening.time_scale, validation.time_scale),
        ("constraints", scenario_constraints_identity(screening), scenario_constraints_identity(validation)),
    )
    for label, actual, expected in checks:
        if actual != expected:
            raise ValueError(f"screening/validation {label} mismatch")
    screening_satellites = tuple(item.model_dump(mode="json") for item in screening.constellation.satellites)
    validation_satellites = tuple(item.model_dump(mode="json") for item in validation.constellation.satellites)
    if screening_satellites != validation_satellites:
        raise ValueError("screening/validation initial constellation identity mismatch")
    if profile.controlled_deputy_id not in {sat.satellite_id for sat in screening.constellation.satellites}:
        raise ValueError("screening scenario does not contain controlled deputy")


def run_dsst_screening_campaign(
    screening_scenario_path: Path,
    validation_scenario_path: Path,
    profile: PreviewOptimalOperationsStudyProfile,
    parameters: OperationalPolicyParameters,
    *,
    propagator: Propagator | None = None,
) -> PreviewScreeningCampaignEvidence:
    """Evaluate one policy on real Orekit DSST propagation without conferring authority."""

    preflight_optimal_operations_study(validation_scenario_path, profile)
    screening = load_scenario(screening_scenario_path)
    validation = load_scenario(validation_scenario_path)
    _validate_screening_compatibility(screening, validation, profile)
    resolved = propagator or OrekitSidecarPropagator(screening.orekit_sidecar_url or "")
    candidate_id = _candidate_id(parameters)
    current = _initial_request(screening, profile.seed)
    by_id = {sat.satellite_id: sat for sat in current.satellites}
    deputy = by_id[profile.controlled_deputy_id]
    if deputy.reference_id is None:
        raise ValueError("screening controlled deputy requires reference_id")
    reference_id = deputy.reference_id
    state = CorrectionPolicyState()
    elapsed = 0.0
    correction_count = 0
    cumulative_dv = 0.0
    cumulative_propellant = 0.0
    current_propellant = deputy.spacecraft.propellant_mass_kg
    required_reserve = deputy.spacecraft.propellant_mass_kg * screening.constraints.propellant_reserve_fraction
    phase_margin = float("inf")
    fleet_margin = float("inf")
    backend: str | None = None
    fingerprint: str | None = None
    pending_boundary_sign: int | None = None

    initial_delta_u = wrap_pi(
        mean_to_classical(deputy.mean_orbit).mean_anomaly_rad
        + mean_to_classical(deputy.mean_orbit).argp_rad
        - mean_to_classical(by_id[reference_id].mean_orbit).mean_anomaly_rad
        - mean_to_classical(by_id[reference_id].mean_orbit).argp_rad
    )
    initial_decision, state = evaluate_optimized_correction_policy(
        candidate_id,
        parameters,
        initial_delta_u,
        screening.constraints.phase_corridor_rad,
        state,
    )
    if initial_decision.decision.correction_requested:
        pending_boundary_sign = initial_decision.decision.crossed_boundary_sign

    while elapsed < profile.campaign_horizon_s - 1.0e-9:
        remaining = profile.campaign_horizon_s - elapsed
        local_horizon = min(profile.coast_horizon_s, remaining)
        current = current.model_copy(
            update={
                "duration_s": local_horizon,
                "output_step_s": min(profile.coast_output_step_s, local_horizon),
                "maneuvers": (),
            }
        )
        if pending_boundary_sign is not None:
            if correction_count >= profile.max_corrections:
                termination = "screening-max-corrections-reached"
                break
            authority_duration = float(profile.authority_times_s[-1])
            authority_request = current.model_copy(
                update={
                    "duration_s": authority_duration,
                    "output_step_s": float(profile.authority_times_s[1] - profile.authority_times_s[0]),
                    "maneuvers": (),
                }
            )
            impulse = _screening_impulse(
                resolved,
                authority_request,
                screening,
                profile,
                parameters,
                pending_boundary_sign,
            )
            magnitude = float(np.linalg.norm(np.asarray(impulse, dtype=float)))
            nonzero = [abs(component) for component in impulse if abs(component) > 1.0e-10]
            if nonzero and min(nonzero) < profile.execution_policy.min_impulse_bit_m_s:
                termination = "screening-minimum-impulse-bit-violation"
                break
            if magnitude <= 1.0e-10:
                termination = "screening-no-maneuver-required"
                break
            used = propellant_used_kg(
                deputy.spacecraft.initial_mass_kg - cumulative_propellant,
                magnitude,
                deputy.spacecraft.isp_s,
            )
            if current_propellant - used < required_reserve:
                termination = "screening-propellant-reserve-violation"
                current_propellant -= used
                cumulative_propellant += used
                cumulative_dv += magnitude
                break
            current_propellant -= used
            cumulative_propellant += used
            cumulative_dv += magnitude
            correction_count += 1
            current = current.model_copy(
                update={
                    "duration_s": local_horizon,
                    "output_step_s": min(profile.coast_output_step_s, local_horizon),
                    "maneuvers": (
                        Maneuver(
                            satellite_id=profile.controlled_deputy_id,
                            time_s=0.0,
                            dv_rtn_m_s=impulse,
                        ),
                    ),
                }
            )
            pending_boundary_sign = None

        result = resolved.propagate(current)
        if not result.backend.startswith("orekit-dsst"):
            raise ValueError("operational policy screening escaped Orekit DSST backend")
        if result.force_model_fingerprint != screening.force_model.fingerprint():
            raise ValueError("operational policy screening force fingerprint mismatch")
        backend = result.backend
        fingerprint = result.force_model_fingerprint
        margins = reduce_trajectory_hard_margins(
            result,
            screening.constraints,
            reference_id=reference_id,
            deputy_id=profile.controlled_deputy_id,
        )
        phase_margin = min(phase_margin, margins.phase_corridor_margin_rad)
        if margins.minimum_fleet_distance_margin_m is None:
            raise ValueError("screening campaign requires fleet-distance evidence")
        fleet_margin = min(fleet_margin, margins.minimum_fleet_distance_margin_m)
        scan, optimized = _scan_optimized_trigger(
            result,
            candidate_id=candidate_id,
            parameters=parameters,
            reference_id=reference_id,
            deputy_id=profile.controlled_deputy_id,
            hard_corridor_half_width_rad=screening.constraints.phase_corridor_rad,
            initial_state=state,
            output_step_s=current.output_step_s,
        )
        state = scan.final_policy_state
        if scan.event is None:
            elapsed += float(result.times_s[-1])
            current = _request_from_result_sample(current, result, -1)
            if elapsed >= profile.campaign_horizon_s - 1.0e-9:
                termination = "screening-campaign-horizon-reached"
                break
            continue
        event = scan.event
        if optimized is None or event.decision.crossed_boundary_sign is None:
            raise ValueError("screening optimized trigger lacks decision evidence")
        elapsed += event.time_s
        current = event_request_from_coast(
            current,
            event,
            duration_s=float(profile.authority_times_s[-1]),
            output_step_s=float(profile.authority_times_s[1] - profile.authority_times_s[0]),
        )
        pending_boundary_sign = event.decision.crossed_boundary_sign
    else:
        termination = "screening-campaign-horizon-reached"

    if backend is None or fingerprint is None:
        raise ValueError("screening campaign produced no DSST propagation evidence")
    return PreviewScreeningCampaignEvidence(
        candidate_id=candidate_id,
        trigger_fraction=parameters.trigger_fraction,
        target_fraction=parameters.target_fraction,
        screening_backend=backend,
        screening_force_model_fingerprint=fingerprint,
        elapsed_time_s=max(elapsed, 1.0e-12),
        correction_count=correction_count,
        cumulative_delta_v_m_s=cumulative_dv,
        cumulative_propellant_used_kg=cumulative_propellant,
        phase_corridor_margin_rad=phase_margin,
        minimum_fleet_distance_margin_m=fleet_margin,
        propellant_reserve_margin_kg=current_propellant - required_reserve,
        termination_reason=termination,
    )


def _raw_objective_value(name: str, unit: str, evidence: PreviewScreeningCampaignEvidence) -> float:
    if name == "cumulative_delta_v" and unit == "m/s":
        return evidence.cumulative_delta_v_m_s
    if name == "cumulative_propellant" and unit == "kg":
        return evidence.cumulative_propellant_used_kg
    if name == "correction_count" and unit == "events":
        return float(evidence.correction_count)
    if name == "delta_v_rate" and unit == "m/s/Julian-year":
        return evidence.cumulative_delta_v_m_s / evidence.elapsed_time_s * JULIAN_YEAR_S
    if name == "propellant_rate" and unit == "kg/Julian-year":
        return evidence.cumulative_propellant_used_kg / evidence.elapsed_time_s * JULIAN_YEAR_S
    if name == "correction_frequency" and unit == "events/Julian-year":
        return evidence.correction_count / evidence.elapsed_time_s * JULIAN_YEAR_S
    if name == "projected_lifetime" and unit == "Julian-year":
        raise ValueError(
            "projected_lifetime is unavailable as a finite screening objective without an explicit finite-rate bound"
        )
    raise ValueError(f"unsupported DSST screening objective: {name} [{unit}]")


def _hard_margin(name: str, unit: str, evidence: PreviewScreeningCampaignEvidence) -> float:
    if name == "phase_corridor_margin" and unit == "rad":
        return evidence.phase_corridor_margin_rad
    if name == "minimum_fleet_distance_margin" and unit == "m":
        return evidence.minimum_fleet_distance_margin_m
    if name == "propellant_reserve_margin" and unit == "kg":
        return evidence.propellant_reserve_margin_kg
    raise ValueError(f"unsupported DSST screening hard constraint: {name} [{unit}]")


def build_real_dsst_screening_evaluator(
    screening_scenario_path: Path,
    validation_scenario_path: Path,
    profile: PreviewOptimalOperationsStudyProfile,
    *,
    propagator: Propagator | None = None,
):
    """Build the release evaluator used by policy search; no synthetic score path exists here."""

    def evaluate(parameters: OperationalPolicyParameters) -> OperationalPolicyEvaluation:
        evidence = run_dsst_screening_campaign(
            screening_scenario_path,
            validation_scenario_path,
            profile,
            parameters,
            propagator=propagator,
        )
        raw_values = tuple(
            _raw_objective_value(item.name, item.unit, evidence) for item in profile.objectives
        )
        objective_scores = tuple(
            value if definition.direction == ObjectiveDirection.MINIMIZE else -value
            for value, definition in zip(raw_values, profile.objectives, strict=True)
        )
        hard_margins = tuple(
            _hard_margin(item.name, item.unit, evidence) for item in profile.hard_constraints
        )
        metrics = {
            "screening_correction_count": float(evidence.correction_count),
            "screening_cumulative_delta_v_m_s": evidence.cumulative_delta_v_m_s,
            "screening_cumulative_propellant_used_kg": evidence.cumulative_propellant_used_kg,
            "screening_elapsed_time_s": evidence.elapsed_time_s,
            "screening_phase_corridor_margin_rad": evidence.phase_corridor_margin_rad,
            "screening_minimum_fleet_distance_margin_m": evidence.minimum_fleet_distance_margin_m,
            "screening_propellant_reserve_margin_kg": evidence.propellant_reserve_margin_kg,
        }
        for index, value in enumerate(raw_values):
            metrics[f"screening_objective_raw_{index}"] = value
        return OperationalPolicyEvaluation(
            objectives=objective_scores,
            hard_margins=hard_margins,
            metrics=metrics,
        )

    return evaluate
