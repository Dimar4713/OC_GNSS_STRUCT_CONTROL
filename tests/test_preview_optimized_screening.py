from __future__ import annotations

from pathlib import Path

import pytest

from constellation_control.application.run import load_scenario
from constellation_control.optimization.operational_policy_search import OperationalPolicyParameters
from constellation_control.preview.optimal_operations_profile import (
    PreviewExecutionPolicyProfile,
    PreviewHardConstraintDefinition,
    PreviewObjectiveDefinition,
    PreviewOperationalPolicySearchProfile,
    PreviewOptimalOperationsStudyProfile,
    PreviewRobustnessPolicy,
    scenario_constraints_identity,
    scenario_integrator_identity,
)
from constellation_control.preview.optimized_screening import (
    PreviewScreeningCampaignEvidence,
    _validate_screening_compatibility,
    build_real_dsst_screening_evaluator,
)


ROOT = Path(__file__).parents[1]
VALIDATION = ROOT / "scenarios" / "orekit_validation_smoke.yaml"
DESIGN = ROOT / "scenarios" / "orekit_design_smoke.yaml"
SYNTHETIC = ROOT / "scenarios" / "design_pipeline_screening_smoke.yaml"


def _profile(*, maximize_second: bool = True) -> PreviewOptimalOperationsStudyProfile:
    scenario = load_scenario(VALIDATION)
    execution = PreviewExecutionPolicyProfile(
        max_abs_impulse_rtn_m_s=(0.2, 0.2, 0.2),
        min_impulse_bit_m_s=0.001,
        trust_tolerances_roe=(1.0e-6, 1.0e-3, 1.0e-6, 1.0e-6, 1.0e-6, 1.0e-6),
        target_roe=(0.0, 0.0, 0.0, 0.0, 0.0, 0.0),
        w_tracking=10.0,
        w_max=0.5,
    )
    return PreviewOptimalOperationsStudyProfile(
        study_id="preview-real-screening-test",
        scenario_name=VALIDATION.name,
        controlled_deputy_id="SYNTH-ADD-45",
        seed=42,
        campaign_horizon_s=3600.0,
        coast_horizon_s=1800.0,
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
            PreviewObjectiveDefinition(name="cumulative_delta_v", unit="m/s", direction="minimize"),
            PreviewObjectiveDefinition(
                name="correction_count",
                unit="events",
                direction="maximize" if maximize_second else "minimize",
            ),
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


def _evidence() -> PreviewScreeningCampaignEvidence:
    return PreviewScreeningCampaignEvidence(
        candidate_id="dsst-candidate",
        trigger_fraction=0.5,
        target_fraction=0.25,
        screening_backend="orekit-dsst-design",
        screening_force_model_fingerprint="a" * 64,
        elapsed_time_s=3600.0,
        correction_count=2,
        cumulative_delta_v_m_s=0.04,
        cumulative_propellant_used_kg=0.03,
        phase_corridor_margin_rad=0.02,
        minimum_fleet_distance_margin_m=2500.0,
        propellant_reserve_margin_kg=40.0,
        termination_reason="screening-campaign-horizon-reached",
    )


def test_design_and_validation_smoke_scenarios_are_screening_compatible() -> None:
    _validate_screening_compatibility(load_scenario(DESIGN), load_scenario(VALIDATION), _profile())


def test_synthetic_screening_backend_is_not_accepted_for_real_policy_search() -> None:
    with pytest.raises(ValueError, match="DESIGN force mode"):
        _validate_screening_compatibility(load_scenario(SYNTHETIC), load_scenario(VALIDATION), _profile())


def test_release_evaluator_preserves_raw_physical_values_and_only_flips_optimizer_direction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import constellation_control.preview.optimized_screening as module

    monkeypatch.setattr(module, "run_dsst_screening_campaign", lambda *args, **kwargs: _evidence())
    evaluator = build_real_dsst_screening_evaluator(DESIGN, VALIDATION, _profile())
    result = evaluator(OperationalPolicyParameters(trigger_fraction=0.5, target_fraction=0.25))

    assert result.objectives == pytest.approx((0.04, -2.0))
    assert result.hard_margins == pytest.approx((0.02, 2500.0, 40.0))
    assert result.metrics["screening_objective_raw_0"] == pytest.approx(0.04)
    assert result.metrics["screening_objective_raw_1"] == pytest.approx(2.0)
    assert result.metrics["screening_cumulative_propellant_used_kg"] == pytest.approx(0.03)


def test_projected_lifetime_is_not_replaced_by_hidden_finite_screening_constant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import constellation_control.preview.optimized_screening as module

    profile = _profile(maximize_second=False).model_copy(
        update={
            "objectives": (
                PreviewObjectiveDefinition(name="projected_lifetime", unit="Julian-year", direction="maximize"),
            )
        }
    )
    monkeypatch.setattr(module, "run_dsst_screening_campaign", lambda *args, **kwargs: _evidence())
    evaluator = build_real_dsst_screening_evaluator(DESIGN, VALIDATION, profile)
    with pytest.raises(ValueError, match="projected_lifetime is unavailable"):
        evaluator(OperationalPolicyParameters(trigger_fraction=0.5, target_fraction=0.25))
