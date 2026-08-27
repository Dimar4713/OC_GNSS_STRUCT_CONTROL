from __future__ import annotations

import uuid
from pathlib import Path

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, model_validator

from constellation_control.adapters.orekit.adapter import OrekitSidecarPropagator
from constellation_control.adapters.synthetic.propagator import SyntheticMeanPropagator
from constellation_control.analysis.closed_loop_metrics import analyze_closed_loop_operations
from constellation_control.application.run import load_scenario
from constellation_control.control.campaign import ClosedLoopCampaignResult, run_closed_loop_campaign
from constellation_control.control.execution import MPCExecutionPolicy
from constellation_control.control.policies import CorrectionPolicy
from constellation_control.domain.models import ForceMode, PropagationRequest
from constellation_control.domain.protocols import Propagator
from constellation_control.reporting.closed_loop_artifacts import write_closed_loop_artifacts


PREVIEW_CLOSED_LOOP_PROFILE_SCHEMA = "preview-closed-loop-profile-v1"


class PreviewClosedLoopProfile(BaseModel):
    """Explicit operator-supplied P2 control contract; contains no hidden control constants."""

    model_config = ConfigDict(frozen=True)

    schema_version: str = PREVIEW_CLOSED_LOOP_PROFILE_SCHEMA
    policy: CorrectionPolicy
    campaign_horizon_s: float = Field(gt=0.0)
    coast_horizon_s: float = Field(gt=0.0)
    coast_output_step_s: float = Field(gt=0.0)
    max_corrections: int = Field(gt=0)
    authority_times_s: tuple[float, ...]
    maneuver_windows: tuple[bool, ...]
    max_abs_impulse_rtn_m_s: tuple[float, float, float]
    min_impulse_bit_m_s: float
    trust_tolerances_roe: tuple[float, float, float, float, float, float]
    target_roe: tuple[float, float, float, float, float, float]
    w_tracking: float
    w_max: float
    deputy_id: str | None = None

    @model_validator(mode="after")
    def validate_contract(self) -> PreviewClosedLoopProfile:
        if self.schema_version != PREVIEW_CLOSED_LOOP_PROFILE_SCHEMA:
            raise ValueError("unsupported Preview closed-loop profile schema")
        if self.policy == CorrectionPolicy.OPTIMIZED:
            raise ValueError("OPTIMIZED is a P3 policy and is not accepted by the P2 Preview runner")
        times = np.asarray(self.authority_times_s, dtype=float)
        if times.ndim != 1 or times.size < 2 or np.any(~np.isfinite(times)):
            raise ValueError("authority_times_s must contain at least two finite samples")
        if abs(float(times[0])) > 1.0e-9 or np.any(np.diff(times) <= 0.0):
            raise ValueError("authority_times_s must start at zero and be strictly increasing")
        if len(self.maneuver_windows) != len(self.authority_times_s) - 1:
            raise ValueError("maneuver_windows must have one entry per authority interval")
        return self

    def execution_policy(self) -> MPCExecutionPolicy:
        return MPCExecutionPolicy(
            max_abs_impulse_rtn_m_s=self.max_abs_impulse_rtn_m_s,
            min_impulse_bit_m_s=self.min_impulse_bit_m_s,
            trust_tolerances_roe=self.trust_tolerances_roe,
            target_roe=self.target_roe,
            w_tracking=self.w_tracking,
            w_max=self.w_max,
        )


class PreviewClosedLoopRunResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    run_dir: str
    profile_path: str
    campaign_path: str
    metrics_path: str
    corrections_json_path: str
    report_path: str
    campaign: ClosedLoopCampaignResult


def _request_from_scenario(scenario_path: Path) -> tuple[PropagationRequest, object]:
    scenario = load_scenario(scenario_path)
    request = PropagationRequest(
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
        seed=scenario.seed,
    )
    return request, scenario


def run_preview_closed_loop(
    scenario_path: Path,
    output_root: Path,
    profile: PreviewClosedLoopProfile,
    *,
    propagator: Propagator | None = None,
) -> PreviewClosedLoopRunResult:
    """Run accepted P2 campaign/artifact code from one explicit Preview control profile."""

    initial_request, scenario_obj = _request_from_scenario(scenario_path)
    scenario = scenario_obj  # preserve type inference without reloading the YAML

    if profile.policy != CorrectionPolicy.NO_CONTROL:
        if scenario.force_model.mode != ForceMode.VALIDATION:
            raise ValueError(
                "Корректирующая политика требует ScenarioConfig с force mode VALIDATION / "
                "correction policy requires a ScenarioConfig with VALIDATION force mode"
            )
        if not scenario.orekit_sidecar_url:
            raise ValueError(
                "Для корректирующей политики требуется orekit_sidecar_url / "
                "correction policy requires orekit_sidecar_url"
            )

    resolved_propagator: Propagator
    if propagator is not None:
        resolved_propagator = propagator
    elif profile.policy == CorrectionPolicy.NO_CONTROL:
        # The P2 campaign returns before any propagation/authority call for NO_CONTROL.
        resolved_propagator = SyntheticMeanPropagator()
    else:
        assert scenario.orekit_sidecar_url is not None
        resolved_propagator = OrekitSidecarPropagator(scenario.orekit_sidecar_url)

    campaign = run_closed_loop_campaign(
        resolved_propagator,
        initial_request,
        scenario.constraints,
        profile.policy,
        profile.execution_policy(),
        np.asarray(profile.authority_times_s, dtype=float),
        np.asarray(profile.maneuver_windows, dtype=bool),
        campaign_horizon_s=profile.campaign_horizon_s,
        coast_horizon_s=profile.coast_horizon_s,
        coast_output_step_s=profile.coast_output_step_s,
        max_corrections=profile.max_corrections,
        deputy_id=profile.deputy_id,
    )
    metrics = analyze_closed_loop_operations(campaign)

    run_id = f"closed-loop-{uuid.uuid4().hex[:12]}"
    run_dir = output_root / initial_request.scenario_id / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    profile_path = run_dir / "closed_loop_profile.json"
    profile_path.write_text(profile.model_dump_json(indent=2), encoding="utf-8")
    write_closed_loop_artifacts(run_dir, campaign, metrics)

    return PreviewClosedLoopRunResult(
        run_dir=str(run_dir),
        profile_path=str(profile_path),
        campaign_path=str(run_dir / "closed_loop_campaign.json"),
        metrics_path=str(run_dir / "closed_loop_metrics.json"),
        corrections_json_path=str(run_dir / "closed_loop_corrections.json"),
        report_path=str(run_dir / "report.html"),
        campaign=campaign,
    )
