from __future__ import annotations

from pathlib import Path

import pytest

from constellation_control.application.run import load_scenario
from constellation_control.application.walker import WalkerDeltaRequest, build_walker_constellation, create_walker_derived_scenario


def _request(**overrides: object) -> WalkerDeltaRequest:
    payload: dict[str, object] = {
        "source_scenario_name": "mvp_45deg.yaml",
        "target_scenario_name": "walker-test.yaml",
        "new_scenario_id": "walker-test",
        "template_satellite_id": "DEMO-REF",
        "total_satellites": 6,
        "planes": 3,
        "phasing": 1,
        "semi_major_axis_m": 26_560_000.0,
        "eccentricity": 0.001,
        "inclination_deg": 64.8,
        "raan0_deg": 10.0,
        "argument_of_perigee_deg": 0.0,
        "mean_anomaly0_deg": 20.0,
    }
    payload.update(overrides)
    return WalkerDeltaRequest.model_validate(payload)


def test_build_walker_delta_geometry() -> None:
    source = load_scenario(Path("scenarios/mvp_45deg.yaml"))
    constellation = build_walker_constellation(source, _request())

    assert len(constellation.satellites) == 6
    assert len(constellation.planes) == 3
    assert constellation.planes[0].satellite_ids == ("W-P01-S01", "W-P01-S02")
    assert constellation.satellites[0].role == "reference"
    assert constellation.satellites[1].reference_id == "W-P01-S01"
    assert constellation.satellites[0].spacecraft == source.constellation.satellites[0].spacecraft
    assert constellation.satellites[0].mean_orbit.definition.theory == "walker-delta-engineering-mean-input"


def test_walker_requires_equal_satellites_per_plane() -> None:
    with pytest.raises(ValueError, match="divisible"):
        _request(total_satellites=5, planes=3)


def test_walker_rejects_unknown_template() -> None:
    source = load_scenario(Path("scenarios/mvp_45deg.yaml"))
    with pytest.raises(ValueError, match="template_satellite_id"):
        build_walker_constellation(source, _request(template_satellite_id="UNKNOWN"))


def test_create_walker_child_preserves_parent(tmp_path: Path) -> None:
    parent_source = Path("scenarios/mvp_45deg.yaml")
    parent = tmp_path / parent_source.name
    parent.write_bytes(parent_source.read_bytes())
    before = parent.read_bytes()

    result = create_walker_derived_scenario(tmp_path, _request())

    assert parent.read_bytes() == before
    assert result["saved"] is True
    assert result["satellite_count"] == 6
    child = load_scenario(tmp_path / "walker-test.yaml")
    assert child.scenario_id == "walker-test"
    assert child.digital_twin is not None
    assert child.digital_twin.lineage is not None
    assert child.digital_twin.lineage.parent_scenario_id == "synthetic-mvp-45deg"
    assert child.digital_twin.lineage.transformation == "walker_generation"
    assert child.maneuvers == ()
    assert child.config_hash() != load_scenario(parent).config_hash()


def test_create_walker_child_never_overwrites(tmp_path: Path) -> None:
    parent_source = Path("scenarios/mvp_45deg.yaml")
    (tmp_path / parent_source.name).write_bytes(parent_source.read_bytes())
    (tmp_path / "walker-test.yaml").write_text("sentinel", encoding="utf-8")

    with pytest.raises(ValueError, match="overwrite"):
        create_walker_derived_scenario(tmp_path, _request())
