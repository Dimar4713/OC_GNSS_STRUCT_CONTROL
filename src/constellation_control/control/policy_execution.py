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
from constellation_control.domain.models import ConstraintConfig, PropagationRequest, SatelliteSpec
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
        )

    target = build_policy_execution_target(
        request,
        constraints,
        decision,
        base_policy,
        deputy_id=deputy_id,
    )
    controller = RecedingHorizonMPCController(
        propagator,
        target.execution_policy,
        deputy_id=target.deputy_id,
    )
    authority = controller.authorize_first_maneuver(
        request,
        constraints,
        times_s,
        maneuver_windows,
    )
    return PolicyManeuverAttemptEvidence(
        decision=decision,
        sizing_attempted=True,
        target=target,
        authority=authority,
    )
