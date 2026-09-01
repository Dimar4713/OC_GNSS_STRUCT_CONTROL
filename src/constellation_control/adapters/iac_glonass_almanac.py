from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from math import pi

from constellation_control.adapters.iac_gnss_tables import IacDataset, IacTable


DMV_TZ = timezone(timedelta(hours=3), name="UTC+3")


@dataclass(frozen=True)
class IacGlonassAlmanacRecord:
    slot: int
    base_date_dmv: date
    ascending_node_time_s: float
    orbital_period_s: float
    eccentricity: float
    inclination_deg: float
    ascending_node_longitude_deg: float
    argument_of_perigee_deg: float
    onboard_time_correction_s: float
    frequency_channel: int
    draconian_period_rate: float

    @property
    def inclination_rad(self) -> float:
        return self.inclination_deg * pi / 180.0

    @property
    def ascending_node_longitude_rad(self) -> float:
        return self.ascending_node_longitude_deg * pi / 180.0

    @property
    def argument_of_perigee_rad(self) -> float:
        return self.argument_of_perigee_deg * pi / 180.0

    @property
    def ascending_node_epoch_dmv(self) -> datetime:
        midnight = datetime(
            self.base_date_dmv.year,
            self.base_date_dmv.month,
            self.base_date_dmv.day,
            tzinfo=DMV_TZ,
        )
        return midnight + timedelta(seconds=self.ascending_node_time_s)

    @property
    def ascending_node_epoch_utc(self) -> datetime:
        return self.ascending_node_epoch_dmv.astimezone(timezone.utc)


@dataclass(frozen=True)
class IacGlonassAlmanac:
    source_url: str | None
    source_sha256: str
    records: tuple[IacGlonassAlmanacRecord, ...]
    authority_note: str = (
        "IAC GLONASS almanac normalized with source-declared field semantics; "
        "no hidden promotion to project MeanOrbit authority"
    )


def _number(value: str, label: str) -> float:
    try:
        return float(value.replace(",", ".").replace("D", "E").replace("d", "e"))
    except ValueError as exc:
        raise ValueError(f"invalid IAC GLONASS {label}: {value!r}") from exc


def _integer(value: str, label: str) -> int:
    try:
        return int(value.strip())
    except ValueError as exc:
        raise ValueError(f"invalid IAC GLONASS {label}: {value!r}") from exc


def _base_date(value: str) -> date:
    try:
        return datetime.strptime(value.strip(), "%d.%m.%y").date()
    except ValueError as exc:
        raise ValueError(f"invalid IAC GLONASS base date: {value!r}") from exc


def normalize_iac_glonass_almanac(table: IacTable) -> IacGlonassAlmanac:
    if table.dataset != IacDataset.GLONASS_ALMANAC:
        raise ValueError("IAC table is not a GLONASS almanac dataset")

    required = ("NS", "Дата", "TΩ", "Tоб", "e", "i", "LΩ", "ω", "δt2", "nl", "ΔT")
    positions = {name: index for index, name in enumerate(table.headers)}
    missing = [name for name in required if name not in positions]
    if missing:
        raise ValueError("IAC GLONASS table missing columns: " + ", ".join(missing))

    records: list[IacGlonassAlmanacRecord] = []
    for row_number, row in enumerate(table.rows, start=1):
        try:
            record = IacGlonassAlmanacRecord(
                slot=_integer(row[positions["NS"]], "satellite number"),
                base_date_dmv=_base_date(row[positions["Дата"]]),
                ascending_node_time_s=_number(row[positions["TΩ"]], "TΩ"),
                orbital_period_s=_number(row[positions["Tоб"]], "Tоб"),
                eccentricity=_number(row[positions["e"]], "eccentricity"),
                inclination_deg=_number(row[positions["i"]], "inclination"),
                ascending_node_longitude_deg=_number(row[positions["LΩ"]], "LΩ"),
                argument_of_perigee_deg=_number(row[positions["ω"]], "argument of perigee"),
                onboard_time_correction_s=_number(row[positions["δt2"]], "δt2"),
                frequency_channel=_integer(row[positions["nl"]], "frequency channel"),
                draconian_period_rate=_number(row[positions["ΔT"]], "ΔT"),
            )
        except (IndexError, ValueError) as exc:
            raise ValueError(f"invalid IAC GLONASS row {row_number}: {exc}") from exc

        if not 1 <= record.slot <= 63:
            raise ValueError(f"invalid IAC GLONASS row {row_number}: slot out of range")
        if not 0.0 <= record.eccentricity < 1.0:
            raise ValueError(f"invalid IAC GLONASS row {row_number}: eccentricity out of range")
        if record.orbital_period_s <= 0.0:
            raise ValueError(f"invalid IAC GLONASS row {row_number}: orbital period must be positive")
        if not 0.0 <= record.ascending_node_time_s < 86400.0:
            raise ValueError(f"invalid IAC GLONASS row {row_number}: TΩ outside one DMV day")
        records.append(record)

    slots = [record.slot for record in records]
    if len(slots) != len(set(slots)):
        raise ValueError("duplicate IAC GLONASS satellite numbers")

    return IacGlonassAlmanac(
        source_url=table.source_url,
        source_sha256=table.source_sha256,
        records=tuple(records),
    )
