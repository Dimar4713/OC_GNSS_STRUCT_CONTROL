from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

import numpy as np
from pydantic import BaseModel, ConfigDict

from constellation_control.adapters.orekit.adapter import OrekitSidecarPropagator
from constellation_control.analysis.campaign_hard_margins import reduce_trajectory_hard_margins
from constellation_control.analysis.fuel import propellant_used_kg
from constellation_control.application.robustness import (
    RobustnessApplicationConfig,
    _orekit_wire_seed,
    _perturb_maneuver,
    _perturb_satellite,
    _verify_authority,
    load_robustness_application_config,
    validate_uncertainty_contract,
)
from constellation_control.application.run import load_scenario
from constellation_control.control.campaign import ClosedLoopCampaignResult
from constellation_control.domain.models import ForceMode, Maneuver, PropagationRequest, ScenarioConfig
from constellation_control.domain.protocols import Propagator
from constellation_control.optimization.operational_robustness import (
    StrategyRobustnessEvidence,
    uncertainty_sampling_model_sha256,
)
from constellation_control.optimization.operational_robustness_binding import robustness_uncertainty_model_id
from constellation_control.optimization.operational_robustness_execution import (
    CompletedOperationalRealization,
    OperationalRobustnessStudyResult,
    SampleGenerator,
    StrategySampleExecutor,
    run_operational_robustness_study,
)
from constellation_control.preview.optimal_operations_authority import PreviewOptimizedAuthorityReduction
from constellation_control.preview.optimal_operations_execution import PreviewOptimalOperationsFoundationRun
from constellation_control.preview.optimal_operations_profile import PreviewOptimalOperationsStudyProfile
from constellation_control.preview.optimized_campaign import PreviewOptimizedCampaignEvidence


class PreviewPairedRobustnessResult(BaseModel):
    """Common-random-number fixed-plan robustness over all operational comparators."""

    model_config = ConfigDict(frozen=True)

    semantics: str
    campaign_id: str
    sampling_model_sha256: str
    strategies: tuple[StrategyRobustnessEvidence, ...]


def _ledger_plan(
    campaign: ClosedLoopCampaignResult,
    controlled_deputy_id: str,
) -> tuple[Maneuver, ...]:
    maneuvers: list[Maneuver] = []
    for record in campaign.resource_ledger:
        if not record.replay_backend.startswith("orekit-numerical"):
            raise ValueError("paired robustness nominal plan requires numerically authorized ledger entries")
        maneuvers.append(
            Maneuver(
                satellite_id=controlled_deputy_id,
                time_s=record.event_time_s,
                dv_rtn_m_s=record.dv_rtn_m_s,
            )
        )
    return tuple(maneuvers)


def _strategy_plan_mapping(
    foundation: PreviewOptimalOperationsFoundationRun,
    authority: PreviewOptimizedAuthorityReduction,
    optimized: PreviewOptimizedCampaignEvidence,
) -> dict[str, tuple[Maneuver, ...]]:
    if authority.selection.preflight_sha256 != foundation.preflight.preflight_sha256:
        raise ValueError("paired robustness optimized selection does not match foundation preflight")
    if authority.selection.screening_evidence_sha256 != foundation.screening.evidence_sha256:
        raise ValueError("paired robustness optimized selection does not match foundation screening evidence")
    if authority.evaluation.strategy_id != authority.selection.strategy_id:
        raise ValueError("paired robustness optimized strategy id does not match selected strategy")
    if authority.evaluation.candidate_id != authority.selection.candidate_id:
        raise ValueError("paired robustness optimized evaluation does not match selected candidate")
    if optimized.candidate_id != authority.selection.candidate_id:
        raise ValueError("paired robustness optimized campaign does not match selected candidate")
    if (
        optimized.trigger_fraction != authority.selection.screening_candidate.trigger_fraction
        or optimized.target_fraction != authority.selection.screening_candidate.target_fraction
    ):
        raise ValueError("paired robustness optimized campaign parameters do not match selected candidate")

    controlled_id = foundation.preflight.controlled_deputy_id
    plans: dict[str, tuple[Maneuver, ...]] = {
        item.strategy.strategy_id: _ledger_plan(item.campaign, controlled_id)
        for item in foundation.baselines
    }
    plans[authority.evaluation.strategy_id] = _ledger_plan(optimized.campaign, controlled_id)
    expected = {item.strategy.strategy_id for item in foundation.baselines} | {authority.evaluation.strategy_id}
    if set(plans) != expected or len(plans) != 4:
        raise ValueError("paired robustness requires exactly three P2 baselines and one optimized strategy")
    return plans


def _validate_template(
    scenario: ScenarioConfig,
    profile: PreviewOptimalOperationsStudyProfile,
    foundation: PreviewOptimalOperationsFoundationRun,
    config: RobustnessApplicationConfig,
    plans: Mapping[str, tuple[Maneuver, ...]],
) -> str:
    preflight = foundation.preflight
    if scenario.force_model.mode != ForceMode.VALIDATION:
        raise ValueError("paired operational robustness requires VALIDATION force mode")
    if not scenario.orekit_sidecar_url:
        raise ValueError("paired operational robustness requires Orekit sidecar URL")
    if not preflight.robustness_enabled:
        raise ValueError("paired operational robustness requires robustness enabled by preflight")
    if preflight.robustness_campaign_id != config.campaign.campaign_id:
        raise ValueError("paired robustness campaign id does not match preflight")

    sampling_hash = uncertainty_sampling_model_sha256(config.campaign)
    if preflight.robustness_sampling_model_sha256 != sampling_hash:
        raise ValueError("paired robustness sampling model does not match preflight")
    expected_uncertainty = f"robustness:{sampling_hash}"
    if preflight.identity.uncertainty_model_id != expected_uncertainty:
        raise ValueError("paired robustness uncertainty identity does not match study identity")

    # Legacy baseline_maneuvers in the YAML is only a schema carrier here. Validate
    # uncertainty variable names against the longest actual authorized comparator plan.
    maximum_plan = max(plans.values(), key=len)
    validation_config = config.model_copy(update={"baseline_maneuvers": maximum_plan})
    validate_uncertainty_contract(scenario, validation_config)
    known_satellites = {sat.satellite_id for sat in scenario.constellation.satellites}
    for plan in plans.values():
        for maneuver in plan:
            if maneuver.satellite_id not in known_satellites:
                raise ValueError("paired robustness nominal plan targets unknown satellite")
            if maneuver.time_s > profile.campaign_horizon_s:
                raise ValueError("paired robustness nominal maneuver lies outside study horizon")
    return sampling_hash


def _perturbed_request(
    scenario: ScenarioConfig,
    profile: PreviewOptimalOperationsStudyProfile,
    plan: tuple[Maneuver, ...],
    sample: Mapping[str, object],
) -> tuple[PropagationRequest, tuple[int, ...]]:
    materialized = dict(sample)
    satellites = tuple(_perturb_satellite(satellite, materialized) for satellite in scenario.constellation.satellites)
    maneuvers: list[Maneuver] = []
    dropped: list[int] = []
    for index, maneuver in enumerate(plan):
        perturbed = _perturb_maneuver(index, maneuver, materialized, profile.campaign_horizon_s)
        if perturbed is None:
            dropped.append(index)
        else:
            maneuvers.append(perturbed)
    return (
        PropagationRequest(
            scenario_id=scenario.scenario_id,
            epoch=scenario.epoch,
            frame=scenario.frame,
            time_scale=scenario.time_scale,
            satellites=satellites,
            maneuvers=tuple(maneuvers),
            duration_s=profile.campaign_horizon_s,
            output_step_s=min(profile.coast_output_step_s, profile.campaign_horizon_s),
            force_model=scenario.force_model,
            integrator=scenario.integrator,
            seed=_orekit_wire_seed(materialized),
        ),
        tuple(dropped),
    )


def _resource_metrics(
    request: PropagationRequest,
    reserve_fraction: float,
    controlled_deputy_id: str,
) -> tuple[dict[str, float], bool]:
    by_id = {sat.satellite_id: sat for sat in request.satellites}
    maneuvers_by_satellite: dict[str, list[Maneuver]] = {sat_id: [] for sat_id in by_id}
    for maneuver in request.maneuvers:
        if maneuver.satellite_id not in maneuvers_by_satellite:
            raise ValueError("paired robustness perturbed maneuver targets unknown satellite")
        maneuvers_by_satellite[maneuver.satellite_id].append(maneuver)

    total_delta_v = 0.0
    total_propellant = 0.0
    controlled_reserve_margin: float | None = None
    reserve_violation = False
    for satellite_id, satellite in by_id.items():
        delta_v = sum(
            float(np.linalg.norm(np.asarray(item.dv_rtn_m_s, dtype=float)))
            for item in maneuvers_by_satellite[satellite_id]
        )
        used = propellant_used_kg(satellite.spacecraft.initial_mass_kg, delta_v, satellite.spacecraft.isp_s)
        reserve = satellite.spacecraft.propellant_mass_kg * reserve_fraction
        residual = satellite.spacecraft.propellant_mass_kg - used
        margin = residual - reserve
        reserve_violation |= margin < 0.0
        if satellite_id == controlled_deputy_id:
            controlled_reserve_margin = margin
        total_delta_v += delta_v
        total_propellant += used
    if controlled_reserve_margin is None:
        raise ValueError("paired robustness request lacks controlled deputy")
    return (
        {
            "fleet_total_delta_v_m_s": total_delta_v,
            "fleet_total_propellant_used_kg": total_propellant,
            "controlled_propellant_reserve_margin_kg": controlled_reserve_margin,
        },
        reserve_violation,
    )


def _sample_executor(
    scenario: ScenarioConfig,
    profile: PreviewOptimalOperationsStudyProfile,
    config: RobustnessApplicationConfig,
    plan: tuple[Maneuver, ...],
    reference_id: str,
    *,
    propagator: Propagator,
) -> StrategySampleExecutor:
    def execute(sample: Mapping[str, object]) -> CompletedOperationalRealization:
        request, dropped = _perturbed_request(scenario, profile, plan, sample)
        result = propagator.propagate(request)
        _verify_authority(result, request, config.authority)
        margins = reduce_trajectory_hard_margins(
            result,
            scenario.constraints,
            reference_id=reference_id,
            deputy_id=profile.controlled_deputy_id,
        )
        if margins.minimum_fleet_distance_margin_m is None:
            raise ValueError("paired robustness requires fleet-distance evidence")
        resource_metrics, reserve_violation = _resource_metrics(
            request,
            scenario.constraints.propellant_reserve_fraction,
            profile.controlled_deputy_id,
        )
        realization = sample.get("realization")
        sample_sha = sample.get("sample_sha256")
        if isinstance(realization, bool) or not isinstance(realization, int):
            raise TypeError("paired robustness realization must be an integer")
        if not isinstance(sample_sha, str):
            raise TypeError("paired robustness sample_sha256 must be a string")
        return CompletedOperationalRealization(
            realization=realization,
            sample_sha256=sample_sha,
            metrics={
                **resource_metrics,
                "operator_delta_u_phase_corridor_margin_rad": margins.phase_corridor_margin_rad,
                "minimum_fleet_distance_margin_m": margins.minimum_fleet_distance_margin_m,
            },
            violations={
                "phase_corridor": margins.phase_corridor_margin_rad < 0.0,
                "minimum_pair_distance": margins.minimum_fleet_distance_margin_m < 0.0,
                "propellant_reserve": reserve_violation,
                "maneuver_window_unavailable": bool(dropped),
            },
            authority_backend=result.backend,
            authority_force_model_fingerprint=result.force_model_fingerprint,
        )

    return execute


def run_preview_paired_fixed_plan_robustness(
    scenario_path: Path,
    robustness_config_path: Path,
    profile: PreviewOptimalOperationsStudyProfile,
    foundation: PreviewOptimalOperationsFoundationRun,
    authority: PreviewOptimizedAuthorityReduction,
    optimized: PreviewOptimizedCampaignEvidence,
    *,
    propagator: Propagator | None = None,
    sample_generator: SampleGenerator | None = None,
) -> PreviewPairedRobustnessResult:
    """Replay exact nominal strategy plans under one common uncertainty sample set.

    This is fixed-plan robustness, not adaptive closed-loop recourse. No strategy is
    re-optimized or re-authorized inside a realization. The legacy
    `accepted_candidate_id` and `baseline_maneuvers` fields of the robustness YAML
    do not define comparator identity in this paired study; the persisted strategy
    ledgers do.
    """

    scenario = load_scenario(scenario_path)
    config = load_robustness_application_config(robustness_config_path)
    plans = _strategy_plan_mapping(foundation, authority, optimized)
    sampling_hash = _validate_template(scenario, profile, foundation, config, plans)
    resolved = propagator or OrekitSidecarPropagator(scenario.orekit_sidecar_url or "", timeout_s=300.0)
    executors = {
        strategy_id: _sample_executor(
            scenario,
            profile,
            config,
            plan,
            foundation.preflight.reference_id,
            propagator=resolved,
        )
        for strategy_id, plan in plans.items()
    }
    if sample_generator is None:
        study: OperationalRobustnessStudyResult = run_operational_robustness_study(
            config.campaign,
            executors,
        )
    else:
        study = run_operational_robustness_study(
            config.campaign,
            executors,
            sample_generator=sample_generator,
        )
    common = study.strategies[0].common_samples
    if common.sampling_model_sha256 != sampling_hash:
        raise ValueError("paired robustness common sample identity drifted from validated sampling model")
    if robustness_uncertainty_model_id(study.strategies[0]) != foundation.preflight.identity.uncertainty_model_id:
        raise ValueError("paired robustness result uncertainty identity drifted from preflight")
    return PreviewPairedRobustnessResult(
        semantics="paired-common-random-number fixed-plan numerical replay; no adaptive recourse",
        campaign_id=common.campaign_id,
        sampling_model_sha256=common.sampling_model_sha256,
        strategies=study.strategies,
    )
