from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from constellation_control.adapters.spacecraft_workbook import load_spacecraft_workbook


def _write_workbook(path: Path, states: list[dict[str, object]], groups: list[dict[str, object]] | None = None) -> None:
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        pd.DataFrame(states).to_excel(writer, sheet_name="Spacecraft_State", index=False)
        if groups is not None:
            pd.DataFrame(groups).to_excel(writer, sheet_name="Spacecraft_Groups", index=False)


def test_loads_individual_state_and_groups(tmp_path: Path) -> None:
    path = tmp_path / "fleet.xlsx"
    _write_workbook(
        path,
        states=[
            {
                "satellite_id": "G01",
                "spacecraft_model_id": "TYPE-A",
                "dry_mass_kg": 850.0,
                "current_propellant_mass_kg": 80.0,
                "propellant_capacity_kg": 120.0,
                "current_mass_kg": 930.0,
                "propulsion_system_type": "electric",
                "propulsion_model_id": "EP-A",
                "thrust_n": 0.25,
                "isp_s": 1800.0,
                "propellant_type": "xenon",
                "correction_system_type": "orbit-correction-a",
                "correction_mode": "hybrid",
            },
            {
                "satellite_id": "G02",
                "spacecraft_model_id": "TYPE-B",
                "dry_mass_kg": 900.0,
                "current_propellant_mass_kg": 35.0,
                "current_mass_kg": 935.0,
            },
        ],
        groups=[
            {"group_id": "TYPE_1", "satellite_id": "G01"},
            {"group_id": "TYPE_2", "satellite_id": "G02"},
        ],
    )

    result = load_spacecraft_workbook(path)

    assert [state.satellite_id for state in result.spacecraft_states] == ["G01", "G02"]
    assert result.spacecraft_states[0].spacecraft_model_id == "TYPE-A"
    assert result.spacecraft_states[0].resolved_current_mass_kg == 930.0
    assert result.spacecraft_states[0].propulsion is not None
    assert result.spacecraft_states[0].propulsion.isp_s == 1800.0
    assert result.spacecraft_states[0].correction_system is not None
    assert result.spacecraft_states[0].correction_system.mode == "hybrid"
    assert result.groups[0].satellite_ids == ("G01",)
    assert result.groups[1].satellite_ids == ("G02",)


def test_rejects_inconsistent_current_mass(tmp_path: Path) -> None:
    path = tmp_path / "bad-mass.xlsx"
    _write_workbook(
        path,
        states=[
            {
                "satellite_id": "G01",
                "dry_mass_kg": 850.0,
                "current_propellant_mass_kg": 80.0,
                "current_mass_kg": 940.0,
            }
        ],
    )

    with pytest.raises(ValueError, match="current_mass_kg"):
        load_spacecraft_workbook(path)


def test_rejects_missing_required_state_column(tmp_path: Path) -> None:
    path = tmp_path / "missing.xlsx"
    _write_workbook(
        path,
        states=[{"satellite_id": "G01", "dry_mass_kg": 850.0}],
    )

    with pytest.raises(ValueError, match="current_propellant_mass_kg"):
        load_spacecraft_workbook(path)


def test_rejects_propulsion_details_without_type(tmp_path: Path) -> None:
    path = tmp_path / "bad-propulsion.xlsx"
    _write_workbook(
        path,
        states=[
            {
                "satellite_id": "G01",
                "dry_mass_kg": 850.0,
                "current_propellant_mass_kg": 80.0,
                "isp_s": 1800.0,
            }
        ],
    )

    with pytest.raises(ValueError, match="propulsion_system_type"):
        load_spacecraft_workbook(path)


def test_rejects_non_excel_suffix(tmp_path: Path) -> None:
    path = tmp_path / "fleet.csv"
    path.write_text("satellite_id,dry_mass_kg,current_propellant_mass_kg\nG01,850,80\n", encoding="utf-8")

    with pytest.raises(ValueError, match=".xls or .xlsx"):
        load_spacecraft_workbook(path)
