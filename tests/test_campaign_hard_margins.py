from __future__ import annotations

from pathlib import Path

import pytest

from constellation_control.analysis.campaign_hard_margins import reduce_trajectory_hard_margins
from constellation_control.application.run import load_scenario
from constellation_control.domain.models import OsculatingState, PropagationResult


def _scenario_path() -> Path:
    return Path(__file__).parents[1] / "scenarios" / "orekit_validation_smoke.yaml"


def _result() -> PropagationResult:
    scenario = load_scenario(_scenario_path())
    ref, dep = scenario.constellation.satellites
    dep0 = dep.mean_orbit.model_copy(update={"lambda_rad": 0.10})
    dep1 = dep.mean_orbit.model_copy(update={"lambda_rad": 0.19})
    return PropagationResult(
        backend="orekit-numerical-test",
        backend_version="test",
        force_model_fingerprint=scenario.force_model.fingerprint(),
        times_s=(0.0, 60.0),
        mean_orbits={
            ref.satellite_id: (ref.mean_orbit, ref.mean_orbit),
            dep.satellite_id: (dep0, dep1),
        },
        cartesian_states={
            ref.satellite_id: (
                OsculatingState(epoch_s=0.0, r_m=(0.0, 0.0, 0.0), v_m_s=(0.0, 0.0, 0.0)),
                OsculatingState(epoch_s=60.0, r_m=(0.0, 0.0, 0.0), v_m_s=(0.0, 0.0, 0.0)),
            ),
            dep.satellite_id: (
                OsculatingState(epoch_s=0.0, r_m=(2500.0, 0.0, 0.0), v_m_s=(0.0, 0.0, 0.0)),
                OsculatingState(epoch_s=60.0, r_m=(1800.0, 0.0, 0.0), v_m_s=(0.0, 0.0, 0.0)),
            ),
        },
    )


def test_reduces_direct_mean_phase_and_fleet_distance_margins() -> None:
    scenario = load_scenario(_scenario_path())
    evidence = reduce_trajectory_hard_margins(
        _result(),
        scenario.constraints,
        reference_id="SYNTH-REF",
        deputy_id="SYNTH-ADD-45",
    )
    assert evidence.phase_corridor_margin_rad == pytest.approx(0.01)
    assert evidence.minimum_fleet_distance_margin_m == pytest.approx(800.0)
    assert evidence.samples == 2
    assert evidence.pair_distance_samples == 2


def test_rejects_missing_pair_history() -> None:
    scenario = load_scenario(_scenario_path())
    base = _result()
    result = base.model_copy(update={"mean_orbits": {"SYNTH-REF": base.mean_orbits["SYNTH-REF"]}})
    with pytest.raises(ValueError, match="lacks reference/deputy"):
        reduce_trajectory_hard_margins(
            result,
            scenario.constraints,
            reference_id="SYNTH-REF",
            deputy_id="SYNTH-ADD-45",
        )
