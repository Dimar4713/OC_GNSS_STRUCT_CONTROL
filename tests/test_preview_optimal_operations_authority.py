from __future__ import annotations

import json
from pathlib import Path

import pytest

from constellation_control.application.run import load_scenario
from constellation_control.control.policies import CorrectionPolicy
from constellation_control.optimization.hybrid import (
    AuthoritativeStateAnchor,
    EventValidationEvidence,
    ScreeningEventBracket,
    ScreeningEventKind,
    StateAnchorKind,
    ValidationOutcomeKind,
)
from constellation_control.optimization.hybrid_authority import HybridCorrectionAuthorityReceipt
from constellation_control.optimization.hybrid_strategy import (
    HybridEventExecutionEvidence,
    HybridValidationJob,
)
from constellation_control.optimization.operations import (
    CredibilityState,
    HardConstraintEvidence,
    NamedObjectiveValue,
    ObjectiveDirection,
)
from constellation_control.optimization.optimal_operations_orchestration import (
    AuthoritativeOperationalOutcomeEvidence,
)
from constellation_control.optimization.optimized_hybrid_execution import (
    OptimizedTriggerBracketEvidence,
)
from constellation_control.preview.optimal_operations_authority import (
    PreviewInitialHybridEventEvidence,
    build_selected_authoritative_evaluation,
    reduce_selected_hybrid_evidence,
    select_screening_candidate,
    write_preview_optimized_authority_evidence,
)
from constellation_control.preview.optimal_operations_execution import (
    PreviewOptimalOperationsFoundationRun,
    PreviewScreeningCandidateEvidence,
    PreviewScreeningEvidence,
)
from constellation_control.preview.optimal_operations_profile import (
    PreviewExecutionPolicyProfile,
    PreviewHardConstraintDefinition,
    PreviewObjectiveDefinition,
    PreviewOperationalPolicySearchProfile,
    PreviewOptimalOperationsStudyProfile,
    PreviewRobustnessPolicy,
    preflight_optimal_operations_study,
    scenario_constraints_identity,
    scenario_integrator_identity,
)


def _scenario_path() -> Path:
    return Path(__file__).parents[1] / "scenarios" / "orekit_validation_smoke.yaml"


def _profile() -> PreviewOptimalOperationsStudyProfile:
    scenario = load_scenario(_scenario_path())
    execution = PreviewExecutionPolicyProfile(
        max_abs_impulse_rtn_m_s=(0.2, 0.2, 0.2),
        min_impulse_bit_m_s=0.001,
        trust_tolerances_roe=(1.0e-6, 1.0e-3, 1.0e-6, 1.0e-6, 1.0e-6, 1.0e-6),
        target_roe=(0.0, 0.0, 0.0, 0.0, 0.0, 0.0),
        w_tracking=10.0,
        w_max=0.5,
    )
    return PreviewOptimalOperationsStudyProfile(
        study_id="preview-optimal-authority-test",
        scenario_name=_scenario_path().name,
        controlled_deputy_id="SYNTH-ADD-45",
        seed=42,
        campaign_horizon_s=3600.0,
        coast_horizon_s=3600.0,
        coast_output_step_s=60.0,
        max_corrections=8,
        authority_times_s=(0.0, 60.0, 120.0),
        maneuver_windows=(True, True),
        execution_policy=execution,
        uncertainty_model_id="deterministic-test-v1",
        search=PreviewOperationalPolicySearchProfile(
            trigger_fraction_bounds=(0.25, 0.95),
            target_fraction_bounds=(0.0, 1.0),
            lhs_samples=4,
            local_seeds=1,
            local_method="SLSQP",
            nsga_population=4,
            nsga_generations=1,
            seed=73,
        ),
        objectives=(
            PreviewObjectiveDefinition(name="propellant_rate", unit="kg/Julian-year", direction="minimize"),
            PreviewObjectiveDefinition(name="correction_frequency", unit="events/Julian-year", direction="minimize"),
        ),
        hard_constraints=(
            PreviewHardConstraintDefinition(name="phase_corridor_margin", unit="rad"),
            PreviewHardConstraintDefinition(name="minimum_fleet_distance_margin", unit="m"),
            PreviewHardConstraintDefinition(name="propellant_reserve_margin", unit="kg"),
        ),
        robustness=PreviewRobustnessPolicy(
            enabled=False,
            recommendation_required=False,
            campaign_id=None,
            uncertainty_model_id=None,
            sampling_model_sha256=None,
        ),
        expected_force_model_fingerprint=scenario.force_model.fingerprint(),
        expected_frame=scenario.frame.value,
        expected_time_scale=scenario.time_scale.value,
        expected_integrator_identity=scenario_integrator_identity(scenario),
        expected_constraints_identity=scenario_constraints_identity(scenario),
        expected_execution_policy_identity=execution.identity(),
    )


def _foundation(*, feasible: bool = True) -> PreviewOptimalOperationsFoundationRun:
    preflight = preflight_optimal_operations_study(_scenario_path(), _profile())
    candidate = PreviewScreeningCandidateEvidence(
        candidate_id="candidate-001",
        stage="nsga2",
        trigger_fraction=0.5,
        target_fraction=0.25,
        objectives=(999.0, 998.0),
        hard_margins=(1.0, 1.0, 1.0),
        metrics={"screening_only_metric": 123.0},
        feasible=feasible,
        screening_only=True,
    )
    screening = PreviewScreeningEvidence(
        candidates=(candidate,),
        pareto_candidate_ids=(candidate.candidate_id,),
        search_config=preflight.search_config,
        screening_only=True,
        evidence_sha256="a" * 64,
    )
    return PreviewOptimalOperationsFoundationRun(
        preflight=preflight,
        baselines=(),
        screening=screening,
        recommendation_strategy_id=None,
    )


def _event(foundation: PreviewOptimalOperationsFoundationRun, *, authorized: bool = True) -> PreviewInitialHybridEventEvidence:
    selection = select_screening_candidate(foundation, "candidate-001")
    bracket = ScreeningEventBracket(
        strategy_id=selection.strategy_id,
        event_id="optimized-event-001",
        event_kind=ScreeningEventKind.OPTIMIZED_TRIGGER,
        predicted_time_s=60.0,
        bracket_start_s=0.0,
        bracket_end_s=120.0,
        predicted_boundary_sign=1,
        predicted_state_coordinate=0.12,
        screening_backend="mean-screening-test",
        screening_force_model_fingerprint=foundation.preflight.identity.force_model_fingerprint,
        screening_output_step_s=60.0,
        screening_config_identity="screening-config-test",
    )
    screening = OptimizedTriggerBracketEvidence(
        candidate_id=selection.candidate_id,
        trigger_fraction=0.5,
        trigger_half_width_rad=0.1,
        target_fraction=0.25,
        hard_corridor_half_width_rad=0.2,
        bracket=bracket,
    )
    anchor = AuthoritativeStateAnchor(
        anchor_id="initial-authority-anchor",
        kind=StateAnchorKind.AUTHORITATIVE_REPLAY,
        anchor_time_s=0.0,
        source_evidence_id="initial-numerical-replay",
        backend="orekit-numerical-test",
        force_model_fingerprint=foundation.preflight.identity.force_model_fingerprint,
        state_digest="state-digest-test",
    )
    validation = EventValidationEvidence(
        strategy_id=selection.strategy_id,
        event_id=bracket.event_id,
        outcome=ValidationOutcomeKind.CONFIRMED,
        screening=bracket,
        state_anchor=anchor,
        validation_start_s=0.0,
        validation_end_s=120.0,
        validation_output_step_s=60.0,
        authority_backend="orekit-numerical-test",
        authority_force_model_fingerprint=foundation.preflight.identity.force_model_fingerprint,
        authority_config_identity="authority-config-test",
        authoritative_event_time_s=60.0,
        authoritative_boundary_sign=1,
        authoritative_state_coordinate=0.12,
        timing_error_s=0.0,
        authority_evidence_id="authority-event-evidence",
    )
    receipt = HybridCorrectionAuthorityReceipt(
        event_validation=validation,
        authority_attempted=True,
        authorized=authorized,
        authority_reason="authorized" if authorized else "numerical-replay-rejected",
        hard_constraints=(
            HardConstraintEvidence(
                name="numerical_authority_authorized",
                unit="signed_boolean_margin",
                margin=0.0 if authorized else -1.0,
                evidence_source="numerical-replay",
            ),
        ),
        resulting_credibility_state=(
            CredibilityState.AUTHORITATIVELY_VALIDATED_CANDIDATE
            if authorized
            else CredibilityState.REJECTED_BY_AUTHORITY
        ),
        deputy_id="SYNTH-ADD-45",
        reference_id="SYNTH-REF",
        replay_backend="orekit-numerical-test" if authorized else None,
        transition_backend="orekit-numerical-test" if authorized else None,
        transition_force_model_fingerprint=(
            foundation.preflight.identity.force_model_fingerprint if authorized else None
        ),
    )
    job = HybridValidationJob(
        screening=bracket,
        anchor=anchor,
        policy=CorrectionPolicy.OPTIMIZED,
        corridor_half_width_rad=0.2,
        validation_output_step_s=60.0,
        authority_config_identity="authority-config-test",
        correction_authority_required=True,
        correction_authority_identity=_profile().execution_policy.identity(),
    )
    return PreviewInitialHybridEventEvidence(
        selection=selection,
        screening_trigger=screening,
        validation_job=job,
        execution=HybridEventExecutionEvidence(
            event_validation=validation,
            correction_authority_receipt=receipt,
        ),
    )


def _outcome() -> AuthoritativeOperationalOutcomeEvidence:
    return AuthoritativeOperationalOutcomeEvidence(
        campaign_termination_reason="campaign-horizon-reached",
        correction_count=3,
        corrections_per_julian_year=3.0,
        cumulative_delta_v_m_s=0.08,
        delta_v_m_s_per_julian_year=0.08,
        cumulative_propellant_used_kg=0.8,
        propellant_kg_per_julian_year=0.8,
        projected_years_to_reserve=12.0,
        minimum_corridor_margin_rad=0.01,
        minimum_fleet_distance_margin_m=1000.0,
        objectives=(
            NamedObjectiveValue(
                name="propellant_rate",
                unit="kg/Julian-year",
                direction=ObjectiveDirection.MINIMIZE,
                value=0.8,
            ),
            NamedObjectiveValue(
                name="correction_frequency",
                unit="events/Julian-year",
                direction=ObjectiveDirection.MINIMIZE,
                value=3.0,
            ),
        ),
        hard_constraints=(
            HardConstraintEvidence(
                name="phase_corridor_margin",
                unit="rad",
                margin=0.01,
                evidence_source="authoritative-outcome",
            ),
            HardConstraintEvidence(
                name="minimum_fleet_distance_margin",
                unit="m",
                margin=1000.0,
                evidence_source="authoritative-outcome",
            ),
            HardConstraintEvidence(
                name="propellant_reserve_margin",
                unit="kg",
                margin=5.0,
                evidence_source="authoritative-outcome",
            ),
        ),
        evidence_id="authoritative-outcome-001",
    )


def test_selected_candidate_reduces_to_authoritative_evaluation_without_screening_scores(tmp_path: Path) -> None:
    foundation = _foundation()
    selection = select_screening_candidate(foundation, "candidate-001")
    hybrid = reduce_selected_hybrid_evidence(selection, (_event(foundation),))
    assert hybrid.complete
    assert hybrid.resulting_credibility_state == CredibilityState.AUTHORITATIVELY_VALIDATED_CANDIDATE

    reduction = build_selected_authoritative_evaluation(foundation, selection, hybrid, _outcome())
    assert reduction.evaluation.operationally_credible
    assert reduction.evaluation.high_fidelity_validation_id is not None
    assert tuple(item.value for item in reduction.evaluation.objectives) == pytest.approx((0.8, 3.0))
    assert 999.0 not in tuple(item.value for item in reduction.evaluation.objectives)
    assert 998.0 not in tuple(item.value for item in reduction.evaluation.objectives)
    assert reduction.robustness_available is False
    assert reduction.recommendation_strategy_id is None

    artifacts = write_preview_optimized_authority_evidence(tmp_path, foundation, reduction)
    manifest = json.loads(Path(artifacts.manifest_path).read_text(encoding="utf-8"))
    assert manifest["credibility_state"] == "authoritatively-validated-candidate"
    assert manifest["robustness_available"] is False
    assert manifest["recommendation_strategy_id"] is None
    assert manifest["preflight_sha256"] == foundation.preflight.preflight_sha256
    assert manifest["screening_evidence_sha256"] == foundation.screening.evidence_sha256


def test_authority_rejection_cannot_promote_candidate() -> None:
    foundation = _foundation()
    selection = select_screening_candidate(foundation, "candidate-001")
    hybrid = reduce_selected_hybrid_evidence(selection, (_event(foundation, authorized=False),))
    assert hybrid.complete
    assert hybrid.resulting_credibility_state == CredibilityState.REJECTED_BY_AUTHORITY

    reduction = build_selected_authoritative_evaluation(foundation, selection, hybrid, _outcome())
    assert reduction.evaluation.credibility_state == CredibilityState.REJECTED_BY_AUTHORITY
    assert reduction.evaluation.high_fidelity_validation_id is None
    assert not reduction.evaluation.operationally_credible
    assert reduction.recommendation_strategy_id is None


def test_infeasible_screening_candidate_cannot_enter_authority() -> None:
    with pytest.raises(ValueError, match="infeasible screening candidate"):
        select_screening_candidate(_foundation(feasible=False), "candidate-001")
