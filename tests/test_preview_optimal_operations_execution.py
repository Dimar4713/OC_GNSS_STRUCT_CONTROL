from __future__ import annotations

from pathlib import Path

import pytest

from constellation_control.application.run import load_scenario
from constellation_control.control.campaign import ClosedLoopCampaignResult
from constellation_control.control.policies import CorrectionPolicy
from constellation_control.control.transition import CorrectionResourceRecord
from constellation_control.domain.models import OsculatingState, PropagationRequest, PropagationResult
from constellation_control.optimization.operational_policy_search import (
    OperationalPolicyEvaluation,
    OperationalPolicyParameters,
)
from constellation_control.optimization.operations import OperationalStrategyKind
from constellation_control.preview.optimal_operations_execution import (
    run_authoritative_p2_baselines,
    run_preview_optimal_operations_foundation,
    run_screening_only_candidate_search,
    write_preview_optimal_operations_foundation,
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
        study_id="preview-optimal-execution-test",
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


def _ledger(policy: CorrectionPolicy) -> tuple[CorrectionResourceRecord, ...]:
    if policy == CorrectionPolicy.NO_CONTROL:
        return ()
    scenario = load_scenario(_scenario_path())
    fingerprint = scenario.force_model.fingerprint()
    records = []
    for index, event_time in enumerate((600.0, 1800.0), start=1):
        records.append(
            CorrectionResourceRecord(
                event_time_s=event_time,
                policy=policy.value,
                policy_reason="test-authorized",
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
        )
    return tuple(records)


def _campaign(policy: CorrectionPolicy, *, elapsed_s: float = 3600.0) -> ClosedLoopCampaignResult:
    ledger = _ledger(policy)
    return ClosedLoopCampaignResult(
        policy=policy,
        corridor_half_width_rad=0.2,
        initial_epoch_iso="2026-01-01T00:00:00+00:00",
        final_epoch_iso="2026-01-01T01:00:00+00:00",
        elapsed_time_s=0.0 if policy == CorrectionPolicy.NO_CONTROL else elapsed_s,
        correction_count=len(ledger),
        coast_propagation_calls=0 if policy == CorrectionPolicy.NO_CONTROL else 1,
        termination_reason="no-control-policy" if policy == CorrectionPolicy.NO_CONTROL else "campaign-horizon-reached",
        final_policy_armed=True,
        policy_events=(),
        policy_trace=(),
        authority_attempts=(),
        transitions=(),
        resource_ledger=ledger,
        cumulative_delta_v_m_s=0.0 if not ledger else ledger[-1].cumulative_delta_v_m_s,
        cumulative_propellant_used_kg=0.0 if not ledger else ledger[-1].cumulative_propellant_used_kg,
        controlled_propellant_remaining_kg=50.0 if not ledger else ledger[-1].propellant_remaining_kg,
        controlled_required_reserve_kg=5.0,
        final_request=_request(),
    )


class NumericalReplayStub:
    def __init__(self) -> None:
        self.requests: list[PropagationRequest] = []

    def propagate(self, request: PropagationRequest) -> PropagationResult:
        self.requests.append(request)
        scenario = load_scenario(_scenario_path())
        ref, dep = scenario.constellation.satellites
        return PropagationResult(
            backend="orekit-numerical-test",
            backend_version="test",
            force_model_fingerprint=scenario.force_model.fingerprint(),
            times_s=(0.0, request.duration_s),
            mean_orbits={
                ref.satellite_id: (ref.mean_orbit, ref.mean_orbit),
                dep.satellite_id: (dep.mean_orbit, dep.mean_orbit),
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


def _screening_evaluator(parameters: OperationalPolicyParameters) -> OperationalPolicyEvaluation:
    objective = parameters.trigger_fraction + abs(parameters.target_fraction)
    return OperationalPolicyEvaluation(
        objectives=(objective, 1.0 - parameters.trigger_fraction),
        hard_margins=(parameters.trigger_fraction - 0.2, 1.0 - abs(parameters.target_fraction)),
        metrics={"trigger_fraction": parameters.trigger_fraction},
    )


def test_three_p2_baselines_share_identity_and_replay_exact_ledgers(monkeypatch: pytest.MonkeyPatch) -> None:
    import constellation_control.preview.optimal_operations_execution as module

    policies: list[CorrectionPolicy] = []

    def fake_campaign(*args: object, **kwargs: object) -> ClosedLoopCampaignResult:
        policy = args[3]
        assert isinstance(policy, CorrectionPolicy)
        policies.append(policy)
        return _campaign(policy)

    monkeypatch.setattr(module, "run_closed_loop_campaign", fake_campaign)
    replay = NumericalReplayStub()
    preflight, baselines = run_authoritative_p2_baselines(
        _scenario_path(),
        _profile(),
        propagator=replay,
    )

    assert policies == [
        CorrectionPolicy.NO_CONTROL,
        CorrectionPolicy.RETURN_TO_CENTER,
        CorrectionPolicy.BOUNDARY_TO_BOUNDARY,
    ]
    assert [item.strategy.kind for item in baselines] == [
        OperationalStrategyKind.NO_CONTROL_BASELINE,
        OperationalStrategyKind.RETURN_TO_CENTER_BASELINE,
        OperationalStrategyKind.BOUNDARY_TO_BOUNDARY_BASELINE,
    ]
    assert all(item.strategy.identity == preflight.identity for item in baselines)
    assert baselines[0].replay_maneuver_count == 0
    assert baselines[1].replay_maneuver_count == 2
    assert baselines[2].replay_maneuver_count == 2
    assert all(item.strategy.credibility_state.value == "authoritative-baseline" for item in baselines)
    assert baselines[0].strategy.hard_constraints_passed is False
    assert len(replay.requests) == 3
    assert all(request.duration_s == 3600.0 for request in replay.requests)


def test_controlled_baseline_must_cover_declared_horizon(monkeypatch: pytest.MonkeyPatch) -> None:
    import constellation_control.preview.optimal_operations_execution as module

    def fake_campaign(*args: object, **kwargs: object) -> ClosedLoopCampaignResult:
        policy = args[3]
        assert isinstance(policy, CorrectionPolicy)
        return _campaign(policy, elapsed_s=600.0 if policy != CorrectionPolicy.NO_CONTROL else 0.0)

    monkeypatch.setattr(module, "run_closed_loop_campaign", fake_campaign)
    with pytest.raises(ValueError, match="did not cover the declared campaign horizon"):
        run_authoritative_p2_baselines(_scenario_path(), _profile(), propagator=NumericalReplayStub())


def test_screening_search_uses_exact_preflight_config_and_never_promotes_candidates() -> None:
    profile = _profile()
    preflight = preflight_optimal_operations_study(_scenario_path(), profile)
    evidence = run_screening_only_candidate_search(profile, preflight, _screening_evaluator)

    assert evidence.search_config == profile.search.backend_config().model_dump(mode="json")
    assert evidence.screening_only is True
    assert evidence.candidates
    assert all(item.screening_only for item in evidence.candidates)
    assert all(len(item.candidate_id) == 16 for item in evidence.candidates)


def test_foundation_artifacts_are_deterministic_and_have_no_recommendation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import constellation_control.preview.optimal_operations_execution as module

    def fake_campaign(*args: object, **kwargs: object) -> ClosedLoopCampaignResult:
        policy = args[3]
        assert isinstance(policy, CorrectionPolicy)
        return _campaign(policy)

    monkeypatch.setattr(module, "run_closed_loop_campaign", fake_campaign)
    run = run_preview_optimal_operations_foundation(
        _scenario_path(),
        _profile(),
        _screening_evaluator,
        propagator=NumericalReplayStub(),
    )
    first = write_preview_optimal_operations_foundation(tmp_path, run)
    second = write_preview_optimal_operations_foundation(tmp_path, run)

    assert run.recommendation_strategy_id is None
    assert first == second
    assert Path(first.manifest_path).read_text(encoding="utf-8").find('"recommendation_strategy_id": null') >= 0
