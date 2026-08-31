from __future__ import annotations

from enum import StrEnum
from hashlib import sha256
from math import pi
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, model_validator


class GnssAlmanacFormat(StrEnum):
    GPS_YUMA = "gps-yuma"
    GPS_SEM = "gps-sem"
    GLONASS_TEXT = "glonass-text"


class GpsYumaRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    prn: int = Field(ge=1, le=63)
    health: int = Field(ge=0, le=63)
    eccentricity: float = Field(ge=0.0, lt=1.0)
    toa_s: float = Field(ge=0.0)
    inclination_rad: float = Field(ge=0.0, le=pi)
    rate_of_raan_rad_s: float
    sqrt_a_m_sqrt: float = Field(gt=0.0)
    raan_rad: float
    argument_of_perigee_rad: float
    mean_anomaly_rad: float
    af0_s: float
    af1_s_s: float
    gps_week: int = Field(ge=0)


class GpsSemRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    prn: int = Field(ge=1, le=63)
    svn: int = Field(ge=0)
    ura: int = Field(ge=0)
    eccentricity: float = Field(ge=0.0, lt=1.0)
    inclination_offset_semicircles: float
    rate_of_raan_semicircles_s: float
    sqrt_a_m_sqrt: float = Field(gt=0.0)
    raan_semicircles: float
    argument_of_perigee_semicircles: float
    mean_anomaly_semicircles: float
    af0_s: float
    af1_s_s: float
    health: int = Field(ge=0, le=63)
    configuration: int = Field(ge=0)
    gps_week: int = Field(ge=0)
    toa_s: float = Field(ge=0.0)

    @property
    def inclination_rad(self) -> float:
        return (0.30 + self.inclination_offset_semicircles) * pi


class GlonassAlmanacRecord(BaseModel):
    """Normalized GLONASS almanac interchange record.

    This is deliberately not a decoder for raw GLONASS navigation strings. It
    accepts an explicit labelled text export so units and semantics remain
    visible to the operator. No field is reinterpreted as canonical MeanOrbit.
    """

    model_config = ConfigDict(frozen=True)

    slot: int = Field(ge=1, le=63)
    frequency_channel: int
    health: int = Field(ge=0)
    reference_day: int = Field(ge=1)
    reference_time_s: float = Field(ge=0.0)
    lambda_rad: float
    delta_i_rad: float
    eccentricity: float = Field(ge=0.0, lt=1.0)
    argument_of_perigee_rad: float
    draconian_period_s: float = Field(gt=0.0)
    draconian_period_rate_s_per_orbit: float


class GnssAlmanacPreview(BaseModel):
    model_config = ConfigDict(frozen=True)

    source_format: GnssAlmanacFormat
    source_filename: str
    source_sha256: str
    authority: str
    units_note: str
    records: tuple[GpsYumaRecord | GpsSemRecord | GlonassAlmanacRecord, ...]
    runnable_promotion_allowed: bool = False
    promotion_block_reason: str

    @model_validator(mode="after")
    def validate_records(self) -> GnssAlmanacPreview:
        if not self.records:
            raise ValueError("almanac contains no records")
        ids: list[int] = []
        for record in self.records:
            ids.append(record.prn if isinstance(record, (GpsYumaRecord, GpsSemRecord)) else record.slot)
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate satellite identifiers are not allowed in one almanac")
        if self.runnable_promotion_allowed:
            raise ValueError("raw almanac intake cannot be marked runnable")
        return self


def _safe_source(filename: str, text: str) -> tuple[str, str]:
    if not filename or Path(filename).name != filename:
        raise ValueError("source filename must not contain path components")
    if not text.strip():
        raise ValueError("almanac source is empty")
    return filename, sha256(text.encode("utf-8")).hexdigest()


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


def _canonical_yuma_key(raw: str) -> str:
    key = " ".join(raw.strip().lower().replace("_", " ").split())
    aliases = {
        "id": "id",
        "health": "health",
        "eccentricity": "eccentricity",
        "time of applicability(s)": "toa",
        "time of applicability": "toa",
        "orbital inclination(rad)": "inclination",
        "orbital inclination": "inclination",
        "rate of right ascen(r/s)": "rate_raan",
        "rate of right ascen": "rate_raan",
        "sqrt(a)  (m 1/2)": "sqrt_a",
        "sqrt(a) (m 1/2)": "sqrt_a",
        "sqrt(a)": "sqrt_a",
        "right ascen at week(rad)": "raan",
        "right ascen at week": "raan",
        "argument of perigee(rad)": "argp",
        "argument of perigee": "argp",
        "mean anom(rad)": "mean_anomaly",
        "mean anom": "mean_anomaly",
        "af0(s)": "af0",
        "af0": "af0",
        "af1(s/s)": "af1",
        "af1": "af1",
        "week": "week",
    }
    return aliases.get(key, key)


def parse_yuma(filename: str, text: str) -> GnssAlmanacPreview:
    source_filename, source_sha = _safe_source(filename, text)
    records: list[GpsYumaRecord] = []
    current: dict[str, str] = {}

    def flush() -> None:
        nonlocal current
        if not current:
            return
        required = {
            "id", "health", "eccentricity", "toa", "inclination", "rate_raan",
            "sqrt_a", "raan", "argp", "mean_anomaly", "af0", "af1", "week",
        }
        missing = sorted(required - current.keys())
        if missing:
            raise ValueError("YUMA record missing fields: " + ", ".join(missing))
        records.append(GpsYumaRecord(
            prn=_integer(current["id"], "ID"),
            health=_integer(current["health"], "Health"),
            eccentricity=_number(current["eccentricity"], "Eccentricity"),
            toa_s=_number(current["toa"], "Time of Applicability"),
            inclination_rad=_number(current["inclination"], "Orbital Inclination"),
            rate_of_raan_rad_s=_number(current["rate_raan"], "Rate of Right Ascension"),
            sqrt_a_m_sqrt=_number(current["sqrt_a"], "SQRT(A)"),
            raan_rad=_number(current["raan"], "Right Ascension at Week"),
            argument_of_perigee_rad=_number(current["argp"], "Argument of Perigee"),
            mean_anomaly_rad=_number(current["mean_anomaly"], "Mean Anomaly"),
            af0_s=_number(current["af0"], "Af0"),
            af1_s_s=_number(current["af1"], "Af1"),
            gps_week=_integer(current["week"], "Week"),
        ))
        current = {}

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or set(line) <= {"*", "-"}:
            if current and "week" in current:
                flush()
            continue
        if ":" not in line:
            continue
        raw_key, value = line.split(":", 1)
        key = _canonical_yuma_key(raw_key)
        if key == "id" and current:
            flush()
        current[key] = value.strip()
    flush()
    return GnssAlmanacPreview(
        source_format=GnssAlmanacFormat.GPS_YUMA,
        source_filename=source_filename,
        source_sha256=source_sha,
        authority="GPS YUMA reduced-precision broadcast almanac input",
        units_note="YUMA angular fields are radians; values remain almanac elements, not canonical project mean elements.",
        records=tuple(records),
        promotion_block_reason="YUMA intake is preview-only until a reviewed almanac-to-state authority is implemented.",
    )


def parse_sem(filename: str, text: str) -> GnssAlmanacPreview:
    source_filename, source_sha = _safe_source(filename, text)
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if len(lines) < 2:
        raise ValueError("SEM source must contain header and applicability line")
    header = lines[0].split()
    if not header:
        raise ValueError("SEM header is empty")
    count = _integer(header[0], "SEM record count")
    applicability = lines[1].split()
    if len(applicability) < 2:
        raise ValueError("SEM applicability line must contain GPS week and time of applicability")
    gps_week = _integer(applicability[0], "SEM GPS week")
    toa_s = _number(applicability[1], "SEM time of applicability")
    body = lines[2:]
    if len(body) != count * 8:
        raise ValueError(f"SEM expected {count * 8} nonblank record lines after header, got {len(body)}")
    records: list[GpsSemRecord] = []
    for offset in range(0, len(body), 8):
        chunk = body[offset:offset + 8]
        orbit1 = chunk[3].split()
        orbit2 = chunk[4].split()
        orbit3 = chunk[5].split()
        if len(orbit1) != 3 or len(orbit2) != 3 or len(orbit3) != 3:
            raise ValueError("SEM orbital rows R-4..R-6 must contain exactly three values each")
        records.append(GpsSemRecord(
            prn=_integer(chunk[0], "SEM PRN"),
            svn=_integer(chunk[1], "SEM SVN"),
            ura=_integer(chunk[2], "SEM URA"),
            eccentricity=_number(orbit1[0], "SEM eccentricity"),
            inclination_offset_semicircles=_number(orbit1[1], "SEM inclination offset"),
            rate_of_raan_semicircles_s=_number(orbit1[2], "SEM rate of RAAN"),
            sqrt_a_m_sqrt=_number(orbit2[0], "SEM sqrt(A)"),
            raan_semicircles=_number(orbit2[1], "SEM RAAN"),
            argument_of_perigee_semicircles=_number(orbit2[2], "SEM argument of perigee"),
            mean_anomaly_semicircles=_number(orbit3[0], "SEM mean anomaly"),
            af0_s=_number(orbit3[1], "SEM af0"),
            af1_s_s=_number(orbit3[2], "SEM af1"),
            health=_integer(chunk[6], "SEM health"),
            configuration=_integer(chunk[7], "SEM configuration"),
            gps_week=gps_week,
            toa_s=toa_s,
        ))
    return GnssAlmanacPreview(
        source_format=GnssAlmanacFormat.GPS_SEM,
        source_filename=source_filename,
        source_sha256=source_sha,
        authority="GPS SEM reduced-precision broadcast almanac input",
        units_note="SEM angular fields are semicircles; inclination is offset from 0.30 semicircle. Values are not canonical project mean elements.",
        records=tuple(records),
        promotion_block_reason="SEM intake is preview-only until a reviewed almanac-to-state authority is implemented.",
    )


def parse_glonass_text(filename: str, text: str) -> GnssAlmanacPreview:
    source_filename, source_sha = _safe_source(filename, text)
    records: list[GlonassAlmanacRecord] = []
    current: dict[str, str] = {}
    aliases = {
        "slot": "slot", "frequency channel": "frequency_channel", "frequency": "frequency_channel",
        "health": "health", "reference day": "reference_day", "reference time(s)": "reference_time_s",
        "reference time": "reference_time_s", "lambda(rad)": "lambda_rad", "lambda": "lambda_rad",
        "delta i(rad)": "delta_i_rad", "delta i": "delta_i_rad", "eccentricity": "eccentricity",
        "argument of perigee(rad)": "argp_rad", "argument of perigee": "argp_rad",
        "draconian period(s)": "period_s", "draconian period": "period_s",
        "draconian period rate(s/orbit)": "period_rate", "draconian period rate": "period_rate",
    }

    def flush() -> None:
        nonlocal current
        if not current:
            return
        required = {"slot", "frequency_channel", "health", "reference_day", "reference_time_s", "lambda_rad", "delta_i_rad", "eccentricity", "argp_rad", "period_s", "period_rate"}
        missing = sorted(required - current.keys())
        if missing:
            raise ValueError("GLONASS almanac record missing fields: " + ", ".join(missing))
        records.append(GlonassAlmanacRecord(
            slot=_integer(current["slot"], "slot"),
            frequency_channel=_integer(current["frequency_channel"], "frequency channel"),
            health=_integer(current["health"], "health"),
            reference_day=_integer(current["reference_day"], "reference day"),
            reference_time_s=_number(current["reference_time_s"], "reference time"),
            lambda_rad=_number(current["lambda_rad"], "lambda"),
            delta_i_rad=_number(current["delta_i_rad"], "delta i"),
            eccentricity=_number(current["eccentricity"], "eccentricity"),
            argument_of_perigee_rad=_number(current["argp_rad"], "argument of perigee"),
            draconian_period_s=_number(current["period_s"], "draconian period"),
            draconian_period_rate_s_per_orbit=_number(current["period_rate"], "draconian period rate"),
        ))
        current = {}

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            if current:
                flush()
            continue
        if ":" not in line:
            continue
        raw_key, value = line.split(":", 1)
        key = aliases.get(" ".join(raw_key.lower().split()))
        if key is None:
            continue
        if key == "slot" and current:
            flush()
        current[key] = value.strip()
    flush()
    return GnssAlmanacPreview(
        source_format=GnssAlmanacFormat.GLONASS_TEXT,
        source_filename=source_filename,
        source_sha256=source_sha,
        authority="GLONASS labelled almanac interchange input",
        units_note="This adapter accepts explicit labelled SI/radian text only; it does not decode raw GLONASS navigation strings.",
        records=tuple(records),
        promotion_block_reason="GLONASS almanac intake is preview-only until a reviewed GLONASS almanac propagation authority is implemented.",
    )


def preview_gnss_almanac(filename: str, text: str, source_format: GnssAlmanacFormat) -> GnssAlmanacPreview:
    if source_format == GnssAlmanacFormat.GPS_YUMA:
        return parse_yuma(filename, text)
    if source_format == GnssAlmanacFormat.GPS_SEM:
        return parse_sem(filename, text)
    if source_format == GnssAlmanacFormat.GLONASS_TEXT:
        return parse_glonass_text(filename, text)
    raise ValueError(f"unsupported GNSS almanac format: {source_format}")
