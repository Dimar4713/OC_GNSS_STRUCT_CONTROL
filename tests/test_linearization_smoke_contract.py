from pathlib import Path

from constellation_control.application.run import load_scenario
from constellation_control.domain.models import ForceMode


def test_orekit_linearization_smoke_uses_one_authoritative_interval() -> None:
    scenario = load_scenario(Path(__file__).parents[1] / "scenarios" / "orekit_linearization_smoke.yaml")

    assert scenario.force_model.mode == ForceMode.VALIDATION
    assert scenario.maneuvers == ()
    assert scenario.output_step_s == scenario.duration_s
    assert scenario.duration_s == 300.0

    references = [sat for sat in scenario.constellation.satellites if sat.role == "reference"]
    deputies = [sat for sat in scenario.constellation.satellites if sat.role == "additional"]
    assert len(references) == 1
    assert len(deputies) == 1
    assert deputies[0].reference_id == references[0].satellite_id
