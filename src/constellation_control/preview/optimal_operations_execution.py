from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from pathlib import Path

import numpy as np
from pydantic import BaseModel, ConfigDict

from constellation_control.adapters.orekit.adapter import OrekitSidecarPropagator
from constellation_control.analysis.campaign_hard_margins import (
    CampaignTrajectoryHardMargins,
    reduce_trajectory_hard_margins,
)
from constellation_control.analysis.closed_loop_metrics import (
    ClosedLoopOperationalMetrics,
    analyze_closed_loop_operations,
)
from constellation_control.application.run import load_scenario
from constellation_control.control.campaign import ClosedLoopCampaignResult, run_closed_loop_campaign
from constellation_control.control.policies import CorrectionPolicy
from constellation_control.domain.models import Maneuver, PropagationRequest, PropagationResult
from constellation_control.domain.protocols import Propagator
from constellation_control.optimization.operational_policy_search import (
    OperationalPolicyCandidate,
    OperationalPolicyEvaluation,
    OperationalPolicyParameters,
    OperationalPolicySearchResult,
    run_operational_policy_screening_search,
)
from constellation_control.optimization.operations import (
    CredibilityState,
    HardConstraintEvidence,
    NamedObjectiveValue,
    OperationalStrategyEvaluation,
    OperationalStrategyKind,
)
from constellation_control.preview.optimal_operations_profile import (
    PreviewHardConstraintDefinition,
    PreviewObjectiveDefinition,
    PreviewOptimalOperationsPreflight,
    PreviewOptimalOperationsStudyProfile,
    preflight_optimal_operations_study,
)


class PreviewBaselineEvidence(BaseModel):
    model_config = ConfigDict(frozen=True)

    strategy: OperationalStrategyEvaluation
    campaign: ClosedLoopCampaignResult
    operational_metrics: ClosedLoopOperationalMetrics
    trajectory_margins: CampaignTrajectoryHardMargins
    replay_backend: str
    replay_backend_version: str
    replay_force_model_fingerprint: str
    replay_maneuver_count: int
    replay_evidence_sha256: str


class PreviewScreeningCandidateEvidence(BaseModel):
    model_config = ConfigDict(frozen=True)

    candidate_id: str
    stage: str
    trigger_fraction: float
    target_fraction: float
    objectives: tuple[float, ...]
    hard_margins: tuple[float, ...]
    metrics: dict[str, float]
    feasible: bool
    screening_only: bool


class PreviewScreeningEvidence(BaseModel):
    model_config = ConfigDict(frozen=True)

    candidates: tuple[PreviewScreeningCandidateEvidence, ...]
    pareto_candidate_ids: tuple[str, ...]
    search_config: dict[str, object]
    screening_only: bool
    evidence_sha256: str


class PreviewOptimalOperationsFoundationRun(BaseModel):
    model_config = ConfigDict(frozen=True)

    preflight: PreviewOptimalOperationsPreflight
    baselines: tuple[PreviewBaselineEvidence, ...]
    screening: PreviewScreeningEvidence
    recommendation_strategy_id: None = None


class PreviewOptimalOperationsFoundationArtifacts(BaseModel):
    model_config = ConfigDict(frozen=True)

    run_dir: str
    preflight_path: str
    baselines_path: str
    screening_path: str
    manifest_path: str
    run_evidence_sha256: str


def _digest(payload: object) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _initial_request(scenario_path: Path, seed: int) -> PropagationRequest:
    scenario = load_scenario(scenario_path)
    return PropagationRequest(
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
        seed=seed,
    )


def _full_horizon_replay_request(
    initial: PropagationRequest,
    campaign: ClosedLoopCampaignResult,
    profile: PreviewOptimalOperationsStudyProfile,
) -> PropagationRequest:
    maneuvers = tuple(
        Maneuver(
            satellite_id=profile.controlled_deputy_id,
            time_s=record.event_time_s,
            dv_rtn_m_s=record.dv_rtn_m_s,
        )
        for record in campaign.resource_ledger
    )
    return initial.model_copy(
        update={
            "maneuvers": maneuvers,
            "duration_s": profile.campaign_horizon_s,
            "output_step_s": min(profile.coast_output_step_s, profile.campaign_horizon_s),
        }
    )


def _validate_replay_authority(
    replay: PropagationResult,
    preflight: PreviewOptimalOperationsPreflight,
) -> None:
    if not replay.backend.startswith("orekit-numerical"):
        raise ValueError("operational baseline replay requires orekit-numerical authority")
    if replay.force_model_fingerprint != preflight.identity.force_model_fingerprint:
        raise ValueError("operational baseline replay fingerprint does not match study identity")


def _validate_campaign_authority(
    policy: CorrectionPolicy,
    campaign: ClosedLoopCampaignResult,
    preflight: PreviewOptimalOperationsPreflight,
) -> None:
    if policy == CorrectionPolicy.NO_CONTROL:
        if campaign.correction_count != 0 or campaign.resource_ledger or campaign.authority_attempts:
            raise ValueError("NO_CONTROL baseline must retain zero-authority execution semantics")
        return
    if campaign.elapsed_time_s + 1.0e-9 < preflight.identity.campaign_horizon_s:
        raise ValueError(
            "controlled operational baseline did not cover the declared campaign horizon; "
            f"termination={campaign.termination_reason}"
        )
    if campaign.correction_count != len(campaign.resource_ledger):
        raise ValueError("controlled baseline correction count does not match resource ledger")
    for record in campaign.resource_ledger:
        if not record.replay_backend.startswith("orekit-numerical"):
            raise ValueError("controlled baseline resource ledger lacks numerical replay authority")
        if record.force_model_fingerprint != preflight.identity.force_model_fingerprint:
            raise ValueError("controlled baseline resource fingerprint does not match study identity")


def _objective_value(
    definition: PreviewObjectiveDefinition,
    campaign: ClosedLoopCampaignResult,
    metrics: ClosedLoopOperationalMetrics,
) -> float:
    if definition.name == "cumulative_delta_v" and definition.unit == "m/s":
        return campaign.cumulative_delta_v_m_s
    if definition.name == "cumulative_propellant" and definition.unit == "kg":
        return campaign.cumulative_propellant_used_kg
    if definition.name == "correction_count" and definition.unit == "events":
        return float(campaign.correction_count)

    if campaign.policy == CorrectionPolicy.NO_CONTROL:
        if definition.name == "propellant_rate" and definition.unit == "kg/Julian-year":
            return 0.0
        if definition.name == "correction_frequency" and definition.unit == "events/Julian-year":
            return 0.0
        if definition.name == "delta_v_rate" and definition.unit == "m/s/Julian-year":
            return 0.0

    annualized = metrics.annualized
    if definition.name == "propellant_rate" and definition.unit == "kg/Julian-year":
        value = annualized.propellant_kg_per_julian_year
    elif definition.name == "correction_frequency" and definition.unit == "events/Julian-year":
        value = annualized.corrections_per_julian_year
    elif definition.name == "delta_v_rate" and definition.unit == "m/s/Julian-year":
        value = annualized.delta_v_m_s_per_julian_year
    elif definition.name == "projected_lifetime" and definition.unit == "Julian-year":
        value = annualized.projected_years_to_reserve
    else:
        raise ValueError(f"unsupported operational objective definition: {definition.name} [{definition.unit}]")
    if value is None:
        raise ValueError(
            f"operational objective {definition.name} is unavailable for {campaign.policy.value}; "
            f"annualization={annualized.unavailable_reason}; lifetime={annualized.lifetime_projection_reason}"
        )
    return float(value)


def _hard_constraint(
    definition: PreviewHardConstraintDefinition,
    campaign: ClosedLoopCampaignResult,
    margins: CampaignTrajectoryHardMargins,
) -> HardConstraintEvidence:
    if definition.name == "phase_corridor_margin" and definition.unit == "rad":
        return HardConstraintEvidence(
            name=definition.name,
            unit=definition.unit,
            margin=margins.phase_corridor_margin_rad,
            evidence_source="full-horizon orekit-numerical replay output grid",
        )
    if definition.name == "minimum_fleet_distance_margin" and definition.unit == "m":
        if margins.minimum_fleet_distance_margin_m is None:
            raise ValueError("fleet-distance hard margin unavailable from authoritative replay")
        return HardConstraintEvidence(
            name=definition.name,
            unit=definition.unit,
            margin=margins.minimum_fleet_distance_margin_m,
            evidence_source="full-horizon orekit-numerical replay Cartesian output grid",
        )
    if definition.name == "propellant_reserve_margin" and definition.unit == "kg":
        return HardConstraintEvidence(
            name=definition.name,
            unit=definition.unit,
            margin=campaign.controlled_propellant_remaining_kg - campaign.controlled_required_reserve_kg,
            evidence_source="accepted P2 resource ledger terminal state",
        )
    raise ValueError(f"unsupported operational hard constraint definition: {definition.name} [{definition.unit}]")


def _strategy_kind(policy: CorrectionPolicy) -> OperationalStrategyKind:
    mapping = {
        CorrectionPolicy.NO_CONTROL: OperationalStrategyKind.NO_CONTROL_BASELINE,
        CorrectionPolicy.RETURN_TO_CENTER: OperationalStrategyKind.RETURN_TO_CENTER_BASELINE,
        CorrectionPolicy.BOUNDARY_TO_BOUNDARY: OperationalStrategyKind.BOUNDARY_TO_BOUNDARY_BASELINE,
    }
    return mapping[policy]


def _strategy_id(policy: CorrectionPolicy) -> str:
    mapping = {
        CorrectionPolicy.NO_CONTROL: "baseline-no-control",
        CorrectionPolicy.RETURN_TO_CENTER: "baseline-return-to-center",
        CorrectionPolicy.BOUNDARY_TO_BOUNDARY: "baseline-boundary-to-boundary",
    }
    return mapping[policy]


def _run_baseline(
    *,
    scenario_path: Path,
    profile: PreviewOptimalOperationsStudyProfile,
    preflight: PreviewOptimalOperationsPreflight,
    policy: CorrectionPolicy,
    propagator: Propagator,
) -> PreviewBaselineEvidence:
    scenario = load_scenario(scenario_path)
    initial = _initial_request(scenario_path, profile.seed)
    campaign = run_closed_loop_campaign(
        propagator,
        initial,
        scenario.constraints,
        policy,
        profile.execution_policy.backend_policy(),
        np.asarray(profile.authority_times_s, dtype=float),
        np.asarray(profile.maneuver_windows, dtype=bool),
        campaign_horizon_s=profile.campaign_horizon_s,
        coast_horizon_s=profile.coast_horizon_s,
        coast_output_step_s=profile.coast_output_step_s,
        max_corrections=profile.max_corrections,
        deputy_id=profile.controlled_deputy_id,
    )
    _validate_campaign_authority(policy, campaign, preflight)
    metrics = analyze_closed_loop_operations(campaign)
    replay_request = _full_horizon_replay_request(initial, campaign, profile)
    replay = propagator.propagate(replay_request)
    _validate_replay_authority(replay, preflight)
    margins = reduce_trajectory_hard_margins(
        replay,
        scenario.constraints,
        reference_id=preflight.reference_id,
        deputy_id=preflight.controlled_deputy_id,
    )
    objectives = tuple(
        NamedObjectiveValue(
            name=definition.name,
            unit=definition.unit,
            direction=definition.direction,
            value=_objective_value(definition, campaign, metrics),
        )
        for definition in profile.objectives
    )
    hard_constraints = tuple(
        _hard_constraint(definition, campaign, margins) for definition in profile.hard_constraints
    )
    strategy = OperationalStrategyEvaluation(
        strategy_id=_strategy_id(policy),
        kind=_strategy_kind(policy),
        credibility_state=CredibilityState.AUTHORITATIVE_BASELINE,
        identity=preflight.identity,
        campaign_termination_reason=campaign.termination_reason,
        correction_count=campaign.correction_count,
        corrections_per_julian_year=(
            0.0 if policy == CorrectionPolicy.NO_CONTROL else metrics.annualized.corrections_per_julian_year
        ),
        cumulative_delta_v_m_s=campaign.cumulative_delta_v_m_s,
        delta_v_m_s_per_julian_year=(
            0.0 if policy == CorrectionPolicy.NO_CONTROL else metrics.annualized.delta_v_m_s_per_julian_year
        ),
        cumulative_propellant_used_kg=campaign.cumulative_propellant_used_kg,
        propellant_kg_per_julian_year=(
            0.0 if policy == CorrectionPolicy.NO_CONTROL else metrics.annualized.propellant_kg_per_julian_year
        ),
        projected_years_to_reserve=metrics.annualized.projected_years_to_reserve,
        minimum_corridor_margin_rad=margins.phase_corridor_margin_rad,
        minimum_fleet_distance_margin_m=margins.minimum_fleet_distance_margin_m,
        settling_mean_s=metrics.rearm_settling_intervals.seconds.mean,
        coast_mean_s=metrics.post_rearm_coast_intervals.seconds.mean,
        objectives=objectives,
        hard_constraints=hard_constraints,
        authority_backend=replay.backend,
        authority_force_model_fingerprint=replay.force_model_fingerprint,
        provenance={
            "preflight_sha256": preflight.preflight_sha256,
            "scenario_config_hash": preflight.scenario_config_hash,
            "controlled_deputy_id": preflight.controlled_deputy_id,
            "reference_id": preflight.reference_id,
            "trajectory_semantics": "full-horizon replay of exact accepted resource-ledger maneuvers",
        },
    )
    replay_payload = {
        "strategy": strategy.model_dump(mode="json"),
        "margins": margins.model_dump(mode="json"),
        "backend": replay.backend,
        "backend_version": replay.backend_version,
        "fingerprint": replay.force_model_fingerprint,
        "maneuvers": [item.model_dump(mode="json") for item in replay_request.maneuvers],
    }
    return PreviewBaselineEvidence(
        strategy=strategy,
        campaign=campaign,
        operational_metrics=metrics,
        trajectory_margins=margins,
        replay_backend=replay.backend,
        replay_backend_version=replay.backend_version,
        replay_force_model_fingerprint=replay.force_model_fingerprint,
        replay_maneuver_count=len(replay_request.maneuvers),
        replay_evidence_sha256=_digest(replay_payload),
    )


def run_authoritative_p2_baselines(
    scenario_path: Path,
    profile: PreviewOptimalOperationsStudyProfile,
    *,
    propagator: Propagator | None = None,
) -> tuple[PreviewOptimalOperationsPreflight, tuple[PreviewBaselineEvidence, ...]]:
    preflight = preflight_optimal_operations_study(scenario_path, profile)
    scenario = load_scenario(scenario_path)
    if propagator is None:
        assert scenario.orekit_sidecar_url is not None
        resolved: Propagator = OrekitSidecarPropagator(scenario.orekit_sidecar_url)
    else:
        resolved = propagator
    baselines = tuple(
        _run_baseline(
            scenario_path=scenario_path,
            profile=profile,
            preflight=preflight,
            policy=policy,
            propagator=resolved,
        )
        for policy in (
            CorrectionPolicy.NO_CONTROL,
            CorrectionPolicy.RETURN_TO_CENTER,
            CorrectionPolicy.BOUNDARY_TO_BOUNDARY,
        )
    )
    identity = baselines[0].strategy.identity
    if any(item.strategy.identity != identity for item in baselines[1:]):
        raise ValueError("P2 baseline evaluations do not share one OperationalStudyIdentity")
    return preflight, baselines


def _screening_candidate(candidate: OperationalPolicyCandidate) -> PreviewScreeningCandidateEvidence:
    return PreviewScreeningCandidateEvidence(
        candidate_id=candidate.candidate_id,
        stage=candidate.stage,
        trigger_fraction=candidate.parameters.trigger_fraction,
        target_fraction=candidate.parameters.target_fraction,
        objectives=candidate.objectives,
        hard_margins=candidate.hard_margins,
        metrics=dict(sorted(candidate.metrics.items())),
        feasible=candidate.feasible,
        screening_only=candidate.screening_only,
    )


def run_screening_only_candidate_search(
    profile: PreviewOptimalOperationsStudyProfile,
    preflight: PreviewOptimalOperationsPreflight,
    evaluator: Callable[[OperationalPolicyParameters], OperationalPolicyEvaluation],
) -> PreviewScreeningEvidence:
    expected = profile.search.backend_config().model_dump(mode="json")
    if preflight.search_config != expected:
        raise ValueError("screening search config does not match preflighted explicit profile")
    result: OperationalPolicySearchResult = run_operational_policy_screening_search(
        profile.search.backend_config(), evaluator
    )
    if any(not candidate.screening_only for candidate in result.candidates):
        raise ValueError("screening candidate attempted to self-promote operational credibility")
    candidates = tuple(_screening_candidate(item) for item in result.candidates)
    payload = {
        "preflight_sha256": preflight.preflight_sha256,
        "search_config": expected,
        "candidates": [item.model_dump(mode="json") for item in candidates],
        "pareto_candidate_ids": result.pareto_candidate_ids,
    }
    return PreviewScreeningEvidence(
        candidates=candidates,
        pareto_candidate_ids=result.pareto_candidate_ids,
        search_config=expected,
        screening_only=True,
        evidence_sha256=_digest(payload),
    )


def run_preview_optimal_operations_foundation(
    scenario_path: Path,
    profile: PreviewOptimalOperationsStudyProfile,
    screening_evaluator: Callable[[OperationalPolicyParameters], OperationalPolicyEvaluation],
    *,
    propagator: Propagator | None = None,
) -> PreviewOptimalOperationsFoundationRun:
    preflight, baselines = run_authoritative_p2_baselines(
        scenario_path,
        profile,
        propagator=propagator,
    )
    screening = run_screening_only_candidate_search(profile, preflight, screening_evaluator)
    return PreviewOptimalOperationsFoundationRun(
        preflight=preflight,
        baselines=baselines,
        screening=screening,
        recommendation_strategy_id=None,
    )


def write_preview_optimal_operations_foundation(
    output_root: Path,
    run: PreviewOptimalOperationsFoundationRun,
) -> PreviewOptimalOperationsFoundationArtifacts:
    payload = run.model_dump(mode="json")
    run_sha = _digest(payload)
    run_dir = output_root / run.preflight.study_id / f"foundation-{run_sha[:16]}"
    run_dir.mkdir(parents=True, exist_ok=True)

    preflight_path = run_dir / "optimal_operations_preflight.json"
    baselines_path = run_dir / "operational_baselines.json"
    screening_path = run_dir / "screening_candidates.json"
    manifest_path = run_dir / "foundation_manifest.json"

    preflight_path.write_text(run.preflight.model_dump_json(indent=2), encoding="utf-8")
    baselines_path.write_text(
        json.dumps([item.model_dump(mode="json") for item in run.baselines], indent=2, sort_keys=True),
        encoding="utf-8",
    )
    screening_path.write_text(run.screening.model_dump_json(indent=2), encoding="utf-8")
    manifest = {
        "study_id": run.preflight.study_id,
        "preflight_sha256": run.preflight.preflight_sha256,
        "run_evidence_sha256": run_sha,
        "baseline_strategy_ids": [item.strategy.strategy_id for item in run.baselines],
        "screening_evidence_sha256": run.screening.evidence_sha256,
        "screening_only": True,
        "recommendation_strategy_id": None,
        "semantics": "P2 authoritative baselines plus screening-only optimized candidates; no final recommendation",
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    return PreviewOptimalOperationsFoundationArtifacts(
        run_dir=str(run_dir),
        preflight_path=str(preflight_path),
        baselines_path=str(baselines_path),
        screening_path=str(screening_path),
        manifest_path=str(manifest_path),
        run_evidence_sha256=run_sha,
    )
