from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from constellation_control.application.run import load_scenario
from constellation_control.preview.optimal_operations_profile import (
    PREVIEW_OPTIMAL_OPERATIONS_PROFILE_SCHEMA,
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


def _profile(*, robustness_enabled: bool = False) -> PreviewOptimalOperationsStudyProfile:
    scenario = load_scenario(_scenario_path())
    execution = PreviewExecutionPolicyProfile(
        max_abs_impulse_rtn_m_s=(0.2, 0.2, 0.2),
        min_impulse_bit_m_s=0.001,
        trust_tolerances_roe=(1.0e-6, 1.0e-3, 1.0e-6, 1.0e-6, 1.0e-6, 1.0e-6),
        target_roe=(0.0, 0.0, 0.0, 0.0, 0.0, 0.0),
        w_tracking=10.0,
        w_max=0.5,
    )
    robustness = (
        PreviewRobustnessPolicy(
            enabled=True,
            recommendation_required=True,
            campaign_id="paired-robustness-test",
            uncertainty_model_id="paired-crn-test-v1",
            sampling_model_sha256="a" * 64,
        )
        if robustness_enabled
        else PreviewRobustnessPolicy(
            enabled=False,
            recommendation_required=False,
            campaign_id=None,
            uncertainty_model_id=None,
            sampling_model_sha256=None,
        )
    )
    return PreviewOptimalOperationsStudyProfile(
        schema_version=PREVIEW_OPTIMAL_OPERATIONS_PROFILE_SCHEMA,
        study_id="preview-optimal-study-test",
        scenario_name=_scenario_path().name,
        seed=42,
        campaign_horizon_s=3600.0,
        coast_horizon_s=600.0,
        coast_output_step_s=60.0,
        authority_times_s=(0.0, 60.0, 120.0),
        maneuver_windows=(True, True),
        execution_policy=execution,
        uncertainty_model_id="deterministic-test-v1",
        search=PreviewOperationalPolicySearchProfile(
            trigger_fraction_bounds=(0.25, 0.95),
            target_fraction_bounds=(0.0, 1.0),
            lhs_samples=8,
            local_seeds=2,
            local_method="SLSQP",
            nsga_population=8,
            nsga_generations=4,
            seed=73,
        ),
        objectives=(
            PreviewObjectiveDefinition(name="delta_v_per_year", unit="m/s/year", direction="minimize"),
            PreviewObjectiveDefinition(name="corrections_per_year", unit="1/year", direction="minimize"),
        ),
        hard_constraints=(
            PreviewHardConstraintDefinition(name="phase_corridor", unit="rad"),
            PreviewHardConstraintDefinition(name="minimum_fleet_distance", unit="m"),
            PreviewHardConstraintDefinition(name="propellant_reserve", unit="kg"),
        ),
        robustness=robustness,
        expected_force_model_fingerprint=scenario.force_model.fingerprint(),
        expected_frame=scenario.frame.value,
        expected_time_scale=scenario.time_scale.value,
        expected_integrator_identity=scenario_integrator_identity(scenario),
        expected_constraints_identity=scenario_constraints_identity(scenario),
        expected_execution_policy_identity=execution.identity(),
    )


def test_profile_has_no_hidden_operational_defaults() -> None:
    assert PreviewOptimalOperationsStudyProfile.model_fields["schema_version"].default == PREVIEW_OPTIMAL_OPERATIONS_PROFILE_SCHEMA
    for name, field in PreviewOptimalOperationsStudyProfile.model_fields.items():
        if name != "schema_version":
            assert field.is_required(), name
    for model in (
        PreviewExecutionPolicyProfile,
        PreviewOperationalPolicySearchProfile,
        PreviewObjectiveDefinition,
        PreviewHardConstraintDefinition,
        PreviewRobustnessPolicy,
    ):
        assert all(field.is_required() for field in model.model_fields.values())


def test_same_scenario_and_profile_produce_identical_preflight() -> None:
    profile = _profile()
    first = preflight_optimal_operations_study(_scenario_path(), profile)
    second = preflight_optimal_operations_study(_scenario_path(), profile)
    assert first == second
    assert first.preflight_sha256 == second.preflight_sha256
    assert first.identity.execution_policy_identity == profile.execution_policy.identity()
    assert first.robustness_enabled is False
    assert first.robustness_campaign_id is None
    assert first.robustness_sampling_model_sha256 is None


def test_preflight_rejects_identity_mismatch_before_execution() -> None:
    payload = _profile().model_dump(mode="json")
    payload["expected_constraints_identity"] = "0" * 64
    mismatched = PreviewOptimalOperationsStudyProfile.model_validate(payload)
    with pytest.raises(ValueError, match="constraints identity mismatch"):
        preflight_optimal_operations_study(_scenario_path(), mismatched)


def test_profile_rejects_malformed_authority_grid() -> None:
    payload = _profile().model_dump(mode="json")
    payload["authority_times_s"] = [0.0, 60.0, 60.0]
    with pytest.raises(ValidationError, match="strictly increasing"):
        PreviewOptimalOperationsStudyProfile.model_validate(payload)


def test_enabled_robustness_requires_explicit_campaign_and_model() -> None:
    with pytest.raises(ValidationError, match="campaign_id and uncertainty_model_id"):
        PreviewRobustnessPolicy(
            enabled=True,
            recommendation_required=True,
            campaign_id=None,
            uncertainty_model_id=None,
            sampling_model_sha256="a" * 64,
        )


def test_disabled_robustness_cannot_hide_threshold_or_campaign_evidence() -> None:
    with pytest.raises(ValidationError, match="null campaign/model evidence"):
        PreviewRobustnessPolicy(
            enabled=False,
            recommendation_required=False,
            campaign_id="hidden-campaign",
            uncertainty_model_id=None,
            sampling_model_sha256=None,
        )


def test_enabled_robustness_is_preserved_as_declared_evidence() -> None:
    preflight = preflight_optimal_operations_study(_scenario_path(), _profile(robustness_enabled=True))
    assert preflight.robustness_enabled is True
    assert preflight.robustness_recommendation_required is True
    assert preflight.robustness_campaign_id == "paired-robustness-test"
    assert preflight.robustness_uncertainty_model_id == "paired-crn-test-v1"
    assert preflight.robustness_sampling_model_sha256 == "a" * 64


def test_profile_json_round_trip_is_deterministic() -> None:
    profile = _profile(robustness_enabled=True)
    encoded = profile.model_dump_json()
    decoded = PreviewOptimalOperationsStudyProfile.model_validate_json(encoded)
    assert decoded == profile
    assert decoded.model_dump_json() == encoded
