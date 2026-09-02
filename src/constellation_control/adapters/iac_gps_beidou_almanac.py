from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from math import pi

from constellation_control.adapters.iac_gnss_tables import IacDataset, IacTable


@dataclass(frozen=True)
class IacGpsAlmanacRecord:
    prn: int
    base_date_utc: date
    time_from_base_s: float
    eccentricity: float
    inclination_deg: float
    raan_rate_deg_s: float
    semi_major_axis_km: float
    ascending_node_longitude_deg: float
    argument_of_perigee_deg: float
    mean_anomaly_deg: float
    af0_s: float
    af1_s_s: float

    @property
    def epoch_utc(self) -> datetime:
        midnight = datetime(self.base_date_utc.year, self.base_date_utc.month, self.base_date_utc.day, tzinfo=UTC)
        return midnight + timedelta(seconds=self.time_from_base_s)

    @property
    def semi_major_axis_m(self) -> float:
        return self.semi_major_axis_km * 1000.0

    @property
    def inclination_rad(self) -> float:
        return self.inclination_deg * pi / 180.0

    @property
    def raan_rate_rad_s(self) -> float:
        return self.raan_rate_deg_s * pi / 180.0

    @property
    def ascending_node_longitude_rad(self) -> float:
        return self.ascending_node_longitude_deg * pi / 180.0

    @property
    def argument_of_perigee_rad(self) -> float:
        return self.argument_of_perigee_deg * pi / 180.0

    @property
    def mean_anomaly_rad(self) -> float:
        return self.mean_anomaly_deg * pi / 180.0


@dataclass(frozen=True)
class IacGpsAlmanac:
    source_url: str | None
    source_sha256: str
    records: tuple[IacGpsAlmanacRecord, ...]
    authority_note: str = (
        "IAC GPS almanac normalized from source-declared units; no hidden promotion to project MeanOrbit authority"
    )


@dataclass(frozen=True)
class IacBeidouAlmanacRecord:
    prn: int
    health_code: str
    eccentricity: float
    time_from_base_s: float
    inclination_rad: float
    raan_rate_rad_s: float
    sqrt_a_source: float
    ascending_node_longitude_rad: float
    argument_of_perigee_rad: float
    mean_anomaly_rad: float
    af0_s: float
    af1_s_s: float
    week: int

    @property
    def semi_major_axis_m_from_sqrt_a(self) -> float:
        return self.sqrt_a_source * self.sqrt_a_source


@dataclass(frozen=True)
class IacBeidouAlmanac:
    source_url: str | None
    source_sha256: str
    records: tuple[IacBeidouAlmanacRecord, ...]
    authority_note: str = (
        "IAC BeiDou almanac normalized with source-declared radian fields; source sqrt(A) is retained verbatim and its square is exposed explicitly"
    )


def _number(value: str, label: str) -> float:
    try:
        return float(value.replace(",", ".").replace("D", "E").replace("d", "e"))
    except ValueError as exc:
        raise ValueError(f"invalid IAC {label}: {value!r}") from exc


def _integer(value: str, label: str) -> int:
    try:
        return int(value.strip())
    except ValueError as exc:
        raise ValueError(f"invalid IAC {label}: {value!r}") from exc


def _date(value: str, label: str) -> date:
    try:
        return datetime.strptime(value.strip(), "%d.%m.%y").date()
    except ValueError as exc:
        raise ValueError(f"invalid IAC {label}: {value!r}") from exc


def normalize_iac_gps_almanac(table: IacTable) -> IacGpsAlmanac:
    if table.dataset != IacDataset.GPS_ALMANAC:
        raise ValueError("IAC table is not a GPS almanac dataset")
    required = ("PRN", "Date", "t", "e", "i", "dΩ/dt", "A", "LΩ", "ω", "m", "af0", "af1")
    positions = {name: index for index, name in enumerate(table.headers)}
    missing = [name for name in required if name not in positions]
    if missing:
        raise ValueError("IAC GPS table missing columns: " + ", ".join(missing))

    records: list[IacGpsAlmanacRecord] = []
    for row_number, row in enumerate(table.rows, start=1):
        try:
            record = IacGpsAlmanacRecord(
                prn=_integer(row[positions["PRN"]], "GPS PRN"),
                base_date_utc=_date(row[positions["Date"]], "GPS base date"),
                time_from_base_s=_number(row[positions["t"]], "GPS t"),
                eccentricity=_number(row[positions["e"]], "GPS eccentricity"),
                inclination_deg=_number(row[positions["i"]], "GPS inclination"),
                raan_rate_deg_s=_number(row[positions["dΩ/dt"]], "GPS dΩ/dt"),
                semi_major_axis_km=_number(row[positions["A"]], "GPS A"),
                ascending_node_longitude_deg=_number(row[positions["LΩ"]], "GPS LΩ"),
                argument_of_perigee_deg=_number(row[positions["ω"]], "GPS argument of perigee"),
                mean_anomaly_deg=_number(row[positions["m"]], "GPS mean anomaly"),
                af0_s=_number(row[positions["af0"]], "GPS af0"),
                af1_s_s=_number(row[positions["af1"]], "GPS af1"),
            )
        except (IndexError, ValueError) as exc:
            raise ValueError(f"invalid IAC GPS row {row_number}: {exc}") from exc
        if not 1 <= record.prn <= 63:
            raise ValueError(f"invalid IAC GPS row {row_number}: PRN out of range")
        if not 0.0 <= record.eccentricity < 1.0:
            raise ValueError(f"invalid IAC GPS row {row_number}: eccentricity out of range")
        if record.semi_major_axis_km <= 0.0:
            raise ValueError(f"invalid IAC GPS row {row_number}: A must be positive")
        if record.time_from_base_s < 0.0:
            raise ValueError(f"invalid IAC GPS row {row_number}: t must be non-negative")
        records.append(record)

    ids = [record.prn for record in records]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate IAC GPS PRNs")
    return IacGpsAlmanac(source_url=table.source_url, source_sha256=table.source_sha256, records=tuple(records))


def normalize_iac_beidou_almanac(table: IacTable) -> IacBeidouAlmanac:
    if table.dataset != IacDataset.BEIDOU_ALMANAC:
        raise ValueError("IAC table is not a BeiDou almanac dataset")
    required = ("PRN", "H", "e", "t", "δi", "Ω", "A", "Ω0", "ω", "m", "af0", "af1", "week")
    positions = {name: index for index, name in enumerate(table.headers)}
    missing = [name for name in required if name not in positions]
    if missing:
        raise ValueError("IAC BeiDou table missing columns: " + ", ".join(missing))

    records: list[IacBeidouAlmanacRecord] = []
    for row_number, row in enumerate(table.rows, start=1):
        try:
            raw_prn = row[positions["PRN"]].strip().upper()
            if raw_prn.startswith("C"):
                raw_prn = raw_prn[1:]
            record = IacBeidouAlmanacRecord(
                prn=_integer(raw_prn, "BeiDou PRN"),
                health_code=row[positions["H"]].strip(),
                eccentricity=_number(row[positions["e"]], "BeiDou eccentricity"),
                time_from_base_s=_number(row[positions["t"]], "BeiDou t"),
                inclination_rad=_number(row[positions["δi"]], "BeiDou inclination"),
                raan_rate_rad_s=_number(row[positions["Ω"]], "BeiDou Ω rate"),
                sqrt_a_source=_number(row[positions["A"]], "BeiDou sqrt(A)"),
                ascending_node_longitude_rad=_number(row[positions["Ω0"]], "BeiDou Ω0"),
                argument_of_perigee_rad=_number(row[positions["ω"]], "BeiDou argument of perigee"),
                mean_anomaly_rad=_number(row[positions["m"]], "BeiDou mean anomaly"),
                af0_s=_number(row[positions["af0"]], "BeiDou af0"),
                af1_s_s=_number(row[positions["af1"]], "BeiDou af1"),
                week=_integer(row[positions["week"]], "BeiDou week"),
            )
        except (IndexError, ValueError) as exc:
            raise ValueError(f"invalid IAC BeiDou row {row_number}: {exc}") from exc
        if not 1 <= record.prn <= 99:
            raise ValueError(f"invalid IAC BeiDou row {row_number}: PRN out of range")
        if record.health_code != "000":
            # Health is retained as source data; unhealthy records are not silently dropped.
            pass
        if not 0.0 <= record.eccentricity < 1.0:
            raise ValueError(f"invalid IAC BeiDou row {row_number}: eccentricity out of range")
        if record.sqrt_a_source <= 0.0:
            raise ValueError(f"invalid IAC BeiDou row {row_number}: sqrt(A) must be positive")
        if record.time_from_base_s < 0.0:
            raise ValueError(f"invalid IAC BeiDou row {row_number}: t must be non-negative")
        if record.week < 0:
            raise ValueError(f"invalid IAC BeiDou row {row_number}: week must be non-negative")
        records.append(record)

    ids = [record.prn for record in records]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate IAC BeiDou PRNs")
    return IacBeidouAlmanac(source_url=table.source_url, source_sha256=table.source_sha256, records=tuple(records))
