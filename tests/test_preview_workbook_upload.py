from __future__ import annotations

import base64
import shutil
from io import BytesIO
from pathlib import Path

import pandas as pd
import pytest

from constellation_control.application.run import load_scenario
from constellation_control.preview.workbook_upload import (
    ApplyWorkbookRequest,
    PreviewWorkbookRequest,
    apply_workbook_as_derived,
    preview_workbook,
)


def _workbook_payload(satellite_id: str) -> str:
    buffer = BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        pd.DataFrame(
            [
                {
                    "satellite_id": satellite_id,
                    "spacecraft_model_id": "TYPE-A",
                    "dry_mass_kg": 500.0,
                    "current_propellant_mass_kg": 40.0,
                    "current_mass_kg": 540.0,
                    "propulsion_system_type": "chemical",
                    "isp_s": 220.0,
                    "correction_system_type": "orbit-correction",
                    "correction_mode": "ground",
                }
            ]
        ).to_excel(writer, sheet_name="Spacecraft_State", index=False)
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def _scenario_root(tmp_path: Path) -> Path:
    root = tmp_path / "scenarios"
    root.mkdir()
    shutil.copy2(Path("scenarios/mvp_45deg.yaml"), root / "mvp_45deg.yaml")
    return root


def test_preview_validates_workbook_against_selected_scenario() -> None:
    result = preview_workbook(
        Path("scenarios"),
        PreviewWorkbookRequest(
            scenario_name="mvp_45deg.yaml",
            filename="spacecraft-state.xlsx",
            content_base64=_workbook_payload("DEMO-REF"),
        ),
    )

    assert result["valid"] is True
    assert result["spacecraft_count"] == 1
    assert result["source_config_hash"] != result["candidate_config_hash"]
    states = result["spacecraft_states"]
    assert isinstance(states, list)
    assert states[0]["satellite_id"] == "DEMO-REF"
    assert states[0]["current_propellant_mass_kg"] == 40.0
    assert states[0]["current_mass_kg"] == 540.0


def test_preview_rejects_unknown_spacecraft_id() -> None:
    with pytest.raises(ValueError, match="unknown digital-twin spacecraft state satellite_id"):
        preview_workbook(
            Path("scenarios"),
            PreviewWorkbookRequest(
                scenario_name="mvp_45deg.yaml",
                filename="spacecraft-state.xlsx",
                content_base64=_workbook_payload("UNKNOWN-KA"),
            ),
        )


def test_preview_rejects_path_in_workbook_filename() -> None:
    with pytest.raises(ValueError, match="path components"):
        preview_workbook(
            Path("scenarios"),
            PreviewWorkbookRequest(
                scenario_name="mvp_45deg.yaml",
                filename="../spacecraft-state.xlsx",
                content_base64=_workbook_payload("DEMO-REF"),
            ),
        )


def test_apply_creates_derived_scenario_with_lineage_and_preserves_parent(tmp_path: Path) -> None:
    root = _scenario_root(tmp_path)
    parent_path = root / "mvp_45deg.yaml"
    parent_before = parent_path.read_bytes()
    parent = load_scenario(parent_path)

    result = apply_workbook_as_derived(
        root,
        ApplyWorkbookRequest(
            scenario_name="mvp_45deg.yaml",
            filename="spacecraft-state.xlsx",
            content_base64=_workbook_payload("DEMO-REF"),
            derived_scenario_name="mvp_45deg-workbook.yaml",
            derived_scenario_id="synthetic-mvp-45deg-workbook",
        ),
    )

    assert parent_path.read_bytes() == parent_before
    child_path = root / "mvp_45deg-workbook.yaml"
    assert child_path.is_file()
    child = load_scenario(child_path)
    assert child.scenario_id == "synthetic-mvp-45deg-workbook"
    assert child.digital_twin is not None
    assert child.digital_twin.spacecraft_states[0].satellite_id == "DEMO-REF"
    assert child.digital_twin.spacecraft_states[0].current_propellant_mass_kg == 40.0
    assert child.digital_twin.lineage is not None
    assert child.digital_twin.lineage.parent_scenario_id == parent.scenario_id
    assert child.digital_twin.lineage.parent_config_hash == parent.config_hash()
    assert child.digital_twin.lineage.transformation == "import"
    assert result["parent_config_hash"] == parent.config_hash()
    assert result["child_config_hash"] == child.config_hash()
    assert result["child_config_hash"] != result["parent_config_hash"]


def test_apply_refuses_existing_target_file(tmp_path: Path) -> None:
    root = _scenario_root(tmp_path)
    target = root / "mvp_45deg-workbook.yaml"
    target.write_text("sentinel\n", encoding="utf-8")

    with pytest.raises(ValueError, match="never overwritten"):
        apply_workbook_as_derived(
            root,
            ApplyWorkbookRequest(
                scenario_name="mvp_45deg.yaml",
                filename="spacecraft-state.xlsx",
                content_base64=_workbook_payload("DEMO-REF"),
                derived_scenario_name=target.name,
                derived_scenario_id="synthetic-mvp-45deg-workbook",
            ),
        )
    assert target.read_text(encoding="utf-8") == "sentinel\n"


def test_apply_requires_new_scenario_id(tmp_path: Path) -> None:
    root = _scenario_root(tmp_path)
    parent = load_scenario(root / "mvp_45deg.yaml")

    with pytest.raises(ValueError, match="must differ"):
        apply_workbook_as_derived(
            root,
            ApplyWorkbookRequest(
                scenario_name="mvp_45deg.yaml",
                filename="spacecraft-state.xlsx",
                content_base64=_workbook_payload("DEMO-REF"),
                derived_scenario_name="mvp_45deg-workbook.yaml",
                derived_scenario_id=parent.scenario_id,
            ),
        )
