from __future__ import annotations

from pathlib import Path

import pytest

from constellation_control.application.run import load_scenario
from constellation_control.control.campaign import ClosedLoopCampaignResult
from constellation_control.control.policies import CorrectionPolicy
from constellation_control.control.transition import CorrectionResourceRecord
from constellation_control.domain.models import OsculatingState, PropagationRequest, PropagationResult
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
from constellation_control.preview.optimized_campaign import run_authoritative_optimized_outcome


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
        study_id="preview-optimized-campaign-test",
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
            PreviewObjectiveDefinition(name="cumulative_delta_v", unit="m/s", direction="minimize"),
            PreviewObjectiveDefinition(name="correction_count", unit="events", direction="minimize"),
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


def _request() -> PropagationRequest:
    scenario = load_scenario(_scenario_path())
    return PropagationRequest(
        scenario_id=scenario.scenario_id,
        epoch=scenario.epoch,
        frame=scenario.frame,
        time_scale=scenario.time_scale,
        satellites=scenario.constellation.satellites,
        maneuvers=(),
        duration_s=3600.0,
        output_step_s=60.0,
        force_model=scenario.force_model,
        integrator=scenario.integrator,
        seed=42,
    )


def _campaign(*, elapsed_s: float = 3600.0) -> ClosedLoopCampaignResult:
    fingerprint = load_scenario(_scenario_path()).force_model.fingerprint()
    ledger = tuple(
        CorrectionResourceRecord(
            event_time_s=event_time,
            policy=CorrectionPolicy.OPTIMIZED.value,
            policy_reason="optimized-test-authorized",
            crossed_boundary_sign=1,
            observed_delta_u_rad=0.2,
            guidance_target_delta_u_rad=0.0,
            dv_rtn_m_s=(0.0, 0.01, 0.0),
            delta_v_m_s=0.01,
            propellant_used_kg=0.01,
            propellant_remaining_kg=50.0 - 0.01 * index,
            required_reserve_kg=5.0,
            cumulative_delta_v_m_s=0.01 * index,
            cumulative_propellant_used_kg=0.01 * index,
            replay_backend="orekit-numerical-test",
            replay_backend_metadata={},
            force_model_fingerprint=fingerprint,
        )
        for index, event_time in enumerate((600.0, 1800.0), start=1)
    )
    return ClosedLoopCampaignResult(
        policy=CorrectionPolicy.OPTIMIZED,
        corridor_half_width_rad=0.2,
        initial_epoch_iso="2026-01-01T00:00:00+00:00",
        final_epoch_iso="2026-01-01T01:00:00+00:00",
        elapsed_time_s=elapsed_s,
        correction_count=len(ledger),
        coast_propagation_calls=2,
        termination_reason="campaign-horizon-reached",
        final_policy_armed=True,
        policy_events=(),
        policy_trace=(),
        authority_attempts=(),
        transitions=(),
        resource_ledger=ledger,
        cumulative_delta_v_m_s=0.02,
        cumulative_propellant_used_kg=0.02,
        controlled_propellant_remaining_kg=49.98,
        controlled_required_reserve_kg=5.0,
        final_request=_request(),
    )


class ReplayStub:
    def propagate(self, request: PropagationRequest) -> PropagationResult:
        scenario = load_scenario(_scenario_path())
        ref, dep = scenario.constellation.satellites
        dep_mean = dep.mean_orbit.model_copy(update={"lambda_rad": 0.1})
        return PropagationResult(
            backend="orekit-numerical-test",
            backend_version="test",
            force_model_fingerprint=scenario.force_model.fingerprint(),
            times_s=(0.0, request.duration_s),
            mean_orbits={
                ref.satellite_id: (ref.mean_orbit, ref.mean_orbit),
                dep.satellite_id: (dep_mean, dep_mean),
            },
            cartesian_states={
                ref.satellite_id: (
                    OsculatingState(epoch_s=0.0, r_m=(0.0, 0.0, 0.0), v_m_s=(0.0, 0.0, 0.0)),
                    OsculatingState(epoch_s=request.duration_s, r_m=(0.0, 0.0, 0.0), v_m_s=(0.0, 0.0, 0.0)),
                ),
                dep.satellite_id: (
                    OsculatingState(epoch_s=0.0, r_m=(5000.0, 0.0, 0.0), v_m_s=(0.0, 0.0, 0.0)),
                    OsculatingState(epoch_s=request.duration_s, r_m=(5000.0, 0.0, 0.0), v_m_s=(0.0, 0.0, 0.0)),
                ),
            },
        )


def test_authoritative_outcome_comes_from_real_campaign_ledger_not_screening_scores(monkeypatch: pytest.MonkeyPatch) -> None:
    import constellation_control.preview.optimized_campaign as module

    monkeypatch.setattr(module, "run_optimized_closed_loop_campaign", lambda *args, **kwargs: _campaign())
    evidence = run_authoritative_optimized_outcome(
        _scenario_path(),
        _profile(),
        OperationalPolicyParameters(trigger_fraction=0.5, target_fraction=0.25),
        candidate_id="candidate-001",
        propagator=ReplayStub(),
    )

    assert evidence.campaign.policy == CorrectionPolicy.OPTIMIZED
    assert evidence.campaign.correction_count == 2
    assert evidence.outcome.cumulative_delta_v_m_s == pytest.approx(0.02)
    assert evidence.outcome.cumulative_propellant_used_kg == pytest.approx(0.02)
    assert tuple(item.value for item in evidence.outcome.objectives) == pytest.approx((0.02, 2.0))
    assert evidence.outcome.minimum_corridor_margin_rad == pytest.approx(0.1)
    assert evidence.outcome.minimum_fleet_distance_margin_m == pytest.approx(4000.0)
    assert evidence.outcome.evidence_id


def test_short_optimized_campaign_is_not_accepted_as_long_horizon_outcome(monkeypatch: pytest.MonkeyPatch) -> None:
    import constellation_control.preview.optimized_campaign as module

    monkeypatch.setattr(module, "run_optimized_closed_loop_campaign", lambda *args, **kwargs: _campaign(elapsed_s=600.0))
    with pytest.raises(ValueError, match="did not cover the declared campaign horizon"):
        run_authoritative_optimized_outcome(
            _scenario_path(),
            _profile(),
            OperationalPolicyParameters(trigger_fraction=0.5, target_fraction=0.25),
            candidate_id="candidate-001",
            propagator=ReplayStub(),
        )
