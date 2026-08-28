from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from constellation_control.domain.models import (
    FrameName,
    IntegratorConfig,
    MeanOrbit,
    OsculatingState,
    TimeScaleName,
)


class TransitionSpacecraftState(BaseModel):
    model_config = ConfigDict(frozen=True)

    satellite_id: str
    mean_orbit: MeanOrbit
    cartesian_state: OsculatingState | None = None


class AuthoritativeTransitionSnapshot(BaseModel):
    """Continuation state from the same numerical replay that authorized the first maneuver."""

    model_config = ConfigDict(frozen=True)

    continuation_sample_index: int = Field(default=1, ge=1)
    continuation_time_s: float = Field(ge=0.0)
    source_replay_times_s: tuple[float, ...]
    controlled_satellite_id: str
    reference_id: str
    spacecraft_states: tuple[TransitionSpacecraftState, ...]
    controlled_propellant_remaining_kg: float = Field(ge=0.0)
    controlled_total_mass_kg: float = Field(gt=0.0)
    event_delta_v_m_s: float = Field(ge=0.0)
    event_propellant_used_kg: float = Field(ge=0.0)
    force_model_fingerprint: str
    backend: str
    backend_version: str
    backend_metadata: dict[str, str]
    frame: FrameName
    time_scale: TimeScaleName
    integrator: IntegratorConfig


class CorrectionResourceRecord(BaseModel):
    """Append-only accounting record for one authorized policy correction."""

    model_config = ConfigDict(frozen=True)

    event_time_s: float = Field(ge=0.0)
    policy: str
    policy_reason: str
    crossed_boundary_sign: int | None
    observed_delta_u_rad: float
    guidance_target_delta_u_rad: float
    dv_rtn_m_s: tuple[float, float, float]
    delta_v_m_s: float = Field(ge=0.0)
    propellant_used_kg: float = Field(ge=0.0)
    propellant_remaining_kg: float = Field(ge=0.0)
    required_reserve_kg: float = Field(ge=0.0)
    cumulative_delta_v_m_s: float = Field(ge=0.0)
    cumulative_propellant_used_kg: float = Field(ge=0.0)
    replay_backend: str
    replay_backend_metadata: dict[str, str]
    force_model_fingerprint: str
