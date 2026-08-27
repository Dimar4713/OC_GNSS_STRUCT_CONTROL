from __future__ import annotations

import hashlib
import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from constellation_control.adapters.orekit.adapter import OrekitSidecarPropagator
from constellation_control.application.run import load_scenario
from constellation_control.domain.models import PropagationRequest
from constellation_control.optimization.operational_policy_search import OperationalPolicyParameters
from constellation_control.preview.optimal_operations_authority import (
    PreviewOptimizedAuthorityArtifacts,
    PreviewOptimizedAuthorityReduction,
    build_selected_authoritative_evaluation,
    discover_selected_initial_trigger,
    reduce_selected_hybrid_evidence,
    select_screening_candidate,
    validate_and_authorize_initial_trigger,
    write_preview_optimized_authority_evidence,
)
from constellation_control.preview.optimal_operations_decision import (
    PreviewOperationalDecisionArtifacts,
    PreviewOperationalDecisionPolicy,
    PreviewOperationalDecisionResult,
    build_preview_operational_decision,
    write_preview_operational_decision,
)
from constellation_control.preview.optimal_operations_execution import (
    PreviewBaselineEvidence,
    PreviewOptimalOperationsFoundationArtifacts,
    PreviewOptimalOperationsFoundationRun,
    PreviewScreeningEvidence,
    run_preview_optimal_operations_foundation,
    write_preview_optimal_operations_foundation,
)
from constellation_control.preview.optimal_operations_profile import (
    PreviewOptimalOperationsPreflight,
    PreviewOptimalOperationsStudyProfile,
)
from constellation_control.preview.optimal_operations_robustness import (
    PreviewPairedRobustnessResult,
    run_preview_paired_fixed_plan_robustness,
)
from constellation_control.preview.optimized_campaign import (
    PreviewOptimizedCampaignEvidence,
    run_authoritative_optimized_outcome,
)
from constellation_control.preview.optimized_screening import build_real_dsst_screening_evaluator

RELEASE_INPUTS_FILE = "optimal_operations_release_inputs.json"
PROFILE_FILE = "optimal_operations_profile.json"


class PreviewOptimalOperationsReleaseInputs(BaseModel):
    model_config = ConfigDict(frozen=True)

    design_scenario_name: str = Field(min_length=1)
    validation_scenario_name: str = Field(min_length=1)
    profile: PreviewOptimalOperationsStudyProfile


class PreviewOptimalOperationsFoundationRelease(BaseModel):
    model_config = ConfigDict(frozen=True)

    foundation: PreviewOptimalOperationsFoundationRun
    artifacts: PreviewOptimalOperationsFoundationArtifacts
    release_inputs_sha256: str


class PreviewOptimalOperationsDecisionRelease(BaseModel):
    model_config = ConfigDict(frozen=True)

    foundation: PreviewOptimalOperationsFoundationRun
    authority: PreviewOptimizedAuthorityReduction
    optimized_campaign: PreviewOptimizedCampaignEvidence
    paired_robustness: PreviewPairedRobustnessResult
    decision: PreviewOperationalDecisionResult
    authority_artifacts: PreviewOptimizedAuthorityArtifacts
    decision_artifacts: PreviewOperationalDecisionArtifacts


def _digest(payload: object) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _scenario_path(root: Path, name: str) -> Path:
    if Path(name).name != name or name in {"", ".", ".."}:
        raise ValueError("scenario/config input must be a plain file name")
    path = (root / name).resolve()
    base = root.resolve()
    if path.parent != base or not path.is_file():
        raise ValueError(f"input file is unavailable: {name}")
    return path


def _safe_run_dir(output_root: Path, group: str, run_id: str) -> Path:
    if any(Path(value).name != value or value in {"", ".", ".."} for value in (group, run_id)):
        raise ValueError("foundation run identity is invalid")
    run_dir = (output_root / group / run_id).resolve()
    root = output_root.resolve()
    try:
        run_dir.relative_to(root)
    except ValueError as exc:
        raise ValueError("foundation run escaped output root") from exc
    if not run_dir.is_dir():
        raise ValueError("foundation run directory is unavailable")
    return run_dir


def _write_release_inputs(run_dir: Path, inputs: PreviewOptimalOperationsReleaseInputs) -> str:
    payload = inputs.model_dump(mode="json")
    digest = _digest(payload)
    (run_dir / PROFILE_FILE).write_text(inputs.profile.model_dump_json(indent=2), encoding="utf-8")
    (run_dir / RELEASE_INPUTS_FILE).write_text(inputs.model_dump_json(indent=2), encoding="utf-8")
    return digest


def _load_foundation(run_dir: Path) -> tuple[PreviewOptimalOperationsFoundationRun, PreviewOptimalOperationsReleaseInputs]:
    preflight = PreviewOptimalOperationsPreflight.model_validate_json(
        (run_dir / "optimal_operations_preflight.json").read_text(encoding="utf-8")
    )
    baselines_raw = json.loads((run_dir / "operational_baselines.json").read_text(encoding="utf-8"))
    if not isinstance(baselines_raw, list):
        raise ValueError("persisted operational baselines must be an array")
    baselines = tuple(PreviewBaselineEvidence.model_validate(item) for item in baselines_raw)
    screening = PreviewScreeningEvidence.model_validate_json(
        (run_dir / "screening_candidates.json").read_text(encoding="utf-8")
    )
    inputs = PreviewOptimalOperationsReleaseInputs.model_validate_json(
        (run_dir / RELEASE_INPUTS_FILE).read_text(encoding="utf-8")
    )
    foundation = PreviewOptimalOperationsFoundationRun(
        preflight=preflight,
        baselines=baselines,
        screening=screening,
        recommendation_strategy_id=None,
    )
    if inputs.profile.study_id != foundation.preflight.study_id:
        raise ValueError("persisted release profile does not match foundation study id")
    return foundation, inputs


def run_preview_optimal_operations_foundation_release(
    scenario_root: Path,
    output_root: Path,
    *,
    design_scenario_name: str,
    validation_scenario_name: str,
    profile: PreviewOptimalOperationsStudyProfile,
) -> PreviewOptimalOperationsFoundationRelease:
    design_path = _scenario_path(scenario_root, design_scenario_name)
    validation_path = _scenario_path(scenario_root, validation_scenario_name)
    if profile.scenario_name != validation_scenario_name:
        raise ValueError("study profile scenario_name must equal the explicit validation scenario file")
    evaluator = build_real_dsst_screening_evaluator(design_path, validation_path, profile)
    foundation = run_preview_optimal_operations_foundation(
        validation_path,
        profile,
        evaluator,
    )
    artifacts = write_preview_optimal_operations_foundation(output_root, foundation)
    inputs = PreviewOptimalOperationsReleaseInputs(
        design_scenario_name=design_scenario_name,
        validation_scenario_name=validation_scenario_name,
        profile=profile,
    )
    release_sha = _write_release_inputs(Path(artifacts.run_dir), inputs)
    return PreviewOptimalOperationsFoundationRelease(
        foundation=foundation,
        artifacts=artifacts,
        release_inputs_sha256=release_sha,
    )


def _design_screening_result(
    design_path: Path,
    profile: PreviewOptimalOperationsStudyProfile,
):
    scenario = load_scenario(design_path)
    if not scenario.orekit_sidecar_url:
        raise ValueError("selected candidate screening requires Orekit DESIGN sidecar")
    request = PropagationRequest(
        scenario_id=scenario.scenario_id,
        epoch=scenario.epoch,
        frame=scenario.frame,
        time_scale=scenario.time_scale,
        satellites=scenario.constellation.satellites,
        maneuvers=(),
        duration_s=profile.campaign_horizon_s,
        output_step_s=min(profile.coast_output_step_s, profile.campaign_horizon_s),
        force_model=scenario.force_model,
        integrator=scenario.integrator,
        seed=profile.seed,
    )
    result = OrekitSidecarPropagator(scenario.orekit_sidecar_url).propagate(request)
    if not result.backend.startswith("orekit-dsst"):
        raise ValueError("selected candidate trigger discovery requires Orekit DSST screening")
    return result, scenario.config_hash()


def run_preview_optimal_operations_decision_release(
    scenario_root: Path,
    output_root: Path,
    *,
    foundation_group: str,
    foundation_run_id: str,
    candidate_id: str,
    robustness_config_name: str,
    decision_policy: PreviewOperationalDecisionPolicy,
    hybrid_validation_output_step_s: float,
    screening_bracket_padding_steps: int,
) -> PreviewOptimalOperationsDecisionRelease:
    if hybrid_validation_output_step_s <= 0.0:
        raise ValueError("hybrid_validation_output_step_s must be explicit and positive")
    if screening_bracket_padding_steps < 0:
        raise ValueError("screening_bracket_padding_steps must be explicit and non-negative")

    foundation_dir = _safe_run_dir(output_root, foundation_group, foundation_run_id)
    foundation, inputs = _load_foundation(foundation_dir)
    profile = inputs.profile
    design_path = _scenario_path(scenario_root, inputs.design_scenario_name)
    validation_path = _scenario_path(scenario_root, inputs.validation_scenario_name)
    robustness_path = _scenario_path(scenario_root, robustness_config_name)

    selection = select_screening_candidate(foundation, candidate_id)
    screening_result, screening_identity = _design_screening_result(design_path, profile)
    trigger = discover_selected_initial_trigger(
        validation_path,
        profile,
        foundation,
        selection,
        screening_result,
        screening_config_identity=screening_identity,
        bracket_padding_steps=screening_bracket_padding_steps,
    )
    if trigger is None:
        raise ValueError("selected screening candidate has no trigger hypothesis inside the declared study horizon")

    validation = load_scenario(validation_path)
    if not validation.orekit_sidecar_url:
        raise ValueError("selected candidate authority requires Orekit numerical sidecar")
    numerical = OrekitSidecarPropagator(validation.orekit_sidecar_url)
    initial_event = validate_and_authorize_initial_trigger(
        validation_path,
        profile,
        foundation,
        selection,
        trigger,
        numerical,
        validation_output_step_s=hybrid_validation_output_step_s,
        authority_config_identity=foundation.preflight.scenario_config_hash,
    )
    hybrid = reduce_selected_hybrid_evidence(selection, (initial_event,))
    parameters = OperationalPolicyParameters(
        trigger_fraction=selection.screening_candidate.trigger_fraction,
        target_fraction=selection.screening_candidate.target_fraction,
    )
    optimized = run_authoritative_optimized_outcome(
        validation_path,
        profile,
        parameters,
        candidate_id=selection.candidate_id,
        propagator=numerical,
    )
    authority = build_selected_authoritative_evaluation(
        foundation,
        selection,
        hybrid,
        optimized.outcome,
    )
    authority_artifacts = write_preview_optimized_authority_evidence(output_root, foundation, authority)

    paired = run_preview_paired_fixed_plan_robustness(
        validation_path,
        robustness_path,
        profile,
        foundation,
        authority,
        optimized,
        propagator=numerical,
    )
    decision = build_preview_operational_decision(
        foundation,
        authority,
        paired.strategies,
        decision_policy,
    )
    decision_artifacts = write_preview_operational_decision(
        output_root,
        foundation,
        authority,
        paired.strategies,
        decision,
    )
    return PreviewOptimalOperationsDecisionRelease(
        foundation=foundation,
        authority=authority,
        optimized_campaign=optimized,
        paired_robustness=paired,
        decision=decision,
        authority_artifacts=authority_artifacts,
        decision_artifacts=decision_artifacts,
    )
