from __future__ import annotations

import base64
from io import BytesIO
from pathlib import Path

import pandas as pd
import pytest

from constellation_control.preview.workbook_upload import PreviewWorkbookRequest, preview_workbook


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
