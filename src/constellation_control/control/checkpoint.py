from __future__ import annotations

from math import isfinite

import numpy as np
from pydantic import BaseModel, ConfigDict, Field

from constellation_control.control.campaign import (
    CampaignAuthorityRecord,
    CampaignPolicyEventRecord,
    CampaignPolicyTraceRecord,
    ClosedLoopCampaignResult,
)
from constellation_control.control.policies import CorrectionPolicy
from constellation_control.control.transition import (
    AuthoritativeTransitionSnapshot,
    CorrectionResourceRecord,
)
from constellation_control.domain.models import IntegratorConfig, PropagationRequest

CHECKPOINT_SCHEMA_VERSION = "closed-loop-checkpoint-v1"


class PendingCorrectionDecisionSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True)

    policy: CorrectionPolicy
    reason: str
    observed_delta_u_rad: float
    corridor_half_width_rad: float = Field(gt=0.0)
    crossed_boundary_sign: int
    guidance_target_delta_u_rad: float
    armed_before: bool
    armed_after: bool


class CampaignProgressEvidence(BaseModel):
    model_config = ConfigDict(frozen=True)

    elapsed_simulated_s: float = Field(ge=0.0)
    campaign_horizon_s: float = Field(gt=0.0)
    simulated_progress_fraction: float = Field(ge=0.0, le=1.0)
    remaining_simulated_s: float = Field(ge=0.0)
    correction_count: int = Field(ge=0)
    max_corrections: int = Field(gt=0)
    correction_progress_fraction: float = Field(ge=0.0, le=1.0)
    cumulative_delta_v_m_s: float = Field(ge=0.0)
    cumulative_propellant_used_kg: float = Field(ge=0.0)
    remaining_propellant_kg: float = Field(ge=0.0)
    required_reserve_kg: float = Field(ge=0.0)
    usable_propellant_above_reserve_kg: float = Field(ge=0.0)
    policy_armed: bool
    last_policy_reason: str | None
    coast_propagation_calls: int = Field(ge=0)
    checkpoint_sequence: int = Field(ge=0)
    runtime_eta_available: bool = False
    runtime_eta_reason: str = "wall-clock ETA requires measured runtime throughput and is not inferred from simulated time"


class ClosedLoopCampaignCheckpoint(BaseModel):
    model_config = ConfigDict(frozen=True)

    schema_version: str = CHECKPOINT_SCHEMA_VERSION
    checkpoint_sequence: int = Field(ge=0)
    source_termination_reason: str
    force_model_fingerprint: str
    frame: str
    time_scale: str
    integrator: IntegratorConfig
    current_request: PropagationRequest
    campaign_horizon_s: float = Field(gt=0.0)
    coast_horizon_s: float = Field(gt=0.0)
    coast_output_step_s: float = Field(gt=0.0)
    authority_times_s: tuple[float, ...]
    maneuver_windows: tuple[bool, ...]
    max_corrections: int = Field(gt=0)
    elapsed_simulated_s: float = Field(ge=0.0)
    policy: CorrectionPolicy
    corridor_half_width_rad: float = Field(gt=0.0)
    policy_armed: bool
    pending_decision: PendingCorrectionDecisionSnapshot | None
    policy_events: tuple[CampaignPolicyEventRecord, ...]
    policy_trace: tuple[CampaignPolicyTraceRecord, ...]
    authority_attempts: tuple[CampaignAuthorityRecord, ...]
    transitions: tuple[AuthoritativeTransitionSnapshot, ...]
    resource_ledger: tuple[CorrectionResourceRecord, ...]
    cumulative_delta_v_m_s: float = Field(ge=0.0)
    cumulative_propellant_used_kg: float = Field(ge=0.0)
    controlled_propellant_remaining_kg: float = Field(ge=0.0)
    controlled_required_reserve_kg: float = Field(ge=0.0)
    coast_propagation_calls: int = Field(ge=0)
    progress: CampaignProgressEvidence


def _validate_grid(
    authority_times_s: np.ndarray,
    maneuver_windows: np.ndarray,
) -> tuple[tuple[float, ...], tuple[bool, ...]]:
    times = np.asarray(authority_times_s, dtype=float)
    windows = np.asarray(maneuver_windows, dtype=bool)
    if times.ndim != 1 or times.size < 2 or np.any(~np.isfinite(times)):
        raise ValueError("authority_times_s must be a finite one-dimensional grid with at least two samples")
    if abs(float(times[0])) > 1.0e-9 or np.any(np.diff(times) <= 0.0):
        raise ValueError("authority_times_s must start at zero and be strictly increasing")
    if windows.shape != (times.size - 1,):
        raise ValueError("maneuver_windows must have one entry per authority interval")
    return tuple(float(value) for value in times), tuple(bool(value) for value in windows)


def _positive_finite(value: float, name: str) -> float:
    resolved = float(value)
    if not isfinite(resolved) or resolved <= 0.0:
        raise ValueError(f"{name} must be finite and positive")
    return resolved


def pending_decision_from_campaign(
    campaign: ClosedLoopCampaignResult,
) -> PendingCorrectionDecisionSnapshot | None:
    """Recover an exact pending boundary decision only at a boundary-before-authority stop."""

    if not campaign.policy_events:
        return None
    event = campaign.policy_events[-1]
    if abs(event.elapsed_time_s - campaign.elapsed_time_s) > 1.0e-9:
        return None
    if event.crossed_boundary_sign is None or event.guidance_target_delta_u_rad is None:
        return None
    if event.armed_after:
        return None
    return PendingCorrectionDecisionSnapshot(
        policy=campaign.policy,
        reason=event.decision_reason,
        observed_delta_u_rad=event.observed_delta_u_rad,
        corridor_half_width_rad=campaign.corridor_half_width_rad,
        crossed_boundary_sign=event.crossed_boundary_sign,
        guidance_target_delta_u_rad=event.guidance_target_delta_u_rad,
        armed_before=event.armed_before,
        armed_after=event.armed_after,
    )


def _latest_policy_reason(campaign: ClosedLoopCampaignResult) -> str | None:
    candidates: list[tuple[float, int, str]] = []
    if campaign.policy_trace:
        trace = campaign.policy_trace[-1]
        candidates.append((trace.elapsed_time_s, 0, trace.decision_reason))
    if campaign.policy_events:
        event = campaign.policy_events[-1]
        candidates.append((event.elapsed_time_s, 1, event.decision_reason))
    if not candidates:
        return None
    return max(candidates, key=lambda item: (item[0], item[1]))[2]


def campaign_progress(
    campaign: ClosedLoopCampaignResult,
    *,
    campaign_horizon_s: float,
    max_corrections: int,
    checkpoint_sequence: int,
) -> CampaignProgressEvidence:
    horizon = _positive_finite(campaign_horizon_s, "campaign_horizon_s")
    if max_corrections <= 0:
        raise ValueError("max_corrections must be positive")
    if checkpoint_sequence < 0:
        raise ValueError("checkpoint_sequence must be non-negative")
    elapsed = float(campaign.elapsed_time_s)
    fraction = min(1.0, max(0.0, elapsed / horizon))
    correction_fraction = min(1.0, max(0.0, campaign.correction_count / max_corrections))
    remaining = max(0.0, horizon - elapsed)
    usable = max(
        0.0,
        campaign.controlled_propellant_remaining_kg - campaign.controlled_required_reserve_kg,
    )
    return CampaignProgressEvidence(
        elapsed_simulated_s=elapsed,
        campaign_horizon_s=horizon,
        simulated_progress_fraction=fraction,
        remaining_simulated_s=remaining,
        correction_count=campaign.correction_count,
        max_corrections=max_corrections,
        correction_progress_fraction=correction_fraction,
        cumulative_delta_v_m_s=campaign.cumulative_delta_v_m_s,
        cumulative_propellant_used_kg=campaign.cumulative_propellant_used_kg,
        remaining_propellant_kg=campaign.controlled_propellant_remaining_kg,
        required_reserve_kg=campaign.controlled_required_reserve_kg,
        usable_propellant_above_reserve_kg=usable,
        policy_armed=campaign.final_policy_armed,
        last_policy_reason=_latest_policy_reason(campaign),
        coast_propagation_calls=campaign.coast_propagation_calls,
        checkpoint_sequence=checkpoint_sequence,
    )


def create_campaign_checkpoint(
    campaign: ClosedLoopCampaignResult,
    *,
    campaign_horizon_s: float,
    coast_horizon_s: float,
    coast_output_step_s: float,
    authority_times_s: np.ndarray,
    maneuver_windows: np.ndarray,
    max_corrections: int,
    checkpoint_sequence: int = 0,
) -> ClosedLoopCampaignCheckpoint:
    """Capture a resumable evidence snapshot without invoking propagation."""

    horizon = _positive_finite(campaign_horizon_s, "campaign_horizon_s")
    coast_horizon = _positive_finite(coast_horizon_s, "coast_horizon_s")
    coast_step = _positive_finite(coast_output_step_s, "coast_output_step_s")
    if max_corrections <= 0:
        raise ValueError("max_corrections must be positive")
    times, windows = _validate_grid(authority_times_s, maneuver_windows)
    request = campaign.final_request
    progress = campaign_progress(
        campaign,
        campaign_horizon_s=horizon,
        max_corrections=max_corrections,
        checkpoint_sequence=checkpoint_sequence,
    )
    return ClosedLoopCampaignCheckpoint(
        checkpoint_sequence=checkpoint_sequence,
        source_termination_reason=campaign.termination_reason,
        force_model_fingerprint=request.force_model.fingerprint(),
        frame=request.frame.value,
        time_scale=request.time_scale.value,
        integrator=request.integrator,
        current_request=request,
        campaign_horizon_s=horizon,
        coast_horizon_s=coast_horizon,
        coast_output_step_s=coast_step,
        authority_times_s=times,
        maneuver_windows=windows,
        max_corrections=max_corrections,
        elapsed_simulated_s=campaign.elapsed_time_s,
        policy=campaign.policy,
        corridor_half_width_rad=campaign.corridor_half_width_rad,
        policy_armed=campaign.final_policy_armed,
        pending_decision=pending_decision_from_campaign(campaign),
        policy_events=campaign.policy_events,
        policy_trace=campaign.policy_trace,
        authority_attempts=campaign.authority_attempts,
        transitions=campaign.transitions,
        resource_ledger=campaign.resource_ledger,
        cumulative_delta_v_m_s=campaign.cumulative_delta_v_m_s,
        cumulative_propellant_used_kg=campaign.cumulative_propellant_used_kg,
        controlled_propellant_remaining_kg=campaign.controlled_propellant_remaining_kg,
        controlled_required_reserve_kg=campaign.controlled_required_reserve_kg,
        coast_propagation_calls=campaign.coast_propagation_calls,
        progress=progress,
    )
