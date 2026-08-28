from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest

from constellation_control.application.run import load_scenario
from constellation_control.control.closed_loop import (
    continuation_request_from_snapshot,
    event_request_from_coast,
    scan_coast_for_policy_event,
)
from constellation_control.control.policies import CorrectionPolicy, CorrectionPolicyState
from constellation_control.control.transition import (
    AuthoritativeTransitionSnapshot,
    TransitionSpacecraftState,
)
from constellation_control.domain.models import Maneuver, OsculatingState, PropagationRequest, PropagationResult


def _source_request() -> PropagationRequest:
    scenario = load_scenario(Path(__file__).parents[1] / "scenarios" / "mvp_45deg.yaml")
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
        seed=scenario.seed,
    )


def _transition_snapshot(source: PropagationRequest) -> AuthoritativeTransitionSnapshot:
    states = []
    for index, satellite in enumerate(source.satellites):
        states.append(
            TransitionSpacecraftState(
                satellite_id=satellite.satellite_id,
                mean_orbit=satellite.mean_orbit.model_copy(
                    update={"lambda_rad": satellite.mean_orbit.lambda_rad + (index + 1) * 1.0e-4}
                ),
                cartesian_state=OsculatingState(
                    epoch_s=60.0,
                    r_m=(1000.0 * index, 1.0, 0.0),
                    v_m_s=(0.0, 0.0, 0.0),
                ),
            )
        )
    deputy = next(sat for sat in source.satellites if sat.role == "additional")
    reference = next(sat for sat in source.satellites if sat.role == "reference")
    return AuthoritativeTransitionSnapshot(
        continuation_sample_index=1,
        continuation_time_s=60.0,
        source_replay_times_s=(0.0, 60.0, 120.0),
        controlled_satellite_id=deputy.satellite_id,
        reference_id=reference.satellite_id,
        spacecraft_states=tuple(states),
        controlled_propellant_remaining_kg=49.5,
        controlled_total_mass_kg=deputy.spacecraft.dry_mass_kg + 49.5,
        event_delta_v_m_s=0.02,
        event_propellant_used_kg=0.5,
        force_model_fingerprint=source.force_model.fingerprint(),
        backend="orekit-numerical-validation",
        backend_version="13.1.7",
        backend_metadata={"orekit_version": "13.1.7"},
        frame=source.frame,
        time_scale=source.time_scale,
        integrator=source.integrator,
    )


def _coast_result(source: PropagationRequest, delta_u_values: tuple[float, ...]) -> PropagationResult:
    reference = next(sat for sat in source.satellites if sat.role == "reference")
    deputy = next(sat for sat in source.satellites if sat.role == "additional")
    times = tuple(60.0 * index for index in range(len(delta_u_values)))
    ref_means = tuple(reference.mean_orbit for _ in times)
    dep_means = tuple(
        reference.mean_orbit.model_copy(update={"lambda_rad": reference.mean_orbit.lambda_rad + delta_u})
        for delta_u in delta_u_values
    )
    ref_cart = tuple(
        OsculatingState(epoch_s=time_s, r_m=(0.0, time_s, 0.0), v_m_s=(0.0, 0.0, 0.0))
        for time_s in times
    )
    dep_cart = tuple(
        OsculatingState(epoch_s=time_s, r_m=(5000.0, time_s, 0.0), v_m_s=(0.0, 0.0, 0.0))
        for time_s in times
    )
    return PropagationResult(
        backend="orekit-numerical-validation",
        backend_version="13.1.7",
        force_model_fingerprint=source.force_model.fingerprint(),
        backend_metadata={"orekit_version": "13.1.7"},
        times_s=times,
        mean_orbits={reference.satellite_id: ref_means, deputy.satellite_id: dep_means},
        cartesian_states={reference.satellite_id: ref_cart, deputy.satellite_id: dep_cart},
    )


def test_continuation_request_uses_snapshot_epoch_states_and_remaining_fuel() -> None:
    source = _source_request()
    source_dump = source.model_dump(mode="json")
    snapshot = _transition_snapshot(source)
    executed = Maneuver(
        satellite_id=snapshot.controlled_satellite_id,
        time_s=0.0,
        dv_rtn_m_s=(0.0, 0.02, 0.0),
    )
    source_with_maneuver = source.model_copy(update={"maneuvers": (executed,)})

    next_request = continuation_request_from_snapshot(
        source_with_maneuver,
        snapshot,
        duration_s=3600.0,
        output_step_s=60.0,
    )

    assert next_request.epoch == source.epoch + timedelta(seconds=60.0)
    assert next_request.duration_s == 3600.0
    assert next_request.output_step_s == 60.0
    assert next_request.maneuvers == ()
    assert next_request.force_model == source.force_model
    assert next_request.force_model.fingerprint() == source.force_model.fingerprint()
    assert next_request.integrator == source.integrator
    assert next_request.frame == source.frame
    assert next_request.time_scale == source.time_scale
    assert next_request.seed == source.seed

    snapshot_by_id = {state.satellite_id: state for state in snapshot.spacecraft_states}
    for satellite in next_request.satellites:
        assert satellite.mean_orbit == snapshot_by_id[satellite.satellite_id].mean_orbit
    controlled = next(
        sat for sat in next_request.satellites if sat.satellite_id == snapshot.controlled_satellite_id
    )
    assert controlled.spacecraft.propellant_mass_kg == 49.5
    assert controlled.spacecraft.initial_mass_kg == pytest.approx(controlled.spacecraft.dry_mass_kg + 49.5)
    assert source.model_dump(mode="json") == source_dump


def test_boundary_to_boundary_coast_honors_disarm_rearm_then_opposite_boundary() -> None:
    source = _source_request()
    half_width = 0.2
    result = _coast_result(source, (half_width, 0.10, 0.0, -half_width))
    reference = next(sat for sat in source.satellites if sat.role == "reference")
    deputy = next(sat for sat in source.satellites if sat.role == "additional")

    scan = scan_coast_for_policy_event(
        result,
        reference_id=reference.satellite_id,
        deputy_id=deputy.satellite_id,
        policy=CorrectionPolicy.BOUNDARY_TO_BOUNDARY,
        corridor_half_width_rad=half_width,
        initial_state=CorrectionPolicyState(armed=False),
        output_step_s=60.0,
    )

    assert scan.event is not None
    event = scan.event
    assert event.sample_index == 3
    assert event.time_s == 180.0
    assert event.grid_resolution_s == 60.0
    assert "no interpolation" in event.timing_semantics
    assert event.state_before.armed is True
    assert event.state_after.armed is False
    assert event.decision.correction_requested is True
    assert event.decision.crossed_boundary_sign == -1
    assert event.decision.guidance_target_delta_u_rad == pytest.approx(half_width)
    assert scan.samples_evaluated == 4


def test_return_to_center_coast_uses_same_rearm_semantics() -> None:
    source = _source_request()
    half_width = 0.2
    result = _coast_result(source, (half_width, 0.10, -0.10, -half_width))
    reference = next(sat for sat in source.satellites if sat.role == "reference")
    deputy = next(sat for sat in source.satellites if sat.role == "additional")
    scan = scan_coast_for_policy_event(
        result,
        reference_id=reference.satellite_id,
        deputy_id=deputy.satellite_id,
        policy=CorrectionPolicy.RETURN_TO_CENTER,
        corridor_half_width_rad=half_width,
        initial_state=CorrectionPolicyState(armed=False),
        output_step_s=60.0,
    )
    assert scan.event is not None
    assert scan.event.sample_index == 3
    assert scan.event.decision.guidance_target_delta_u_rad == 0.0


def test_no_control_coast_never_yields_policy_event() -> None:
    source = _source_request()
    result = _coast_result(source, (0.0, 0.5, -0.5, 1.0))
    reference = next(sat for sat in source.satellites if sat.role == "reference")
    deputy = next(sat for sat in source.satellites if sat.role == "additional")
    scan = scan_coast_for_policy_event(
        result,
        reference_id=reference.satellite_id,
        deputy_id=deputy.satellite_id,
        policy=CorrectionPolicy.NO_CONTROL,
        corridor_half_width_rad=0.2,
        initial_state=CorrectionPolicyState(),
        output_step_s=60.0,
    )
    assert scan.event is None
    assert scan.samples_evaluated == 4
    assert scan.final_policy_state.armed is True


def test_event_request_comes_directly_from_coast_sample_without_propagation() -> None:
    source = _source_request()
    source_dump = source.model_dump(mode="json")
    half_width = 0.2
    result = _coast_result(source, (half_width, 0.10, 0.0, -half_width))
    reference = next(sat for sat in source.satellites if sat.role == "reference")
    deputy = next(sat for sat in source.satellites if sat.role == "additional")
    scan = scan_coast_for_policy_event(
        result,
        reference_id=reference.satellite_id,
        deputy_id=deputy.satellite_id,
        policy=CorrectionPolicy.BOUNDARY_TO_BOUNDARY,
        corridor_half_width_rad=half_width,
        initial_state=CorrectionPolicyState(armed=False),
        output_step_s=60.0,
    )
    assert scan.event is not None

    event_request = event_request_from_coast(
        source,
        scan.event,
        duration_s=600.0,
        output_step_s=60.0,
    )

    assert event_request.epoch == source.epoch + timedelta(seconds=180.0)
    assert event_request.maneuvers == ()
    assert event_request.duration_s == 600.0
    assert event_request.output_step_s == 60.0
    event_states = {state.satellite_id: state for state in scan.event.spacecraft_states}
    for satellite in event_request.satellites:
        assert satellite.mean_orbit == event_states[satellite.satellite_id].mean_orbit
    assert event_request.force_model == source.force_model
    assert event_request.integrator == source.integrator
    assert source.model_dump(mode="json") == source_dump


def test_coast_grid_allows_short_final_interval_but_rejects_hidden_coarsening() -> None:
    source = _source_request()
    reference = next(sat for sat in source.satellites if sat.role == "reference")
    deputy = next(sat for sat in source.satellites if sat.role == "additional")
    base = _coast_result(source, (0.0, 0.05, 0.10))
    shortened = base.model_copy(update={"times_s": (0.0, 60.0, 100.0)})
    scan = scan_coast_for_policy_event(
        shortened,
        reference_id=reference.satellite_id,
        deputy_id=deputy.satellite_id,
        policy=CorrectionPolicy.NO_CONTROL,
        corridor_half_width_rad=0.2,
        initial_state=CorrectionPolicyState(),
        output_step_s=60.0,
    )
    assert scan.event is None

    coarsened = base.model_copy(update={"times_s": (0.0, 61.0, 100.0)})
    with pytest.raises(ValueError, match="exceed declared output_step_s"):
        scan_coast_for_policy_event(
            coarsened,
            reference_id=reference.satellite_id,
            deputy_id=deputy.satellite_id,
            policy=CorrectionPolicy.NO_CONTROL,
            corridor_half_width_rad=0.2,
            initial_state=CorrectionPolicyState(),
            output_step_s=60.0,
        )
