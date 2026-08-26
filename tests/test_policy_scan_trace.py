from __future__ import annotations

from pathlib import Path

import pytest

from constellation_control.application.run import load_scenario
from constellation_control.control.policies import CorrectionPolicy, CorrectionPolicyState
from constellation_control.control.policy_trace import scan_coast_for_policy_event_with_trace
from constellation_control.domain.models import OsculatingState, PropagationResult
from constellation_control.mean_elements.roe import RelativeOrbitalElements, mean_from_damico_roe


def _result(phases: tuple[float, ...]) -> tuple[PropagationResult, str, str, float]:
    scenario = load_scenario(Path(__file__).parents[1] / "scenarios" / "mvp_45deg.yaml")
    reference = next(sat for sat in scenario.constellation.satellites if sat.role == "reference")
    deputy = next(sat for sat in scenario.constellation.satellites if sat.role == "additional")
    ref_history = tuple(reference.mean_orbit for _ in phases)
    dep_history = tuple(
        mean_from_damico_roe(
            reference.mean_orbit,
            RelativeOrbitalElements(0.0, phase, 0.0, 0.0, 0.0, 0.0),
        )
        for phase in phases
    )
    times = tuple(float(index * 60) for index in range(len(phases)))
    zero_v = (0.0, 0.0, 0.0)
    result = PropagationResult(
        backend="synthetic-coast",
        backend_version="test",
        force_model_fingerprint=scenario.force_model.fingerprint(),
        backend_metadata={},
        times_s=times,
        mean_orbits={reference.satellite_id: ref_history, deputy.satellite_id: dep_history},
        cartesian_states={
            reference.satellite_id: tuple(
                OsculatingState(epoch_s=t, r_m=(0.0, 0.0, 0.0), v_m_s=zero_v) for t in times
            ),
            deputy.satellite_id: tuple(
                OsculatingState(epoch_s=t, r_m=(5000.0, 0.0, 0.0), v_m_s=zero_v) for t in times
            ),
        },
    )
    return result, reference.satellite_id, deputy.satellite_id, scenario.constraints.phase_corridor_rad


def test_boundary_to_boundary_trace_retains_disarm_rearm_and_opposite_boundary() -> None:
    result, reference_id, deputy_id, half_width = _result((0.0, 0.0, 0.0))
    result, reference_id, deputy_id, half_width = _result((half_width, 0.0, -half_width))
    traced = scan_coast_for_policy_event_with_trace(
        result,
        reference_id=reference_id,
        deputy_id=deputy_id,
        policy=CorrectionPolicy.BOUNDARY_TO_BOUNDARY,
        corridor_half_width_rad=half_width,
        initial_state=CorrectionPolicyState(armed=False),
        output_step_s=60.0,
    )

    assert traced.scan.event is not None
    assert traced.scan.event.sample_index == 2
    assert [record.sample_index for record in traced.trace] == [0, 1, 2]
    assert [record.decision_reason for record in traced.trace] == [
        "disarmed_waiting_for_reentry",
        "rearmed_inside_corridor",
        "phase_boundary_reached_coast_to_opposite_boundary",
    ]
    assert traced.trace[1].armed_before is False
    assert traced.trace[1].armed_after is True
    assert traced.trace[2].correction_requested
    assert traced.trace[2].crossed_boundary_sign == -1
    assert traced.trace[2].guidance_target_delta_u_rad == pytest.approx(half_width)
    assert all("no interpolation" in record.timing_semantics for record in traced.trace)


def test_return_to_center_trace_uses_same_strict_inside_rearm_rule() -> None:
    result0, reference_id, deputy_id, half_width = _result((0.0,))
    del result0
    result, reference_id, deputy_id, half_width = _result((half_width, 0.0, half_width))
    traced = scan_coast_for_policy_event_with_trace(
        result,
        reference_id=reference_id,
        deputy_id=deputy_id,
        policy=CorrectionPolicy.RETURN_TO_CENTER,
        corridor_half_width_rad=half_width,
        initial_state=CorrectionPolicyState(armed=False),
        output_step_s=60.0,
    )

    assert [record.decision_reason for record in traced.trace] == [
        "disarmed_waiting_for_reentry",
        "rearmed_inside_corridor",
        "phase_boundary_reached_return_to_center",
    ]
    assert traced.trace[-1].guidance_target_delta_u_rad == pytest.approx(0.0)
    assert traced.scan.final_policy_state.armed is False
