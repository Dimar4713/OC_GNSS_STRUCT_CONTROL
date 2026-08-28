from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from pydantic import BaseModel, ConfigDict

from constellation_control.control.closed_loop import event_request_from_coast
from constellation_control.control.execution import MPCExecutionPolicy
from constellation_control.control.policy_execution import (
    PolicyManeuverAttemptEvidence,
    authorize_policy_correction,
)
from constellation_control.domain.models import ConstraintConfig, PropagationRequest
from constellation_control.domain.protocols import Propagator
from constellation_control.optimization.hybrid import EventValidationEvidence, ValidationOutcomeKind
from constellation_control.optimization.hybrid_execution import AuthoritativePhaseWindowResult
from constellation_control.optimization.operations import CredibilityState, HardConstraintEvidence


class HybridCorrectionAuthorityReceipt(BaseModel):
    """Machine-readable authority result retaining measured event evidence even on rejection."""

    model_config = ConfigDict(frozen=True)

    event_validation: EventValidationEvidence
    authority_attempted: bool
    authorized: bool
    authority_reason: str
    hard_constraints: tuple[HardConstraintEvidence, ...]
    resulting_credibility_state: CredibilityState
    deputy_id: str | None = None
    reference_id: str | None = None
    dv_rtn_m_s: tuple[float, float, float] | None = None
    propellant_used_kg: float | None = None
    propellant_remaining_kg: float | None = None
    required_reserve_kg: float | None = None
    replay_backend: str | None = None
    trust_error_ratio: float | None = None
    replay_min_pair_distance_m: float | None = None
    transition_backend: str | None = None
    transition_force_model_fingerprint: str | None = None


@dataclass(frozen=True)
class HybridCorrectionAuthorityResult:
    receipt: HybridCorrectionAuthorityReceipt
    attempt: PolicyManeuverAttemptEvidence | None
    event_request: PropagationRequest | None


def _authority_hard_constraints(
    attempt: PolicyManeuverAttemptEvidence,
    constraints: ConstraintConfig,
) -> tuple[HardConstraintEvidence, ...]:
    authority = attempt.authority
    if authority is None:
        return (
            HardConstraintEvidence(
                name="numerical_authority_authorized",
                unit="signed_boolean_margin",
                margin=-1.0,
                evidence_source="missing-maneuver-authority-evidence",
            ),
        )

    margins: list[HardConstraintEvidence] = [
        HardConstraintEvidence(
            name="propellant_reserve_margin",
            unit="kg",
            margin=float(authority.propellant_remaining_kg - authority.required_reserve_kg),
            evidence_source=authority.reason,
        ),
        HardConstraintEvidence(
            name="numerical_authority_authorized",
            unit="signed_boolean_margin",
            margin=0.0 if authority.authorized else -1.0,
            evidence_source=authority.reason,
        ),
    ]
    if authority.replay_min_pair_distance_m is not None:
        margins.append(
            HardConstraintEvidence(
                name="fleet_minimum_distance_margin",
                unit="m",
                margin=float(
                    authority.replay_min_pair_distance_m - constraints.min_pair_distance_m
                ),
                evidence_source=authority.reason,
            )
        )
    if authority.trust_error_ratio is not None:
        margins.append(
            HardConstraintEvidence(
                name="numerical_trust_margin",
                unit="ratio",
                margin=float(1.0 - authority.trust_error_ratio),
                evidence_source=authority.reason,
            )
        )
    return tuple(margins)


def authorize_validated_phase_event(
    propagator: Propagator,
    window: AuthoritativePhaseWindowResult,
    constraints: ConstraintConfig,
    base_execution_policy: MPCExecutionPolicy,
    authority_times_s: np.ndarray,
    maneuver_windows: np.ndarray,
    *,
    deputy_id: str | None = None,
) -> HybridCorrectionAuthorityResult:
    """Route one real high-fidelity phase event through the existing P2 numerical authority."""

    validation = window.evidence
    if validation.outcome not in {
        ValidationOutcomeKind.CONFIRMED,
        ValidationOutcomeKind.SHIFTED,
    }:
        receipt = HybridCorrectionAuthorityReceipt(
            event_validation=validation,
            authority_attempted=False,
            authorized=False,
            authority_reason=f"event-not-authorizable:{validation.outcome.value}",
            hard_constraints=(
                HardConstraintEvidence(
                    name="authoritative_event_present",
                    unit="signed_boolean_margin",
                    margin=-1.0,
                    evidence_source=validation.outcome.value,
                ),
            ),
            resulting_credibility_state=CredibilityState.REJECTED_BY_AUTHORITY,
        )
        return HybridCorrectionAuthorityResult(receipt=receipt, attempt=None, event_request=None)
    if window.event is None:
        raise RuntimeError("confirmed/shifted event evidence must retain exact authoritative event state")

    times = np.asarray(authority_times_s, dtype=float)
    windows = np.asarray(maneuver_windows, dtype=bool)
    if times.ndim != 1 or times.size < 2 or abs(float(times[0])) > 1.0e-9:
        raise ValueError("authority_times_s must start at zero and contain at least two samples")
    intervals = np.diff(times)
    if np.any(~np.isfinite(times)) or np.any(intervals <= 0.0):
        raise ValueError("authority_times_s must be finite and strictly increasing")
    if not np.allclose(intervals, intervals[0], rtol=0.0, atol=1.0e-9):
        raise ValueError("authority_times_s must use a uniform output grid")
    if windows.shape != (times.size - 1,):
        raise ValueError("maneuver_windows must have one entry per authority interval")

    event_request = event_request_from_coast(
        window.validation_request,
        window.event,
        duration_s=float(times[-1]),
        output_step_s=float(intervals[0]),
    )
    attempt = authorize_policy_correction(
        propagator,
        event_request,
        constraints,
        window.event.decision,
        base_execution_policy,
        times,
        windows,
        deputy_id=deputy_id,
    )
    authority = attempt.authority
    hard_constraints = _authority_hard_constraints(attempt, constraints)
    authorized = bool(authority is not None and authority.authorized and attempt.transition is not None)
    hard_pass = all(item.passed for item in hard_constraints)
    credibility = (
        CredibilityState.AUTHORITATIVELY_VALIDATED_CANDIDATE
        if authorized and hard_pass
        else CredibilityState.REJECTED_BY_AUTHORITY
    )
    maneuver = None if authority is None else authority.first_maneuver
    transition = attempt.transition
    receipt = HybridCorrectionAuthorityReceipt(
        event_validation=validation,
        authority_attempted=True,
        authorized=authorized,
        authority_reason="missing-authority-evidence" if authority is None else authority.reason,
        hard_constraints=hard_constraints,
        resulting_credibility_state=credibility,
        deputy_id=None if authority is None else authority.deputy_id,
        reference_id=None if authority is None else authority.reference_id,
        dv_rtn_m_s=None if maneuver is None else maneuver.dv_rtn_m_s,
        propellant_used_kg=None if authority is None else authority.propellant_used_kg,
        propellant_remaining_kg=None if authority is None else authority.propellant_remaining_kg,
        required_reserve_kg=None if authority is None else authority.required_reserve_kg,
        replay_backend=None if authority is None else authority.replay_backend,
        trust_error_ratio=None if authority is None else authority.trust_error_ratio,
        replay_min_pair_distance_m=(
            None if authority is None else authority.replay_min_pair_distance_m
        ),
        transition_backend=None if transition is None else transition.backend,
        transition_force_model_fingerprint=(
            None if transition is None else transition.force_model_fingerprint
        ),
    )
    return HybridCorrectionAuthorityResult(
        receipt=receipt,
        attempt=attempt,
        event_request=event_request,
    )
