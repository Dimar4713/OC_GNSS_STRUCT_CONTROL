from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from constellation_control.application.run import load_scenario
from constellation_control.application.walker import WalkerDeltaRequest
from constellation_control.preview.walker_input import create_walker, preview_walker


def _root(tmp_path: Path) -> Path:
    root = tmp_path / "scenarios"
    root.mkdir()
    shutil.copy(Path("scenarios/mvp_45deg.yaml"), root / "source.yaml")
    return root


def _request() -> WalkerDeltaRequest:
    return WalkerDeltaRequest(
        source_scenario_name="source.yaml",
        target_scenario_name="walker-child.yaml",
        new_scenario_id="walker-child",
        template_satellite_id="DEMO-REF",
        total_satellites=6,
        planes=3,
        phasing=1,
        semi_major_axis_m=26_560_000.0,
        eccentricity=0.001,
        inclination_deg=64.8,
    )


def test_preview_walker_does_not_write(tmp_path: Path) -> None:
    root = _root(tmp_path)
    before = (root / "source.yaml").read_bytes()

    result = preview_walker(root, _request())

    assert result["valid"] is True
    assert result["satellite_count"] == 6
    assert result["plane_count"] == 3
    assert not (root / "walker-child.yaml").exists()
    assert (root / "source.yaml").read_bytes() == before


def test_create_walker_writes_derived_scenario(tmp_path: Path) -> None:
    root = _root(tmp_path)
    parent = load_scenario(root / "source.yaml")

    result = create_walker(root, _request())
    child = load_scenario(root / "walker-child.yaml")

    assert result["saved"] is True
    assert child.scenario_id == "walker-child"
    assert len(child.constellation.satellites) == 6
    assert child.digital_twin is not None
    assert child.digital_twin.lineage is not None
    assert child.digital_twin.lineage.parent_scenario_id == parent.scenario_id
    assert child.digital_twin.lineage.parent_config_hash == parent.config_hash()
    assert child.digital_twin.lineage.transformation == "walker_generation"


def test_preview_rejects_source_path_traversal(tmp_path: Path) -> None:
    root = _root(tmp_path)
    request = _request().model_copy(update={"source_scenario_name": "../source.yaml"})

    with pytest.raises(ValueError, match="without path components"):
        preview_walker(root, request)


def test_create_rejects_existing_target(tmp_path: Path) -> None:
    root = _root(tmp_path)
    request = _request()
    create_walker(root, request)

    with pytest.raises(ValueError, match="already exists"):
        create_walker(root, request)
