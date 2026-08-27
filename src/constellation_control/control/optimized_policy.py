from __future__ import annotations

from dataclasses import dataclass
from math import isfinite

from constellation_control.control.policies import (
    CorrectionDecision,
    CorrectionPolicy,
    CorrectionPolicyState,
)
from constellation_control.optimization.operational_policy_search import OperationalPolicyParameters


@dataclass(frozen=True)
class OptimizedPolicyDecisionEvidence:
    candidate_id: str
    trigger_fraction: float
    trigger_half_width_rad: float
    target_fraction: float
    hard_corridor_half_width_rad: float
    decision: CorrectionDecision


def _validate_parameters(parameters: OperationalPolicyParameters) -> None:
    if not isfinite(parameters.trigger_fraction) or not 0.0 < parameters.trigger_fraction <= 1.0:
        raise ValueError("optimized trigger_fraction must be finite and in (0, 1]")
    if not isfinite(parameters.target_fraction) or not -1.0 <= parameters.target_fraction <= 1.0:
        raise ValueError("optimized target_fraction must be finite and in [-1, 1]")


def evaluate_optimized_correction_policy(
    candidate_id: str,
    parameters: OperationalPolicyParameters,
    delta_u_rad: float,
    hard_corridor_half_width_rad: float,
    state: CorrectionPolicyState | None = None,
) -> tuple[OptimizedPolicyDecisionEvidence, CorrectionPolicyState]:
    """Evaluate P3 optimized triggering while preserving the hard execution corridor.

    The optimized trigger is a configurable fraction of the hard phase corridor.
    `CorrectionDecision.corridor_half_width_rad` always remains the hard execution
    corridor so the existing numerical authority keeps its original safety contract.
    """

    if not candidate_id:
        raise ValueError("optimized policy requires candidate_id")
    _validate_parameters(parameters)
    delta_u = float(delta_u_rad)
    hard = float(hard_corridor_half_width_rad)
    if not isfinite(delta_u):
        raise ValueError("delta_u_rad must be finite")
    if not isfinite(hard) or hard <= 0.0:
        raise ValueError("hard corridor half width must be finite and positive")

    trigger = parameters.trigger_fraction * hard
    if delta_u >= trigger:
        trigger_sign: int | None = 1
    elif delta_u <= -trigger:
        trigger_sign = -1
    else:
        trigger_sign = None
    inside_trigger = trigger_sign is None
    current_state = CorrectionPolicyState() if state is None else state

    if not current_state.armed:
        if inside_trigger:
            next_state = CorrectionPolicyState(armed=True)
            decision = CorrectionDecision(
                policy=CorrectionPolicy.OPTIMIZED,
                correction_requested=False,
                reason="optimized_rearmed_inside_trigger",
                observed_delta_u_rad=delta_u,
                corridor_half_width_rad=hard,
                crossed_boundary_sign=None,
                guidance_target_delta_u_rad=None,
                armed_before=False,
                armed_after=True,
            )
        else:
            next_state = current_state
            decision = CorrectionDecision(
                policy=CorrectionPolicy.OPTIMIZED,
                correction_requested=False,
                reason="optimized_disarmed_waiting_for_trigger_reentry",
                observed_delta_u_rad=delta_u,
                corridor_half_width_rad=hard,
                crossed_boundary_sign=trigger_sign,
                guidance_target_delta_u_rad=None,
                armed_before=False,
                armed_after=False,
            )
    elif inside_trigger:
        next_state = current_state
        decision = CorrectionDecision(
            policy=CorrectionPolicy.OPTIMIZED,
            correction_requested=False,
            reason="optimized_inside_trigger",
            observed_delta_u_rad=delta_u,
            corridor_half_width_rad=hard,
            crossed_boundary_sign=None,
            guidance_target_delta_u_rad=None,
            armed_before=True,
            armed_after=True,
        )
    else:
        assert trigger_sign is not None
        next_state = CorrectionPolicyState(armed=False)
        decision = CorrectionDecision(
            policy=CorrectionPolicy.OPTIMIZED,
            correction_requested=True,
            reason="optimized_trigger_reached",
            observed_delta_u_rad=delta_u,
            corridor_half_width_rad=hard,
            crossed_boundary_sign=trigger_sign,
            guidance_target_delta_u_rad=parameters.guidance_target_delta_u_rad(trigger_sign, hard),
            armed_before=True,
            armed_after=False,
        )

    return (
        OptimizedPolicyDecisionEvidence(
            candidate_id=candidate_id,
            trigger_fraction=parameters.trigger_fraction,
            trigger_half_width_rad=trigger,
            target_fraction=parameters.target_fraction,
            hard_corridor_half_width_rad=hard,
            decision=decision,
        ),
        next_state,
    )
