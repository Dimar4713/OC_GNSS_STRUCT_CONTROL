from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any

import pandas as pd

from constellation_control.domain.digital_twin import (
    CorrectionSystem,
    DigitalTwinConfig,
    PropulsionSystem,
    SpacecraftGroup,
    SpacecraftOperationalState,
)

_STATE_SHEET = "Spacecraft_State"
_GROUP_SHEET = "Spacecraft_Groups"
_STATE_REQUIRED_COLUMNS = {
    "satellite_id",
    "dry_mass_kg",
    "current_propellant_mass_kg",
}
_GROUP_REQUIRED_COLUMNS = {"group_id", "satellite_id"}
_SUPPORTED_SUFFIXES = {".xls", ".xlsx"}


def _clean_columns(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    result.columns = [str(column).strip() for column in result.columns]
    return result


def _optional(row: pd.Series, name: str) -> Any | None:
    if name not in row.index:
        return None
    value = row[name]
    if pd.isna(value):
        return None
    if isinstance(value, str):
        value = value.strip()
        return value or None
    return value


def _required_text(row: pd.Series, name: str) -> str:
    value = _optional(row, name)
    if value is None:
        raise ValueError(f"required workbook value is empty: {name}")
    return str(value).strip()


def _require_columns(frame: pd.DataFrame, required: set[str], sheet: str) -> None:
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"{sheet} is missing required columns: {', '.join(missing)}")


def _propulsion(row: pd.Series) -> PropulsionSystem | None:
    system_type = _optional(row, "propulsion_system_type")
    fields = {
        "model_id": _optional(row, "propulsion_model_id"),
        "thrust_n": _optional(row, "thrust_n"),
        "isp_s": _optional(row, "isp_s"),
        "propellant_type": _optional(row, "propellant_type"),
    }
    if system_type is None:
        if any(value is not None for value in fields.values()):
            raise ValueError("propulsion_system_type is required when propulsion details are supplied")
        return None
    return PropulsionSystem(system_type=str(system_type), **fields)


def _correction_system(row: pd.Series) -> CorrectionSystem | None:
    system_type = _optional(row, "correction_system_type")
    mode = _optional(row, "correction_mode")
    if system_type is None:
        if mode is not None:
            raise ValueError("correction_system_type is required when correction_mode is supplied")
        return None
    return CorrectionSystem(system_type=str(system_type), mode=mode)


def _states(frame: pd.DataFrame) -> tuple[SpacecraftOperationalState, ...]:
    frame = _clean_columns(frame)
    _require_columns(frame, _STATE_REQUIRED_COLUMNS, _STATE_SHEET)
    states: list[SpacecraftOperationalState] = []
    for index, row in frame.iterrows():
        if row.isna().all():
            continue
        try:
            states.append(
                SpacecraftOperationalState(
                    satellite_id=_required_text(row, "satellite_id"),
                    spacecraft_model_id=_optional(row, "spacecraft_model_id"),
                    dry_mass_kg=_optional(row, "dry_mass_kg"),
                    current_propellant_mass_kg=_optional(row, "current_propellant_mass_kg"),
                    propellant_capacity_kg=_optional(row, "propellant_capacity_kg"),
                    current_mass_kg=_optional(row, "current_mass_kg"),
                    propulsion=_propulsion(row),
                    correction_system=_correction_system(row),
                )
            )
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{_STATE_SHEET} row {index + 2}: {exc}") from exc
    if not states:
        raise ValueError(f"{_STATE_SHEET} contains no spacecraft rows")
    return tuple(states)


def _groups(frame: pd.DataFrame | None) -> tuple[SpacecraftGroup, ...]:
    if frame is None:
        return ()
    frame = _clean_columns(frame)
    _require_columns(frame, _GROUP_REQUIRED_COLUMNS, _GROUP_SHEET)
    members: dict[str, list[str]] = defaultdict(list)
    for index, row in frame.iterrows():
        if row.isna().all():
            continue
        try:
            group_id = _required_text(row, "group_id")
            satellite_id = _required_text(row, "satellite_id")
        except ValueError as exc:
            raise ValueError(f"{_GROUP_SHEET} row {index + 2}: {exc}") from exc
        members[group_id].append(satellite_id)
    return tuple(SpacecraftGroup(group_id=group_id, satellite_ids=tuple(ids)) for group_id, ids in members.items())


def load_spacecraft_workbook(path: str | Path) -> DigitalTwinConfig:
    """Load explicit spacecraft operational state/groups from an engineer workbook.

    The workbook is a convenience/input adapter only. Pydantic domain models remain
    the canonical validated representation. No defaults for physical state are
    invented by this adapter.
    """

    source = Path(path)
    if source.suffix.lower() not in _SUPPORTED_SUFFIXES:
        raise ValueError("spacecraft workbook must use .xls or .xlsx")
    if not source.is_file():
        raise ValueError(f"spacecraft workbook not found: {source}")

    sheets = pd.read_excel(source, sheet_name=None)
    if _STATE_SHEET not in sheets:
        raise ValueError(f"spacecraft workbook requires sheet {_STATE_SHEET}")

    return DigitalTwinConfig(
        spacecraft_states=_states(sheets[_STATE_SHEET]),
        groups=_groups(sheets.get(_GROUP_SHEET)),
    )
