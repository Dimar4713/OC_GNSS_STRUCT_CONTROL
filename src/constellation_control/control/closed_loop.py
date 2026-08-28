from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from math import isfinite

import numpy as np

from constellation_control.analysis.relative_operations import mean_phase_rad
from constellation_control.control.policies import (
    CorrectionDecision,
    CorrectionPolicy,
    CorrectionPolicyState,
    evaluate_correction_policy,
)
from constellation_control.control.transition import (
    AuthoritativeTransitionSnapshot,
    TransitionSpacecraftState,
)
from constellation_control.domain.models import PropagationRequest, PropagationResult, SatelliteSpec
from constellation_control.dynamics.orbits import wrap_pi


@dataclass(frozen=True)
class CoastPolicyEvent:
    sample_index: int
    time_s: float
    grid_resolution_s: float
    timing_semantics: str
    decision: CorrectionDecision
    state_before: CorrectionPolicyState
    state_after: CorrectionPolicyState
    spacecraft_states: tuple[TransitionSpacecraftState, ...]
    source_backend: str
    source_force_model_fingerprint: str


@dataclass(frozen=True)
class CoastScanResult:
    event: CoastPolicyEvent | None
    final_policy_state: CorrectionPolicyState
    samples_evaluated: int


def _validate_local_horizon(duration_s: float, output_step_s: float) -> tuple[float, float]:
    duration = float(duration_s)
    step = float(output_step_s)
    if not isfinite(duration) or duration <= 0.0:
        raise ValueError("duration_s must be finite and positive")
    if not isfinite(step) or step <= 0.0:
        raise ValueError("output_step_s must be finite and positive")
    return duration, step


def _states_by_id(
    states: tuple[TransitionSpacecraftState, ...],
) -> dict[str, TransitionSpacecraftState]:
    by_id = {state.satellite_id: state for state in states}
    if len(by_id) != len(states):
        raise ValueError("transition spacecraft state ids must be unique")
    return by_id


def _request_from_absolute_states(
    source: PropagationRequest,
    states: tuple[TransitionSpacecraftState, ...],
    *,
    controlled_satellite_id: str | None,
    controlled_propellant_remaining_kg: float | None,
    epoch_offset_s: float,
    duration_s: float,
    output_step_s: float,
) -> PropagationRequest:
    duration, step = _validate_local_horizon(duration_s, output_step_s)
    if not isfinite(epoch_offset_s) or epoch_offset_s < 0.0:
        raise ValueError("epoch_offset_s must be finite and non-negative")
    state_by_id = _states_by_id(states)
    source_ids = {sat.satellite_id for sat in source.satellites}
    if set(state_by_id) != source_ids:
        raise ValueError("absolute state snapshot must contain exactly the source spacecraft ids")

    fingerprint = source.force_model.fingerprint()
    rebuilt: list[SatelliteSpec] = []
    for satellite in source.satellites:
        state = state_by_id[satellite.satellite_id]
        if state.mean_orbit.definition.force_model_fingerprint != fingerprint:
            raise ValueError(
                f"continuation mean state for {satellite.satellite_id} has mismatched force-model fingerprint"
            )
        spacecraft = satellite.spacecraft
        if satellite.satellite_id == controlled_satellite_id:
            if controlled_propellant_remaining_kg is None:
                raise ValueError("controlled continuation requires propellant remaining")
            if not isfinite(controlled_propellant_remaining_kg) or controlled_propellant_remaining_kg < 0.0:
                raise ValueError("controlled propellant remaining must be finite and non-negative")
            spacecraft = spacecraft.model_copy(
                update={"propellant_mass_kg": float(controlled_propellant_remaining_kg)}
            )
        rebuilt.append(
            satellite.model_copy(
                update={
                    "mean_orbit": state.mean_orbit,
                    "spacecraft": spacecraft,
                }
            )
        )

    return source.model_copy(
        update={
            "epoch": source.epoch + timedelta(seconds=float(epoch_offset_s)),
            "satellites": tuple(rebuilt),
            "maneuvers": (),
            "duration_s": duration,
            "output_step_s": step,
        }
    )


def continuation_request_from_snapshot(
    source: PropagationRequest,
    snapshot: AuthoritativeTransitionSnapshot,
    *,
    duration_s: float,
    output_step_s: float,
) -> PropagationRequest:
    """Advance one authorized receding-horizon interval using the exact replay snapshot."""

    if snapshot.force_model_fingerprint != source.force_model.fingerprint():
        raise ValueError("transition snapshot force-model fingerprint does not match source request")
    if snapshot.frame != source.frame or snapshot.time_scale != source.time_scale:
        raise ValueError("transition snapshot frame/time scale does not match source request")
    if snapshot.integrator != source.integrator:
        raise ValueError("transition snapshot integrator does not match source request")
    return _request_from_absolute_states(
        source,
        snapshot.spacecraft_states,
        controlled_satellite_id=snapshot.controlled_satellite_id,
        controlled_propellant_remaining_kg=snapshot.controlled_propellant_remaining_kg,
        epoch_offset_s=snapshot.continuation_time_s,
        duration_s=duration_s,
        output_step_s=output_step_s,
    )


def _sample_states(result: PropagationResult, index: int) -> tuple[TransitionSpacecraftState, ...]:
    states: list[TransitionSpacecraftState] = []
    for satellite_id in sorted(result.mean_orbits):
        mean_history = result.mean_orbits[satellite_id]
        if len(mean_history) <= index:
            raise ValueError(f"coast result mean history is too short for {satellite_id}")
        cart_history = result.cartesian_states.get(satellite_id)
        cartesian = None
        if cart_history is not None:
            if len(cart_history) <= index:
                raise ValueError(f"coast result Cartesian history is too short for {satellite_id}")
            cartesian = cart_history[index]
        states.append(
            TransitionSpacecraftState(
                satellite_id=satellite_id,
                mean_orbit=mean_history[index],
                cartesian_state=cartesian,
            )
        )
    return tuple(states)


def scan_coast_for_policy_event(
    result: PropagationResult,
    *,
    reference_id: str,
    deputy_id: str,
    policy: CorrectionPolicy,
    corridor_half_width_rad: float,
    initial_state: CorrectionPolicyState,
    output_step_s: float,
) -> CoastScanResult:
    """Return the first correction request observed on the authoritative coast output grid."""

    step = float(output_step_s)
    if not isfinite(step) or step <= 0.0:
        raise ValueError("output_step_s must be finite and positive")
    times = np.asarray(result.times_s, dtype=float)
    if times.ndim != 1 or times.size == 0 or np.any(~np.isfinite(times)):
        raise ValueError("coast result times_s must be a non-empty finite one-dimensional grid")
    if abs(float(times[0])) > 1.0e-9:
        raise ValueError("coast result time grid must start at zero")
    intervals = np.diff(times)
    if np.any(intervals <= 0.0):
        raise ValueError("coast result times_s must be strictly increasing")
    if intervals.size and np.any(intervals > step + 1.0e-9):
        raise ValueError("coast result time intervals exceed declared output_step_s")
    if reference_id not in result.mean_orbits or deputy_id not in result.mean_orbits:
        raise ValueError("coast result does not contain the requested reference/deputy pair")
    ref_history = result.mean_orbits[reference_id]
    dep_history = result.mean_orbits[deputy_id]
    if len(ref_history) != times.size or len(dep_history) != times.size:
        raise ValueError("coast mean histories must match the result time grid")

    state = initial_state
    for index, (time_s, ref_mean, dep_mean) in enumerate(
        zip(times, ref_history, dep_history, strict=True)
    ):
        delta_u = wrap_pi(mean_phase_rad(dep_mean) - mean_phase_rad(ref_mean))
        state_before = state
        decision, state = evaluate_correction_policy(
            policy,
            delta_u,
            corridor_half_width_rad,
            state,
        )
        if decision.correction_requested:
            return CoastScanResult(
                event=CoastPolicyEvent(
                    sample_index=index,
                    time_s=float(time_s),
                    grid_resolution_s=step,
                    timing_semantics="first correction request on authoritative propagation output grid; no interpolation",
                    decision=decision,
                    state_before=state_before,
                    state_after=state,
                    spacecraft_states=_sample_states(result, index),
                    source_backend=result.backend,
                    source_force_model_fingerprint=result.force_model_fingerprint,
                ),
                final_policy_state=state,
                samples_evaluated=index + 1,
            )
    return CoastScanResult(
        event=None,
        final_policy_state=state,
        samples_evaluated=int(times.size),
    )


def event_request_from_coast(
    source: PropagationRequest,
    event: CoastPolicyEvent,
    *,
    duration_s: float,
    output_step_s: float,
) -> PropagationRequest:
    """Build the maneuver-sizing request directly from the coast event sample state."""

    if event.source_force_model_fingerprint != source.force_model.fingerprint():
        raise ValueError("coast event force-model fingerprint does not match source request")
    return _request_from_absolute_states(
        source,
        event.spacecraft_states,
        controlled_satellite_id=None,
        controlled_propellant_remaining_kg=None,
        epoch_offset_s=event.time_s,
        duration_s=duration_s,
        output_step_s=output_step_s,
    )
