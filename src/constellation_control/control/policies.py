from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from math import isfinite


class CorrectionPolicy(StrEnum):
    NO_CONTROL = "no_control"
    RETURN_TO_CENTER = "return_to_center"
    BOUNDARY_TO_BOUNDARY = "boundary_to_boundary"


@dataclass(frozen=True)
class CorrectionPolicyState:
    """Minimal deterministic state required to suppress duplicate boundary requests."""

    armed: bool = True


@dataclass(frozen=True)
class CorrectionDecision:
    """Policy-layer guidance request without maneuver sizing or fuel assumptions."""

    policy: CorrectionPolicy
    correction_requested: bool
    reason: str
    observed_delta_u_rad: float
    corridor_half_width_rad: float
    crossed_boundary_sign: int | None
    guidance_target_delta_u_rad: float | None
    armed_before: bool
    armed_after: bool


def _validate_inputs(delta_u_rad: float, corridor_half_width_rad: float) -> tuple[float, float]:
    delta_u = float(delta_u_rad)
    half_width = float(corridor_half_width_rad)
    if not isfinite(delta_u):
        raise ValueError("delta_u_rad must be finite")
    if not isfinite(half_width) or half_width <= 0.0:
        raise ValueError("corridor_half_width_rad must be finite and positive")
    return delta_u, half_width


def _boundary_sign(delta_u_rad: float, corridor_half_width_rad: float) -> int | None:
    if delta_u_rad >= corridor_half_width_rad:
        return 1
    if delta_u_rad <= -corridor_half_width_rad:
        return -1
    return None


def evaluate_correction_policy(
    policy: CorrectionPolicy,
    delta_u_rad: float,
    corridor_half_width_rad: float,
    state: CorrectionPolicyState | None = None,
) -> tuple[CorrectionDecision, CorrectionPolicyState]:
    """Evaluate one deterministic correction-policy sample.

    The policy layer decides only whether guidance is requested and which mean-phase
    objective should guide the ensuing controlled coast. It intentionally does not
    map a request to delta-V, propellant, or an instantaneous phase jump.

    A correction request disarms RETURN_TO_CENTER and BOUNDARY_TO_BOUNDARY. They
    rearm only after a later observation lies strictly inside the configured phase
    corridor. No hidden tolerance or hysteresis is introduced.
    """

    current_state = CorrectionPolicyState() if state is None else state
    delta_u, half_width = _validate_inputs(delta_u_rad, corridor_half_width_rad)
    boundary_sign = _boundary_sign(delta_u, half_width)
    inside = boundary_sign is None

    if policy == CorrectionPolicy.NO_CONTROL:
        decision = CorrectionDecision(
            policy=policy,
            correction_requested=False,
            reason="no_control_policy",
            observed_delta_u_rad=delta_u,
            corridor_half_width_rad=half_width,
            crossed_boundary_sign=boundary_sign,
            guidance_target_delta_u_rad=None,
            armed_before=current_state.armed,
            armed_after=current_state.armed,
        )
        return decision, current_state

    if not current_state.armed:
        if inside:
            next_state = CorrectionPolicyState(armed=True)
            decision = CorrectionDecision(
                policy=policy,
                correction_requested=False,
                reason="rearmed_inside_corridor",
                observed_delta_u_rad=delta_u,
                corridor_half_width_rad=half_width,
                crossed_boundary_sign=None,
                guidance_target_delta_u_rad=None,
                armed_before=False,
                armed_after=True,
            )
            return decision, next_state
        decision = CorrectionDecision(
            policy=policy,
            correction_requested=False,
            reason="disarmed_waiting_for_reentry",
            observed_delta_u_rad=delta_u,
            corridor_half_width_rad=half_width,
            crossed_boundary_sign=boundary_sign,
            guidance_target_delta_u_rad=None,
            armed_before=False,
            armed_after=False,
        )
        return decision, current_state

    if inside:
        decision = CorrectionDecision(
            policy=policy,
            correction_requested=False,
            reason="inside_corridor",
            observed_delta_u_rad=delta_u,
            corridor_half_width_rad=half_width,
            crossed_boundary_sign=None,
            guidance_target_delta_u_rad=None,
            armed_before=True,
            armed_after=True,
        )
        return decision, current_state

    if policy == CorrectionPolicy.RETURN_TO_CENTER:
        target = 0.0
        reason = "phase_boundary_reached_return_to_center"
    elif policy == CorrectionPolicy.BOUNDARY_TO_BOUNDARY:
        assert boundary_sign is not None
        target = -float(boundary_sign) * half_width
        reason = "phase_boundary_reached_coast_to_opposite_boundary"
    else:
        raise ValueError(f"unsupported correction policy: {policy}")

    next_state = CorrectionPolicyState(armed=False)
    decision = CorrectionDecision(
        policy=policy,
        correction_requested=True,
        reason=reason,
        observed_delta_u_rad=delta_u,
        corridor_half_width_rad=half_width,
        crossed_boundary_sign=boundary_sign,
        guidance_target_delta_u_rad=target,
        armed_before=True,
        armed_after=False,
    )
    return decision, next_state
