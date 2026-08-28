from __future__ import annotations

from dataclasses import dataclass, replace

import numpy as np

from constellation_control.control.execution import (
    MPCExecutionPolicy,
    ManeuverAuthorityEvidence,
    RecedingHorizonMPCController,
)
from constellation_control.control.phase_target import delta_u_from_damico_roe, roe_target_for_delta_u
from constellation_control.control.policies import CorrectionDecision
from constellation_control.control.transition import (
    AuthoritativeTransitionSnapshot,
    CorrectionResourceRecord,
    TransitionSpacecraftState,
)
from constellation_control.domain.models import (
    ConstraintConfig,
    PropagationRequest,
    PropagationResult,
    SatelliteSpec,
)
from constellation_control.domain.protocols import Propagator
from constellation_control.dynamics.orbits import wrap_pi
from constellation_control.mean_elements.roe import RelativeOrbitalElements, damico_roe


@dataclass(frozen=True)
class PolicyExecutionTarget:
    deputy_id: str
    reference_id: str
    current_roe: tuple[float, float, float, float, float, float]
    current_delta_u_rad: float
    guidance_target_delta_u_rad: float
    adapted_target_roe: tuple[float, float, float, float, float, float]
    execution_policy: MPCExecutionPolicy


@dataclass(frozen=True)
class PolicyManeuverAttemptEvidence:
    decision: CorrectionDecision
    sizing_attempted: bool
    target: PolicyExecutionTarget | None
    authority: ManeuverAuthorityEvidence | None
    transition: AuthoritativeTransitionSnapshot | None = None


@dataclass(frozen=True)
class _CapturedPropagation:
    request: PropagationRequest
    result: PropagationResult


class _ReplayCapturePropagator:
    """Pass-through propagator retaining exact in-memory results for later evidence extraction."""

    def __init__(self, delegate: Propagator) -> None:
        self._delegate = delegate
        self.calls: list[_CapturedPropagation] = []

    def propagate(self, request: PropagationRequest) -> PropagationResult:
        result = self._delegate.propagate(request)
        self.calls.append(_CapturedPropagation(request=request, result=result))
        return result

    def authorizing_replay(self, authority: ManeuverAuthorityEvidence) -> _CapturedPropagation:
        maneuver = authority.first_maneuver
        if not authority.authorized or maneuver is None or authority.replay_backend is None:
            raise ValueError("authorizing replay is available only for an authorized maneuver")
        matches = [
            call
            for call in self.calls
            if call.request.maneuvers == (maneuver,)
            and call.result.backend == authority.replay_backend
            and call.result.force_model_fingerprint == call.request.force_model.fingerprint()
        ]
        if not matches:
            raise RuntimeError("authorized maneuver replay was not captured from the execution authority")
        # Finite-difference linearization also uses propagation calls and can use
        # one synthetic impulse. The actual authority replay occurs after all
        # linearization calls, so the last exact maneuver/backend match is the
        # replay that produced ManeuverAuthorityEvidence.
        return matches[-1]


def _resolve_control_pair(
    satellites: tuple[SatelliteSpec, ...],
    deputy_id: str | None,
) -> tuple[SatelliteSpec, SatelliteSpec]:
    by_id = {sat.satellite_id: sat for sat in satellites}
    additional = [sat for sat in satellites if sat.role == "additional"]
    if deputy_id is None:
        if len(additional) != 1:
            raise ValueError("deputy_id is required unless exactly one additional satellite is present")
        deputy = additional[0]
    else:
        matches = [sat for sat in additional if sat.satellite_id == deputy_id]
        if len(matches) != 1:
            raise ValueError(f"unknown or non-additional deputy_id: {deputy_id}")
        deputy = matches[0]
    if deputy.reference_id is None:
        raise ValueError("controlled deputy requires reference_id")
    try:
        reference = by_id[deputy.reference_id]
    except KeyError as exc:
        raise ValueError(f"unknown reference_id: {deputy.reference_id}") from exc
    return deputy, reference


def build_policy_execution_target(
    request: PropagationRequest,
    constraints: ConstraintConfig,
    decision: CorrectionDecision,
    base_policy: MPCExecutionPolicy,
    *,
    deputy_id: str | None = None,
) -> PolicyExecutionTarget:
    """Adapt a policy Δu guidance request into the existing D'Amico ROE execution target."""

    if not decision.correction_requested or decision.guidance_target_delta_u_rad is None:
        raise ValueError("policy execution target requires a correction decision with guidance target")
    if not np.isclose(
        decision.corridor_half_width_rad,
        constraints.phase_corridor_rad,
        rtol=0.0,
        atol=1.0e-12,
    ):
        raise ValueError("policy decision corridor does not match execution constraints")

    deputy, reference = _resolve_control_pair(request.satellites, deputy_id)
    current: RelativeOrbitalElements = damico_roe(reference.mean_orbit, deputy.mean_orbit)
    current_delta_u = delta_u_from_damico_roe(reference.mean_orbit, current)
    stale_error = abs(wrap_pi(decision.observed_delta_u_rad - current_delta_u))
    if stale_error > 1.0e-10:
        raise ValueError("policy decision does not match current request mean phase")

    adapted = roe_target_for_delta_u(
        reference.mean_orbit,
        current,
        decision.guidance_target_delta_u_rad,
    )
    execution_policy = replace(base_policy, target_roe=adapted.as_tuple())
    return PolicyExecutionTarget(
        deputy_id=deputy.satellite_id,
        reference_id=reference.satellite_id,
        current_roe=current.as_tuple(),
        current_delta_u_rad=current_delta_u,
        guidance_target_delta_u_rad=decision.guidance_target_delta_u_rad,
        adapted_target_roe=adapted.as_tuple(),
        execution_policy=execution_policy,
    )


def _build_transition_snapshot(
    request: PropagationRequest,
    target: PolicyExecutionTarget,
    authority: ManeuverAuthorityEvidence,
    captured: _CapturedPropagation,
) -> AuthoritativeTransitionSnapshot:
    replay = captured.result
    if len(replay.times_s) < 2:
        raise RuntimeError("authorizing replay must contain the first continuation interval")
    continuation_index = 1
    states: list[TransitionSpacecraftState] = []
    for satellite in request.satellites:
        mean_history = replay.mean_orbits.get(satellite.satellite_id)
        if mean_history is None or len(mean_history) <= continuation_index:
            raise RuntimeError(f"authorizing replay lacks continuation mean state for {satellite.satellite_id}")
        cart_history = replay.cartesian_states.get(satellite.satellite_id)
        cartesian = None
        if cart_history is not None:
            if len(cart_history) <= continuation_index:
                raise RuntimeError(f"authorizing replay lacks continuation Cartesian state for {satellite.satellite_id}")
            cartesian = cart_history[continuation_index]
        states.append(
            TransitionSpacecraftState(
                satellite_id=satellite.satellite_id,
                mean_orbit=mean_history[continuation_index],
                cartesian_state=cartesian,
            )
        )

    controlled = next(sat for sat in request.satellites if sat.satellite_id == target.deputy_id)
    maneuver = authority.first_maneuver
    if maneuver is None:
        raise RuntimeError("authorized maneuver evidence is missing first_maneuver")
    delta_v = float(np.linalg.norm(np.asarray(maneuver.dv_rtn_m_s, dtype=float)))
    return AuthoritativeTransitionSnapshot(
        continuation_sample_index=continuation_index,
        continuation_time_s=float(replay.times_s[continuation_index]),
        source_replay_times_s=tuple(float(value) for value in replay.times_s),
        controlled_satellite_id=target.deputy_id,
        reference_id=target.reference_id,
        spacecraft_states=tuple(states),
        controlled_propellant_remaining_kg=authority.propellant_remaining_kg,
        controlled_total_mass_kg=controlled.spacecraft.dry_mass_kg + authority.propellant_remaining_kg,
        event_delta_v_m_s=delta_v,
        event_propellant_used_kg=authority.propellant_used_kg,
        force_model_fingerprint=replay.force_model_fingerprint,
        backend=replay.backend,
        backend_version=replay.backend_version,
        backend_metadata=dict(sorted(replay.backend_metadata.items())),
        frame=request.frame,
        time_scale=request.time_scale,
        integrator=request.integrator,
    )


def authorize_policy_correction(
    propagator: Propagator,
    request: PropagationRequest,
    constraints: ConstraintConfig,
    decision: CorrectionDecision,
    base_policy: MPCExecutionPolicy,
    times_s: np.ndarray,
    maneuver_windows: np.ndarray,
    *,
    deputy_id: str | None = None,
) -> PolicyManeuverAttemptEvidence:
    """Attempt numerical maneuver authorization only when the policy requests correction."""

    if not decision.correction_requested:
        return PolicyManeuverAttemptEvidence(
            decision=decision,
            sizing_attempted=False,
            target=None,
            authority=None,
            transition=None,
        )

    target = build_policy_execution_target(
        request,
        constraints,
        decision,
        base_policy,
        deputy_id=deputy_id,
    )
    capture = _ReplayCapturePropagator(propagator)
    controller = RecedingHorizonMPCController(
        capture,
        target.execution_policy,
        deputy_id=target.deputy_id,
    )
    authority = controller.authorize_first_maneuver(
        request,
        constraints,
        times_s,
        maneuver_windows,
    )
    transition = None
    if authority.authorized:
        captured = capture.authorizing_replay(authority)
        transition = _build_transition_snapshot(request, target, authority, captured)
    return PolicyManeuverAttemptEvidence(
        decision=decision,
        sizing_attempted=True,
        target=target,
        authority=authority,
        transition=transition,
    )


def append_authorized_resource_record(
    ledger: tuple[CorrectionResourceRecord, ...],
    attempt: PolicyManeuverAttemptEvidence,
    *,
    event_time_s: float,
) -> tuple[CorrectionResourceRecord, ...]:
    """Append one resource record only for a maneuver authorized by numerical replay."""

    if not np.isfinite(event_time_s) or event_time_s < 0.0:
        raise ValueError("event_time_s must be finite and non-negative")
    authority = attempt.authority
    transition = attempt.transition
    if authority is None or not authority.authorized:
        return ledger
    if transition is None or authority.first_maneuver is None:
        raise RuntimeError("authorized policy attempt must contain transition and maneuver evidence")
    guidance_target = attempt.decision.guidance_target_delta_u_rad
    if guidance_target is None:
        raise RuntimeError("authorized policy attempt is missing guidance target")

    previous_delta_v = ledger[-1].cumulative_delta_v_m_s if ledger else 0.0
    previous_propellant = ledger[-1].cumulative_propellant_used_kg if ledger else 0.0
    record = CorrectionResourceRecord(
        event_time_s=float(event_time_s),
        policy=attempt.decision.policy.value,
        policy_reason=attempt.decision.reason,
        crossed_boundary_sign=attempt.decision.crossed_boundary_sign,
        observed_delta_u_rad=attempt.decision.observed_delta_u_rad,
        guidance_target_delta_u_rad=guidance_target,
        dv_rtn_m_s=authority.first_maneuver.dv_rtn_m_s,
        delta_v_m_s=transition.event_delta_v_m_s,
        propellant_used_kg=authority.propellant_used_kg,
        propellant_remaining_kg=authority.propellant_remaining_kg,
        required_reserve_kg=authority.required_reserve_kg,
        cumulative_delta_v_m_s=previous_delta_v + transition.event_delta_v_m_s,
        cumulative_propellant_used_kg=previous_propellant + authority.propellant_used_kg,
        replay_backend=transition.backend,
        replay_backend_metadata=transition.backend_metadata,
        force_model_fingerprint=transition.force_model_fingerprint,
    )
    return (*ledger, record)
