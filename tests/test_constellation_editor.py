from pathlib import Path
import shutil

import pytest
import yaml

from constellation_control.preview.constellation_editor import ConstellationEditRequest, apply_constellation_edit


SOURCE = Path("scenarios/mvp_45deg.yaml")


def _root(tmp_path: Path) -> Path:
    shutil.copy(SOURCE, tmp_path / SOURCE.name)
    return tmp_path


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_rename_updates_reference_ids_and_creates_derived_scenario(tmp_path: Path) -> None:
    root = _root(tmp_path)
    result = apply_constellation_edit(
        root,
        ConstellationEditRequest(
            source_scenario_name=SOURCE.name,
            operation="rename",
            satellite_id="DEMO-REF",
            new_satellite_id="DEMO-REF-RENAMED",
            target_scenario_name="renamed.yaml",
            new_scenario_id="renamed-scenario",
        ),
    )
    assert result["saved"] is True
    child = _load(root / "renamed.yaml")
    sats = {item["satellite_id"]: item for item in child["constellation"]["satellites"]}
    assert "DEMO-REF" not in sats
    assert "DEMO-REF-RENAMED" in sats
    assert sats["DEMO-ADD-45"]["reference_id"] == "DEMO-REF-RENAMED"
    assert child["digital_twin"]["lineage"]["transformation"] == "constellation_editor"
    # Parent remains immutable.
    parent = _load(root / SOURCE.name)
    assert parent["constellation"]["satellites"][0]["satellite_id"] == "DEMO-REF"


def test_remove_reference_spacecraft_fails_closed(tmp_path: Path) -> None:
    root = _root(tmp_path)
    with pytest.raises(ValueError, match="reference_id"):
        apply_constellation_edit(
            root,
            ConstellationEditRequest(
                source_scenario_name=SOURCE.name,
                operation="remove",
                satellite_id="DEMO-REF",
                target_scenario_name="invalid.yaml",
                new_scenario_id="invalid-remove",
            ),
        )
    assert not (root / "invalid.yaml").exists()


def test_move_rebuilds_plane_membership(tmp_path: Path) -> None:
    root = _root(tmp_path)
    apply_constellation_edit(
        root,
        ConstellationEditRequest(
            source_scenario_name=SOURCE.name,
            operation="move",
            satellite_id="DEMO-ADD-45",
            plane_id="P2",
            target_scenario_name="moved.yaml",
            new_scenario_id="moved-scenario",
        ),
    )
    child = _load(root / "moved.yaml")
    sats = {item["satellite_id"]: item for item in child["constellation"]["satellites"]}
    assert sats["DEMO-ADD-45"]["plane_id"] == "P2"
    planes = {item["plane_id"]: item["satellite_ids"] for item in child["constellation"]["planes"]}
    assert planes["P1"] == ["DEMO-REF"]
    assert planes["P2"] == ["DEMO-ADD-45"]


def test_clone_requires_unique_new_identity(tmp_path: Path) -> None:
    root = _root(tmp_path)
    apply_constellation_edit(
        root,
        ConstellationEditRequest(
            source_scenario_name=SOURCE.name,
            operation="clone",
            satellite_id="DEMO-REF",
            new_satellite_id="DEMO-NEW",
            plane_id="P1",
            role="additional",
            reference_id="DEMO-REF",
            target_scenario_name="clone.yaml",
            new_scenario_id="clone-scenario",
        ),
    )
    child = _load(root / "clone.yaml")
    ids = [item["satellite_id"] for item in child["constellation"]["satellites"]]
    assert ids == ["DEMO-REF", "DEMO-ADD-45", "DEMO-NEW"]
