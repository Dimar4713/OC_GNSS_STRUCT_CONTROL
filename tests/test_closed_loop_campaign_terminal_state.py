from __future__ import annotations

from datetime import timedelta
from pathlib import Path

from constellation_control.application.run import load_scenario
from constellation_control.control.campaign import _request_from_result_sample
from constellation_control.domain.models import OsculatingState, PropagationRequest, PropagationResult
from constellation_control.mean_elements.roe import RelativeOrbitalElements, mean_from_damico_roe


def test_terminal_request_uses_last_authoritative_coast_sample_without_mutating_source() -> None:
    scenario = load_scenario(Path(__file__).parents[1] / "scenarios" / "mvp_45deg.yaml")
    reference = next(sat for sat in scenario.constellation.satellites if sat.role == "reference")
    deputy = next(sat for sat in scenario.constellation.satellites if sat.role == "additional")
    source = PropagationRequest(
        scenario_id=scenario.scenario_id,
        epoch=scenario.epoch,
        frame=scenario.frame,
        time_scale=scenario.time_scale,
        satellites=(reference, deputy),
        maneuvers=(),
        duration_s=120.0,
        output_step_s=60.0,
        force_model=scenario.force_model,
        integrator=scenario.integrator,
        seed=scenario.seed,
    )
    terminal_deputy = mean_from_damico_roe(
        reference.mean_orbit,
        RelativeOrbitalElements(0.0, 0.0123, 0.0, 0.0, 0.0, 0.0),
    )
    zero_v = (0.0, 0.0, 0.0)
    result = PropagationResult(
        backend="synthetic-coast",
        backend_version="test",
        force_model_fingerprint=source.force_model.fingerprint(),
        backend_metadata={},
        times_s=(0.0, 60.0, 120.0),
        mean_orbits={
            reference.satellite_id: (reference.mean_orbit, reference.mean_orbit, reference.mean_orbit),
            deputy.satellite_id: (deputy.mean_orbit, deputy.mean_orbit, terminal_deputy),
        },
        cartesian_states={
            reference.satellite_id: tuple(
                OsculatingState(epoch_s=t, r_m=(0.0, 0.0, 0.0), v_m_s=zero_v)
                for t in (0.0, 60.0, 120.0)
            ),
            deputy.satellite_id: tuple(
                OsculatingState(epoch_s=t, r_m=(5000.0, 0.0, 0.0), v_m_s=zero_v)
                for t in (0.0, 60.0, 120.0)
            ),
        },
    )

    terminal = _request_from_result_sample(source, result, -1)

    assert terminal.epoch == source.epoch + timedelta(seconds=120.0)
    assert next(sat for sat in terminal.satellites if sat.role == "additional").mean_orbit == terminal_deputy
    assert next(sat for sat in source.satellites if sat.role == "additional").mean_orbit == deputy.mean_orbit
    assert terminal.maneuvers == ()
    assert terminal.force_model == source.force_model
    assert terminal.integrator == source.integrator
    assert terminal.frame == source.frame
    assert terminal.time_scale == source.time_scale
