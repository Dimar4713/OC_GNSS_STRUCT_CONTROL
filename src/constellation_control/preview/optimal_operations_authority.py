from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
from pydantic import BaseModel, ConfigDict

from constellation_control.application.run import load_scenario
from constellation_control.control.policies import CorrectionPolicy, CorrectionPolicyState
from constellation_control.domain.models import PropagationRequest, PropagationResult
from constellation_control.domain.protocols import Propagator
from constellation_control.optimization.hybrid_authority import authorize_validated_phase_event
from constellation_control.optimization.hybrid_execution import AuthoritativePhaseWindowResult
from constellation_control.optimization.hybrid_strategy import (
    HybridEventExecutionEvidence,
    HybridStrategyValidationResult,
    HybridValidationJob,
    run_hybrid_strategy_validation,
)
from constellation_control.optimization.operational_policy_search import (
    OperationalPolicyCandidate,
    OperationalPolicyParameters,
)
from constellation_control.optimization.optimal_operations_orchestration import (
    AuthoritativeOperationalOutcomeEvidence,
    build_optimized_operational_evaluation,
)
from constellation_control.optimization.operations import OperationalStrategyEvaluation
from constellation_control.optimization.optimized_hybrid_execution import (
    OptimizedTriggerBracketEvidence,
    discover_optimized_trigger_bracket,
)
from constellation_control.optimization.optimized_initial_validation import validate_initial_optimized_trigger_replay
from constellation_control.preview.optimal_operations_execution import (
    PreviewOptimalOperationsFoundationRun,
    PreviewScreeningCandidateEvidence,
)
from constellation_control.preview.optimal_operations_profile import PreviewOptimalOperationsStudyProfile


class PreviewOptimizedCandidateSelection(BaseModel):
    model_config = ConfigDict(frozen=True)

    candidate_id: str
    strategy_id: str
    preflight_sha256: str
    screening_evidence_sha256: str
    screening_candidate: PreviewScreeningCandidateEvidence
    selection_sha256: str


class PreviewInitialHybridEventEvidence(BaseModel):
    model_config = ConfigDict(frozen=True)

    selection: PreviewOptimizedCandidateSelection
    screening_trigger: OptimizedTriggerBracketEvidence
    validation_job: HybridValidationJob
    execution: HybridEventExecutionEvidence


class PreviewOptimizedAuthorityReduction(BaseModel):
    model_config = ConfigDict(frozen=True)

    selection: PreviewOptimizedCandidateSelection
    hybrid: HybridStrategyValidationResult
    evaluation: OperationalStrategyEvaluation
    recommendation_strategy_id: None = None
    robustness_available: bool


def _digest(payload: object) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def select_screening_candidate(
    foundation: PreviewOptimalOperationsFoundationRun,
    candidate_id: str,
) -> PreviewOptimizedCandidateSelection:
    matches = [item for item in foundation.screening.candidates if item.candidate_id == candidate_id]
    if len(matches) != 1:
        raise ValueError("candidate_id must identify exactly one persisted screening candidate")
    candidate = matches[0]
    if not candidate.screening_only:
        raise ValueError("selected optimized candidate must retain screening-only provenance")
    if not candidate.feasible:
        raise ValueError("infeasible screening candidate cannot enter hybrid authority")
    strategy_id = f"optimized-{candidate.candidate_id}"
    payload = {
        "candidate": candidate.model_dump(mode="json"),
        "strategy_id": strategy_id,
        "preflight_sha256": foundation.preflight.preflight_sha256,
        "screening_evidence_sha256": foundation.screening.evidence_sha256,
    }
    return PreviewOptimizedCandidateSelection(
        candidate_id=candidate.candidate_id,
        strategy_id=strategy_id,
        preflight_sha256=foundation.preflight.preflight_sha256,
        screening_evidence_sha256=foundation.screening.evidence_sha256,
        screening_candidate=candidate,
        selection_sha256=_digest(payload),
    )


def _candidate(selection: PreviewOptimizedCandidateSelection) -> OperationalPolicyCandidate:
    item = selection.screening_candidate
    return OperationalPolicyCandidate(
        candidate_id=item.candidate_id,
        stage=item.stage,
        parameters=OperationalPolicyParameters(
            trigger_fraction=item.trigger_fraction,
            target_fraction=item.target_fraction,
        ),
        objectives=item.objectives,
        hard_margins=item.hard_margins,
        metrics=item.metrics,
        feasible=item.feasible,
        screening_only=item.screening_only,
    )


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


def discover_selected_initial_trigger(
    scenario_path: Path,
    profile: PreviewOptimalOperationsStudyProfile,
    foundation: PreviewOptimalOperationsFoundationRun,
    selection: PreviewOptimizedCandidateSelection,
    screening_result: PropagationResult,
    *,
    screening_config_identity: str,
    initial_policy_state: CorrectionPolicyState | None = None,
    bracket_padding_steps: int = 1,
) -> OptimizedTriggerBracketEvidence | None:
    if selection.preflight_sha256 != foundation.preflight.preflight_sha256:
        raise ValueError("candidate selection preflight does not match foundation preflight")
    if selection.screening_evidence_sha256 != foundation.screening.evidence_sha256:
        raise ValueError("candidate selection screening evidence does not match foundation evidence")
    scenario = load_scenario(scenario_path)
    if scenario.config_hash() != foundation.preflight.scenario_config_hash:
        raise ValueError("selected candidate scenario does not match foundation ScenarioConfig")
    if profile.controlled_deputy_id != foundation.preflight.controlled_deputy_id:
        raise ValueError("selected candidate controlled deputy does not match foundation preflight")
    candidate = _candidate(selection)
    return discover_optimized_trigger_bracket(
        screening_result,
        strategy_id=selection.strategy_id,
        candidate_id=selection.candidate_id,
        parameters=candidate.parameters,
        reference_id=foundation.preflight.reference_id,
        deputy_id=foundation.preflight.controlled_deputy_id,
        hard_corridor_half_width_rad=scenario.constraints.phase_corridor_rad,
        initial_policy_state=initial_policy_state or CorrectionPolicyState(),
        output_step_s=screening_result.times_s[1] - screening_result.times_s[0],
        screening_config_identity=screening_config_identity,
        bracket_padding_steps=bracket_padding_steps,
    )


def validate_and_authorize_initial_trigger(
    scenario_path: Path,
    profile: PreviewOptimalOperationsStudyProfile,
    foundation: PreviewOptimalOperationsFoundationRun,
    selection: PreviewOptimizedCandidateSelection,
    screening: OptimizedTriggerBracketEvidence,
    propagator: Propagator,
    *,
    validation_output_step_s: float,
    authority_config_identity: str,
    initial_policy_state: CorrectionPolicyState | None = None,
) -> PreviewInitialHybridEventEvidence:
    if screening.candidate_id != selection.candidate_id or screening.bracket.strategy_id != selection.strategy_id:
        raise ValueError("optimized trigger evidence does not match selected candidate")
    scenario = load_scenario(scenario_path)
    if scenario.config_hash() != foundation.preflight.scenario_config_hash:
        raise ValueError("hybrid authority scenario does not match foundation preflight")
    candidate = _candidate(selection)
    initial = _initial_request(scenario_path, foundation.preflight.identity.seed)
    optimized_window = validate_initial_optimized_trigger_replay(
        propagator,
        initial,
        screening,
        reference_id=foundation.preflight.reference_id,
        deputy_id=foundation.preflight.controlled_deputy_id,
        parameters=candidate.parameters,
        initial_policy_state=initial_policy_state or CorrectionPolicyState(),
        validation_output_step_s=validation_output_step_s,
        authority_config_identity=authority_config_identity,
    )
    generic_window = AuthoritativePhaseWindowResult(
        evidence=optimized_window.evidence,
        validation_request=optimized_window.validation_request,
        event=optimized_window.event,
    )
    authority = authorize_validated_phase_event(
        propagator,
        generic_window,
        scenario.constraints,
        profile.execution_policy.backend_policy(),
        np.asarray(profile.authority_times_s, dtype=float),
        np.asarray(profile.maneuver_windows, dtype=bool),
        deputy_id=foundation.preflight.controlled_deputy_id,
    )
    anchor = optimized_window.evidence.state_anchor
    if anchor is None:
        raise ValueError("initial optimized validation did not retain an authoritative anchor")
    job = HybridValidationJob(
        screening=screening.bracket,
        anchor=anchor,
        policy=CorrectionPolicy.OPTIMIZED,
        corridor_half_width_rad=scenario.constraints.phase_corridor_rad,
        validation_output_step_s=validation_output_step_s,
        authority_config_identity=authority_config_identity,
        correction_authority_required=True,
        correction_authority_identity=profile.execution_policy.identity(),
    )
    execution = HybridEventExecutionEvidence(
        event_validation=optimized_window.evidence,
        correction_authority_receipt=authority.receipt,
    )
    return PreviewInitialHybridEventEvidence(
        selection=selection,
        screening_trigger=screening,
        validation_job=job,
        execution=execution,
    )


def reduce_selected_hybrid_evidence(
    selection: PreviewOptimizedCandidateSelection,
    events: tuple[PreviewInitialHybridEventEvidence, ...],
) -> HybridStrategyValidationResult:
    if not events:
        raise ValueError("selected candidate hybrid reduction requires declared event evidence")
    if any(item.selection.selection_sha256 != selection.selection_sha256 for item in events):
        raise ValueError("hybrid event evidence belongs to a different candidate selection")
    jobs = tuple(item.validation_job for item in events)
    evidence_by_key = {
        item.validation_job.exact_key(): item.execution
        for item in events
    }
    return run_hybrid_strategy_validation(
        jobs,
        executor=lambda job: evidence_by_key.get(job.exact_key()),
    )


def build_selected_authoritative_evaluation(
    foundation: PreviewOptimalOperationsFoundationRun,
    selection: PreviewOptimizedCandidateSelection,
    hybrid: HybridStrategyValidationResult,
    outcome: AuthoritativeOperationalOutcomeEvidence,
) -> PreviewOptimizedAuthorityReduction:
    if selection.preflight_sha256 != foundation.preflight.preflight_sha256:
        raise ValueError("selected candidate preflight lineage does not match foundation")
    evaluation = build_optimized_operational_evaluation(
        strategy_id=selection.strategy_id,
        candidate=_candidate(selection),
        hybrid=hybrid,
        identity=foundation.preflight.identity,
        outcome=outcome,
        robustness=None,
    )
    if evaluation.robustness_available or evaluation.robustness_evidence is not None:
        raise ValueError("Preview 0.2 hybrid-authority slice must not fabricate robustness")
    return PreviewOptimizedAuthorityReduction(
        selection=selection,
        hybrid=hybrid,
        evaluation=evaluation,
        recommendation_strategy_id=None,
        robustness_available=False,
    )
