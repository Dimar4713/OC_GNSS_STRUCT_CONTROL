from __future__ import annotations

from datetime import date
from hashlib import sha256
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, model_validator


class GlonassAuthorityRecord(BaseModel):
    """Explicit GLONASS almanac fields required by Orekit's analytical authority."""

    model_config = ConfigDict(frozen=True)

    slot: int = Field(ge=1, le=63)
    frequency_channel: int = Field(ge=-7, le=6)
    health: int = Field(ge=0)
    reference_date: date
    reference_time_s: float = Field(ge=0.0, lt=86400.0)
    lambda_rad: float
    delta_i_rad: float
    eccentricity: float = Field(ge=0.0, lt=1.0)
    argument_of_perigee_rad: float
    delta_t_s: float
    delta_t_dot: float
    glo_to_utc_s: float
    gps_to_glo_s: float
    glo_time_offset_s: float


class GlonassAuthoritySource(BaseModel):
    model_config = ConfigDict(frozen=True)

    source_filename: str
    source_sha256: str
    source_format: str = "glonass-labelled-authority-v1"
    authority: str = "GLONASS almanac explicit interchange for Orekit analytical propagation"
    records: tuple[GlonassAuthorityRecord, ...]

    @model_validator(mode="after")
    def validate_records(self) -> GlonassAuthoritySource:
        if not self.records:
            raise ValueError("GLONASS authority source contains no records")
        slots = [record.slot for record in self.records]
        if len(slots) != len(set(slots)):
            raise ValueError("duplicate GLONASS slots are not allowed")
        return self


_ALIASES = {
    "slot": "slot",
    "frequency channel": "frequency_channel",
    "frequency": "frequency_channel",
    "health": "health",
    "reference date": "reference_date",
    "reference time(s)": "reference_time_s",
    "reference time": "reference_time_s",
    "lambda(rad)": "lambda_rad",
    "lambda": "lambda_rad",
    "delta i(rad)": "delta_i_rad",
    "delta i": "delta_i_rad",
    "eccentricity": "eccentricity",
    "argument of perigee(rad)": "argument_of_perigee_rad",
    "argument of perigee": "argument_of_perigee_rad",
    "delta t(s)": "delta_t_s",
    "delta t": "delta_t_s",
    "delta t dot": "delta_t_dot",
    "delta t dot(s/orbit)": "delta_t_dot",
    "glo to utc(s)": "glo_to_utc_s",
    "glo to utc": "glo_to_utc_s",
    "gps to glo(s)": "gps_to_glo_s",
    "gps to glo": "gps_to_glo_s",
    "glo time offset(s)": "glo_time_offset_s",
    "glo time offset": "glo_time_offset_s",
}

_REQUIRED = frozenset(_ALIASES.values())


def _number(value: str, label: str) -> float:
    try:
        return float(value.replace("D", "E").replace("d", "e"))
    except ValueError as exc:
        raise ValueError(f"invalid numeric value for {label}: {value!r}") from exc


def _integer(value: str, label: str) -> int:
    try:
        return int(value.strip())
    except ValueError as exc:
        raise ValueError(f"invalid integer value for {label}: {value!r}") from exc


def _record(fields: dict[str, str]) -> GlonassAuthorityRecord:
    missing = sorted(_REQUIRED - fields.keys())
    if missing:
        raise ValueError("GLONASS authority record missing fields: " + ", ".join(missing))
    try:
        reference_date = date.fromisoformat(fields["reference_date"])
    except ValueError as exc:
        raise ValueError("reference date must be ISO YYYY-MM-DD") from exc
    return GlonassAuthorityRecord(
        slot=_integer(fields["slot"], "slot"),
        frequency_channel=_integer(fields["frequency_channel"], "frequency channel"),
        health=_integer(fields["health"], "health"),
        reference_date=reference_date,
        reference_time_s=_number(fields["reference_time_s"], "reference time"),
        lambda_rad=_number(fields["lambda_rad"], "lambda"),
        delta_i_rad=_number(fields["delta_i_rad"], "delta i"),
        eccentricity=_number(fields["eccentricity"], "eccentricity"),
        argument_of_perigee_rad=_number(fields["argument_of_perigee_rad"], "argument of perigee"),
        delta_t_s=_number(fields["delta_t_s"], "delta T"),
        delta_t_dot=_number(fields["delta_t_dot"], "delta T dot"),
        glo_to_utc_s=_number(fields["glo_to_utc_s"], "GLO to UTC"),
        gps_to_glo_s=_number(fields["gps_to_glo_s"], "GPS to GLO"),
        glo_time_offset_s=_number(fields["glo_time_offset_s"], "GLO time offset"),
    )


def parse_glonass_authority_source(filename: str, text: str) -> GlonassAuthoritySource:
    if not filename or Path(filename).name != filename:
        raise ValueError("source filename must not contain path components")
    if not text.strip():
        raise ValueError("GLONASS authority source is empty")

    records: list[GlonassAuthorityRecord] = []
    current: dict[str, str] = {}

    def flush() -> None:
        nonlocal current
        if current:
            records.append(_record(current))
            current = {}

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            flush()
            continue
        if line.startswith("#"):
            continue
        if ":" not in line:
            raise ValueError(f"unlabelled GLONASS authority line: {line!r}")
        raw_key, value = line.split(":", 1)
        canonical = _ALIASES.get(" ".join(raw_key.lower().split()))
        if canonical is None:
            raise ValueError(f"unknown GLONASS authority field: {raw_key.strip()!r}")
        if canonical == "slot" and current:
            flush()
        if canonical in current:
            raise ValueError(f"duplicate GLONASS authority field: {raw_key.strip()!r}")
        current[canonical] = value.strip()
    flush()

    return GlonassAuthoritySource(
        source_filename=filename,
        source_sha256=sha256(text.encode("utf-8")).hexdigest(),
        records=tuple(records),
    )
