from __future__ import annotations

import json
from pathlib import Path

import pytest

from constellation_control.analysis.closed_loop_metrics import analyze_closed_loop_operations
from constellation_control.application.run import load_scenario
from constellation_control.control.campaign import (
    CampaignAuthorityRecord,
    CampaignPolicyEventRecord,
    CampaignPolicyTraceRecord,
    ClosedLoopCampaignResult,
)
from constellation_control.control.policies import CorrectionPolicy
from constellation_control.control.transition import (
    AuthoritativeTransitionSnapshot,
    CorrectionResourceRecord,
    TransitionSpacecraftState,
)
from constellation_control.domain.models import PropagationRequest
from constellation_control.mean_elements.roe import RelativeOrbitalElements, mean_from_damico_roe
from constellation_control.reporting.closed_loop_artifacts import (
    correction_event_table,
    write_closed_loop_artifacts,
)


def _request() -> PropagationRequest:
    scenario = load_scenario(Path(__file__).parents[1] / "scenarios" / "mvp_45deg.yaml")
    return PropagationRequest(
        scenario_id=scenario.scenario_id,
        epoch=scenario.epoch,
        frame=scenario.frame,
        time_scale=scenario.time_scale,
        satellites=scenario.constellation.satellites,
        maneuvers=(),
        duration_s=60.0,
        output_step_s=60.0,
        force_model=scenario.force_model,
        integrator=scenario.integrator,
        seed=scenario.seed,
    )


def _event(time_s: float, sign: int) -> CampaignPolicyEventRecord:
    target = -float(sign) * 0.1
    return CampaignPolicyEventRecord(
        elapsed_time_s=time_s,
        source="coast-grid" if time_s else "initial-state",
        local_sample_index=0 if time_s == 0.0 else 2,
        local_time_s=0.0 if time_s == 0.0 else 120.0,
        observed_delta_u_rad=float(sign) * 0.1,
        decision_reason="phase_boundary_reached_coast_to_opposite_boundary",
        crossed_boundary_sign=sign,
        guidance_target_delta_u_rad=target,
        armed_before=True,
        armed_after=False,
    )


def _authority(time_s: float, remaining: float) -> CampaignAuthorityRecord:
    return CampaignAuthorityRecord(
        elapsed_time_s=time_s,
        authorized=True,
        reason="authorized-by-numerical-replay",
        sizing_attempted=True,
        adapted_target_roe=(0.0, 0.0, 0.0, 0.0, 0.0, 0.0),
        dv_rtn_m_s=(0.0, 0.01, 0.0),
        propellant_used_kg=1.0,
        propellant_remaining_kg=remaining,
        required_reserve_kg=10.0,
        replay_backend="orekit-numerical-validation",
        trust_error_ratio=0.1,
        replay_min_pair_distance_m=5000.0,
    )


def _transition(request: PropagationRequest, post_delta_u: float, remaining: float) -> AuthoritativeTransitionSnapshot:
    reference = next(sat for sat in request.satellites if sat.role == "reference")
    deputy = next(sat for sat in request.satellites if sat.role == "additional")
    post_deputy = deputy.model_copy(
        update={
            "mean_orbit": mean_from_damico_roe(
                reference.mean_orbit,
                RelativeOrbitalElements(0.0, post_delta_u, 0.0, 0.0, 0.0, 0.0),
            )
        }
    )
    return AuthoritativeTransitionSnapshot(
        continuation_sample_index=1,
        continuation_time_s=60.0,
        source_replay_times_s=(0.0, 60.0),
        controlled_satellite_id=post_deputy.satellite_id,
        reference_id=reference.satellite_id,
        spacecraft_states=(
            TransitionSpacecraftState(satellite_id=reference.satellite_id, mean_orbit=reference.mean_orbit),
            TransitionSpacecraftState(satellite_id=post_deputy.satellite_id, mean_orbit=post_deputy.mean_orbit),
        ),
        controlled_propellant_remaining_kg=remaining,
        controlled_total_mass_kg=post_deputy.spacecraft.dry_mass_kg + remaining,
        event_delta_v_m_s=0.01,
        event_propellant_used_kg=1.0,
        force_model_fingerprint=request.force_model.fingerprint(),
        backend="orekit-numerical-validation",
        backend_version="13.1.7",
        backend_metadata={"gravity_model": "EIGEN-6S"},
        frame=request.frame,
        time_scale=request.time_scale,
        integrator=request.integrator,
    )


def _resource(request: PropagationRequest, time_s: float, sign: int, index: int, remaining: float) -> CorrectionResourceRecord:
    return CorrectionResourceRecord(
        event_time_s=time_s,
        policy=CorrectionPolicy.BOUNDARY_TO_BOUNDARY.value,
        policy_reason="phase_boundary_reached_coast_to_opposite_boundary",
        crossed_boundary_sign=sign,
        observed_delta_u_rad=float(sign) * 0.1,
        guidance_target_delta_u_rad=-float(sign) * 0.1,
        dv_rtn_m_s=(0.0, 0.01, 0.0),
        delta_v_m_s=0.01,
        propellant_used_kg=1.0,
        propellant_remaining_kg=remaining,
        required_reserve_kg=10.0,
        cumulative_delta_v_m_s=0.01 * index,
        cumulative_propellant_used_kg=float(index),
        replay_backend="orekit-numerical-validation",
        replay_backend_metadata={"gravity_model": "EIGEN-6S"},
        force_model_fingerprint=request.force_model.fingerprint(),
    )


def _trace(time_s: float) -> CampaignPolicyTraceRecord:
    return CampaignPolicyTraceRecord(
        elapsed_time_s=time_s,
        local_sample_index=1,
        local_time_s=60.0,
        delta_u_rad=0.0,
        decision_reason="rearmed_inside_corridor",
        correction_requested=False,
        crossed_boundary_sign=None,
        guidance_target_delta_u_rad=None,
        armed_before=False,
        armed_after=True,
        grid_resolution_s=60.0,
        timing_semantics="authoritative propagation output grid; no interpolation",
    )


def _campaign() -> ClosedLoopCampaignResult:
    request = _request()
    return ClosedLoopCampaignResult(
        policy=CorrectionPolicy.BOUNDARY_TO_BOUNDARY,
        corridor_half_width_rad=0.1,
        initial_epoch_iso=request.epoch.isoformat(),
        final_epoch_iso=request.epoch.isoformat(),
        elapsed_time_s=360.0,
        correction_count=2,
        coast_propagation_calls=2,
        termination_reason="max-corrections-reached",
        final_policy_armed=False,
        policy_events=(_event(0.0, 1), _event(180.0, -1)),
        policy_trace=(_trace(120.0), _trace(300.0)),
        authority_attempts=(_authority(0.0, 49.0), _authority(180.0, 48.0)),
        transitions=(_transition(request, 0.02, 49.0), _transition(request, -0.03, 48.0)),
        resource_ledger=(
            _resource(request, 0.0, 1, 1, 49.0),
            _resource(request, 180.0, -1, 2, 48.0),
        ),
        cumulative_delta_v_m_s=0.02,
        cumulative_propellant_used_kg=2.0,
        controlled_propellant_remaining_kg=48.0,
        controlled_required_reserve_kg=10.0,
        final_request=request,
    )


def test_correction_table_preserves_one_to_one_authority_transition_ledger_lineage() -> None:
    table = correction_event_table(_campaign())

    assert list(table["correction_index"]) == [1, 2]
    assert list(table["event_time_s"]) == pytest.approx([0.0, 180.0])
    assert list(table["pre_correction_delta_u_rad"]) == pytest.approx([0.1, -0.1])
    assert list(table["post_transition_delta_u_rad"]) == pytest.approx([0.02, -0.03])
    assert list(table["delta_v_m_s"]) == pytest.approx([0.01, 0.01])
    assert "not an instantaneous maneuver jump" in table.iloc[0]["post_transition_semantics"]
    states = json.loads(table.iloc[0]["post_transition_states_json"])
    assert len(states) == 2


def test_closed_loop_artifacts_round_trip_and_report_precedes_secondary_diagnostics(tmp_path: Path) -> None:
    campaign = _campaign()
    metrics = analyze_closed_loop_operations(campaign)
    (tmp_path / "report.md").write_text(
        "# Run\n\n## Resource / maneuver diagnostics\n\nresources\n\n## Secondary diagnostics\n\nsecondary\n",
        encoding="utf-8",
    )

    table = write_closed_loop_artifacts(tmp_path, campaign, metrics)

    assert len(table) == 2
    restored_campaign = ClosedLoopCampaignResult.model_validate_json(
        (tmp_path / "closed_loop_campaign.json").read_text(encoding="utf-8")
    )
    assert restored_campaign == campaign
    restored_metrics = json.loads((tmp_path / "closed_loop_metrics.json").read_text(encoding="utf-8"))
    assert restored_metrics["annualized"]["evidence_correction_count"] == 2
    restored_rows = json.loads((tmp_path / "closed_loop_corrections.json").read_text(encoding="utf-8"))
    assert len(restored_rows) == 2
    report = (tmp_path / "report.md").read_text(encoding="utf-8")
    assert report.index("## Closed-loop control campaign") < report.index("## Secondary diagnostics")
    assert "Annualized and lifetime values are projections" in report
    assert "not an instantaneous maneuver jump" in report
    assert (tmp_path / "report.html").exists()
