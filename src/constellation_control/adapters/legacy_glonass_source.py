from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class LegacyGlonassRecord:
    satellite_number: int
    day: int
    month: int
    year_2digit: int
    t_om_s: float
    t_ob_s: float
    eccentricity: float
    inclination_deg: float
    l_om_deg: float
    om_deg: float
    dt2: float
    nl: int
    d_t_s: float


_ADDITIONAL_REFERENCE_PAIRS = {
    25: (1, 2),
    26: (5, 6),
    27: (10, 11),
    28: (14, 15),
    29: (19, 20),
    30: (23, 24),
}


def parse_legacy_glonass_source(text: str) -> tuple[LegacyGlonassRecord, ...]:
    records: list[LegacyGlonassRecord] = []
    for line_number, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        fields = line.split()
        if len(fields) != 13:
            raise ValueError(f"legacy GLONASS line {line_number}: expected 13 fields, got {len(fields)}")
        try:
            record = LegacyGlonassRecord(
                satellite_number=int(fields[0]),
                day=int(fields[1]),
                month=int(fields[2]),
                year_2digit=int(fields[3]),
                t_om_s=float(fields[4]),
                t_ob_s=float(fields[5]),
                eccentricity=float(fields[6]),
                inclination_deg=float(fields[7]),
                l_om_deg=float(fields[8]),
                om_deg=float(fields[9]),
                dt2=float(fields[10]),
                nl=int(fields[11]),
                d_t_s=float(fields[12]),
            )
        except ValueError as exc:
            raise ValueError(f"legacy GLONASS line {line_number}: invalid numeric field") from exc
        records.append(record)

    numbers = [item.satellite_number for item in records]
    if numbers != list(range(1, 31)):
        raise ValueError("legacy GLONASS 24+6 source must contain satellites 1..30 exactly once in order")
    return tuple(records)


def load_legacy_glonass_source(path: Path) -> tuple[LegacyGlonassRecord, ...]:
    return parse_legacy_glonass_source(path.read_text(encoding="utf-8"))


def additional_reference_pairs() -> dict[int, tuple[int, int]]:
    return dict(_ADDITIONAL_REFERENCE_PAIRS)
