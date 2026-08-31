from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, model_validator


class NoradFormat(StrEnum):
    TLE = "tle"
    OMM_JSON = "omm_json"


class NoradMeanElements(BaseModel):
    """Normalized NORAD/SGP4 mean elements.

    These values are intentionally not represented as canonical MeanOrbit or as
    osculating Keplerian elements. Promotion requires an authoritative TLE/SGP4
    propagation/conversion boundary.
    """

    model_config = ConfigDict(frozen=True)

    source_format: NoradFormat
    satellite_number: int = Field(gt=0)
    epoch_utc: datetime
    inclination_deg: float = Field(ge=0.0, le=180.0)
    raan_deg: float
    eccentricity: float = Field(ge=0.0, lt=1.0)
    argument_of_pericenter_deg: float
    mean_anomaly_deg: float
    mean_motion_rev_per_day: float = Field(gt=0.0)
    bstar: float | None = None
    classification: str | None = None
    international_designator: str | None = None
    element_set_number: int | None = Field(default=None, ge=0)
    revolution_number_at_epoch: int | None = Field(default=None, ge=0)
    object_name: str | None = None

    @model_validator(mode="after")
    def _epoch_timezone(self) -> "NoradMeanElements":
        if self.epoch_utc.tzinfo is None or self.epoch_utc.utcoffset() is None:
            raise ValueError("epoch_utc must be timezone-aware")
        return self


class NoradImportPreview(BaseModel):
    model_config = ConfigDict(frozen=True)

    source_filename: str
    source_sha256: str
    records: tuple[NoradMeanElements, ...]
    authority: str = "NORAD SGP4 mean-element input"
    runnable_promotion_allowed: bool = False
    promotion_block_reason: str = (
        "NORAD TLE/OMM elements are SGP4 mean elements, not osculating Keplerian elements and not the project's "
        "canonical mean-element definition. An authoritative Orekit TLE/SGP4 propagation/conversion step is required."
    )


def _tle_checksum_ok(line: str) -> bool:
    if len(line) != 69 or not line[-1].isdigit():
        return False
    total = 0
    for char in line[:-1]:
        if char.isdigit():
            total += int(char)
        elif char == "-":
            total += 1
    return total % 10 == int(line[-1])


def _tle_epoch(year_2: int, day_of_year: float) -> datetime:
    year = 1900 + year_2 if year_2 >= 57 else 2000 + year_2
    if not (1.0 <= day_of_year < 367.0):
        raise ValueError("TLE epoch day-of-year is outside the supported range")
    return datetime(year, 1, 1, tzinfo=timezone.utc) + timedelta(days=day_of_year - 1.0)


def _tle_exponential(field: str) -> float:
    token = field.strip()
    if not token:
        return 0.0
    sign = -1.0 if token.startswith("-") else 1.0
    if token[0] in "+-":
        token = token[1:]
    if len(token) < 3:
        raise ValueError(f"invalid TLE exponential field: {field!r}")
    mantissa_digits = token[:-2]
    exponent = int(token[-2:])
    return sign * float(f"0.{mantissa_digits}") * (10.0**exponent)


def _parse_tle_pair(line1: str, line2: str, object_name: str | None) -> NoradMeanElements:
    if len(line1) != 69 or len(line2) != 69:
        raise ValueError("TLE lines must each contain exactly 69 characters")
    if not line1.startswith("1 ") or not line2.startswith("2 "):
        raise ValueError("TLE pair must contain line 1 followed by line 2")
    if not _tle_checksum_ok(line1) or not _tle_checksum_ok(line2):
        raise ValueError("TLE checksum validation failed")
    sat1 = int(line1[2:7])
    sat2 = int(line2[2:7])
    if sat1 != sat2:
        raise ValueError("TLE line satellite numbers do not match")
    epoch = _tle_epoch(int(line1[18:20]), float(line1[20:32]))
    eccentricity = float(f"0.{line2[26:33].strip()}")
    return NoradMeanElements(
        source_format=NoradFormat.TLE,
        satellite_number=sat1,
        epoch_utc=epoch,
        inclination_deg=float(line2[8:16]),
        raan_deg=float(line2[17:25]),
        eccentricity=eccentricity,
        argument_of_pericenter_deg=float(line2[34:42]),
        mean_anomaly_deg=float(line2[43:51]),
        mean_motion_rev_per_day=float(line2[52:63]),
        bstar=_tle_exponential(line1[53:61]),
        classification=line1[7].strip() or None,
        international_designator=line1[9:17].strip() or None,
        element_set_number=int(line1[64:68]),
        revolution_number_at_epoch=int(line2[63:68]),
        object_name=object_name,
    )


def parse_tle(text: str) -> tuple[NoradMeanElements, ...]:
    lines = [line.rstrip("\r") for line in text.splitlines() if line.strip()]
    if not lines:
        raise ValueError("TLE input is empty")
    records: list[NoradMeanElements] = []
    i = 0
    while i < len(lines):
        object_name: str | None = None
        if not lines[i].startswith("1 "):
            object_name = lines[i].strip()
            i += 1
        if i + 1 >= len(lines):
            raise ValueError("incomplete TLE record")
        records.append(_parse_tle_pair(lines[i], lines[i + 1], object_name))
        i += 2
    numbers = [record.satellite_number for record in records]
    if len(numbers) != len(set(numbers)):
        raise ValueError("duplicate NORAD satellite number in TLE input")
    return tuple(records)


def _required_omm_number(payload: dict[str, object], key: str) -> float:
    if key not in payload:
        raise ValueError(f"OMM field {key} is required")
    try:
        return float(payload[key])
    except (TypeError, ValueError) as exc:
        raise ValueError(f"OMM field {key} must be numeric") from exc


def _parse_omm_object(payload: dict[str, object]) -> NoradMeanElements:
    if "NORAD_CAT_ID" not in payload or "EPOCH" not in payload:
        raise ValueError("OMM fields NORAD_CAT_ID and EPOCH are required")
    try:
        epoch = datetime.fromisoformat(str(payload["EPOCH"]).replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("OMM EPOCH must be ISO-8601") from exc
    if epoch.tzinfo is None:
        raise ValueError("OMM EPOCH must include a time-zone offset or Z")
    try:
        sat_number = int(str(payload["NORAD_CAT_ID"]))
    except ValueError as exc:
        raise ValueError("OMM NORAD_CAT_ID must be an integer") from exc
    bstar_raw = payload.get("BSTAR")
    return NoradMeanElements(
        source_format=NoradFormat.OMM_JSON,
        satellite_number=sat_number,
        epoch_utc=epoch.astimezone(timezone.utc),
        inclination_deg=_required_omm_number(payload, "INCLINATION"),
        raan_deg=_required_omm_number(payload, "RA_OF_ASC_NODE"),
        eccentricity=_required_omm_number(payload, "ECCENTRICITY"),
        argument_of_pericenter_deg=_required_omm_number(payload, "ARG_OF_PERICENTER"),
        mean_anomaly_deg=_required_omm_number(payload, "MEAN_ANOMALY"),
        mean_motion_rev_per_day=_required_omm_number(payload, "MEAN_MOTION"),
        bstar=float(bstar_raw) if bstar_raw is not None else None,
        classification=str(payload["CLASSIFICATION_TYPE"]).strip() if payload.get("CLASSIFICATION_TYPE") else None,
        international_designator=str(payload["OBJECT_ID"]).strip() if payload.get("OBJECT_ID") else None,
        element_set_number=int(str(payload["ELEMENT_SET_NO"])) if payload.get("ELEMENT_SET_NO") is not None else None,
        revolution_number_at_epoch=(
            int(str(payload["REV_AT_EPOCH"])) if payload.get("REV_AT_EPOCH") is not None else None
        ),
        object_name=str(payload["OBJECT_NAME"]).strip() if payload.get("OBJECT_NAME") else None,
    )


def parse_omm_json(text: str) -> tuple[NoradMeanElements, ...]:
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"OMM JSON cannot be parsed: {exc}") from exc
    objects = raw if isinstance(raw, list) else [raw]
    if not objects or not all(isinstance(item, dict) for item in objects):
        raise ValueError("OMM JSON must be an object or a non-empty array of objects")
    records = tuple(_parse_omm_object(item) for item in objects)
    numbers = [record.satellite_number for record in records]
    if len(numbers) != len(set(numbers)):
        raise ValueError("duplicate NORAD satellite number in OMM input")
    return records


def preview_norad_import(filename: str, content: str) -> NoradImportPreview:
    safe_name = Path(filename).name
    if not filename or safe_name != filename:
        raise ValueError("filename must not contain path components")
    if not content.strip():
        raise ValueError("NORAD input is empty")
    suffix = Path(filename).suffix.lower()
    if suffix in {".tle", ".txt"}:
        records = parse_tle(content)
    elif suffix == ".json":
        records = parse_omm_json(content)
    else:
        raise ValueError("supported NORAD input extensions are .tle, .txt and OMM .json")
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
    return NoradImportPreview(source_filename=safe_name, source_sha256=digest, records=records)
