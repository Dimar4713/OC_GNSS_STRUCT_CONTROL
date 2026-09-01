from __future__ import annotations

import hashlib
import html
import json
import re
from dataclasses import dataclass
from enum import StrEnum
from html.parser import HTMLParser
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class IacDataset(StrEnum):
    GLONASS_ALMANAC = "glonass-almanac"
    GPS_ALMANAC = "gps-almanac"
    BEIDOU_ALMANAC = "beidou-almanac"
    BEIDOU_CONSTELLATION = "beidou-constellation"


IAC_URLS: dict[IacDataset, str] = {
    IacDataset.GLONASS_ALMANAC: "https://glonass-iac.ru/glonass/ephemeris/",
    IacDataset.GPS_ALMANAC: "https://glonass-iac.ru/gps/ephemeris/",
    IacDataset.BEIDOU_ALMANAC: "https://glonass-iac.ru/beidou/ephemeris/",
    IacDataset.BEIDOU_CONSTELLATION: "https://glonass-iac.ru/beidou/sostavOG/",
}

# Live source contract verified from aimeton-main-server on 2026-09-01.
IAC_DATA_URLS: dict[IacDataset, str] = {
    IacDataset.GLONASS_ALMANAC: "https://glonass-iac.ru/glonass/ephemeris/ephemeris_json.php",
    IacDataset.GPS_ALMANAC: "https://glonass-iac.ru/gps/ephemeris/ephemeris_json.php",
    IacDataset.BEIDOU_ALMANAC: "https://glonass-iac.ru/beidou/ephemeris/beidou_almanac_calc.php",
    IacDataset.BEIDOU_CONSTELLATION: IAC_URLS[IacDataset.BEIDOU_CONSTELLATION],
}


@dataclass(frozen=True)
class IacTable:
    dataset: IacDataset
    source_url: str | None
    source_sha256: str
    headers: tuple[str, ...]
    rows: tuple[tuple[str, ...], ...]
    canonical_tsv: str


_JSON_FIELDS: dict[IacDataset, tuple[tuple[str, str], ...]] = {
    IacDataset.GLONASS_ALMANAC: (
        ("NS", "ns"),
        ("Дата", "datetime"),
        ("TΩ", "Tomega"),
        ("Tоб", "Tapp"),
        ("e", "e"),
        ("i", "i"),
        ("LΩ", "Lomega"),
        ("ω", "W"),
        ("δt2", "deltaT2"),
        ("nl", "nl"),
        ("ΔT", "deltaT"),
    ),
    IacDataset.GPS_ALMANAC: (
        ("PRN", "PRN"),
        ("Date", "datetime"),
        ("t", "t"),
        ("e", "e"),
        ("i", "i"),
        ("dΩ/dt", "DomegaDT"),
        ("A", "A"),
        ("LΩ", "Lomega"),
        ("ω", "w"),
        ("m", "mm"),
        ("af0", "af0"),
        ("af1", "af1"),
    ),
    IacDataset.BEIDOU_ALMANAC: (
        ("PRN", "ID"),
        ("H", "Health"),
        ("e", "Eccentricity"),
        ("t", "Time of Applicability(s)"),
        ("δi", "Orbital Inclination(rad)"),
        ("Ω", "Rate of Right Ascen(r/s)"),
        ("A", "SQRT(A)  (m 1/2)"),
        ("Ω0", "Right Ascen at Week(rad)"),
        ("ω", "Argument of Perigee(rad)"),
        ("m", "Mean Anom(rad)"),
        ("af0", "Af0(s)"),
        ("af1", "Af1(s/s)"),
        ("week", "week"),
    ),
}


class _TableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.tables: list[list[list[str]]] = []
        self._table: list[list[str]] | None = None
        self._row: list[str] | None = None
        self._cell: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "table" and self._table is None:
            self._table = []
        elif self._table is not None and tag == "tr":
            self._row = []
        elif self._row is not None and tag in {"td", "th"}:
            self._cell = []

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag in {"td", "th"} and self._cell is not None and self._row is not None:
            value = " ".join("".join(self._cell).split())
            self._row.append(html.unescape(value))
            self._cell = None
        elif tag == "tr" and self._row is not None and self._table is not None:
            if any(cell.strip() for cell in self._row):
                self._table.append(self._row)
            self._row = None
        elif tag == "table" and self._table is not None:
            if self._table:
                self.tables.append(self._table)
            self._table = None


def _canonicalize(rows: list[list[str]]) -> tuple[tuple[str, ...], tuple[tuple[str, ...], ...], str]:
    if len(rows) < 2:
        raise ValueError("IAC table must contain a header and at least one data row")
    width = max(len(row) for row in rows)
    normalized = [tuple((row + [""] * (width - len(row)))[:width]) for row in rows]
    headers = normalized[0]
    if not any(value.strip() for value in headers):
        raise ValueError("IAC table header is empty")
    body = tuple(row for row in normalized[1:] if any(value.strip() for value in row))
    if not body:
        raise ValueError("IAC table contains no data rows")
    text = "\n".join("\t".join(row) for row in (headers, *body)) + "\n"
    return headers, body, text


def _value_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def parse_iac_json(dataset: IacDataset, content: str, *, source_url: str | None = None) -> IacTable:
    fields = _JSON_FIELDS.get(dataset)
    if fields is None:
        raise ValueError(f"dataset has no JSON source contract: {dataset.value}")
    try:
        payload = json.loads(content)
    except json.JSONDecodeError as exc:
        raise ValueError("IAC JSON source is invalid") from exc
    if not isinstance(payload, list) or not payload:
        raise ValueError("IAC JSON source must be a non-empty array")

    records: list[dict[str, Any]] = []
    for item in payload:
        if isinstance(item, dict):
            records.append(item)
        elif dataset != IacDataset.BEIDOU_ALMANAC:
            raise ValueError("IAC JSON source contains a non-record item")
    if not records:
        raise ValueError("IAC JSON source contains no records")

    required = {key for _, key in fields}
    for index, record in enumerate(records, start=1):
        missing = required.difference(record)
        if missing:
            names = ", ".join(sorted(missing))
            raise ValueError(f"IAC {dataset.value} record {index} missing fields: {names}")

    headers = [label for label, _ in fields]
    rows: list[list[str]] = [headers]
    for record in records:
        row = [_value_text(record[key]) for _, key in fields]
        if dataset == IacDataset.BEIDOU_ALMANAC:
            row[0] = f"C{row[0]}" if not row[0].upper().startswith("C") else row[0]
        rows.append(row)
    canonical_headers, body, canonical = _canonicalize(rows)
    return IacTable(
        dataset=dataset,
        source_url=source_url,
        source_sha256=hashlib.sha256(content.encode("utf-8")).hexdigest(),
        headers=canonical_headers,
        rows=body,
        canonical_tsv=canonical,
    )


def parse_iac_html(dataset: IacDataset, content: str, *, source_url: str | None = None) -> IacTable:
    parser = _TableParser()
    parser.feed(content)
    if not parser.tables:
        raise ValueError("no HTML table found in IAC response")
    # The BeiDou composition page contains a small summary table followed by the
    # authoritative detailed spacecraft table. Largest table selects the latter.
    rows = max(parser.tables, key=lambda table: (len(table), max((len(row) for row in table), default=0)))
    headers, body, canonical = _canonicalize(rows)
    return IacTable(
        dataset=dataset,
        source_url=source_url,
        source_sha256=hashlib.sha256(content.encode("utf-8")).hexdigest(),
        headers=headers,
        rows=body,
        canonical_tsv=canonical,
    )


def parse_iac_text(dataset: IacDataset, content: str, *, source_url: str | None = None) -> IacTable:
    lines = [line.strip() for line in content.splitlines() if line.strip() and not line.lstrip().startswith("#")]
    if len(lines) < 2:
        raise ValueError("IAC text table must contain a header and at least one data row")

    def split(line: str) -> list[str]:
        if "\t" in line:
            return [part.strip() for part in line.split("\t")]
        if ";" in line:
            return [part.strip() for part in line.split(";")]
        return [part.strip() for part in re.split(r"\s{2,}", line.strip())]

    rows = [split(line) for line in lines]
    headers, body, canonical = _canonicalize(rows)
    return IacTable(
        dataset=dataset,
        source_url=source_url,
        source_sha256=hashlib.sha256(content.encode("utf-8")).hexdigest(),
        headers=headers,
        rows=body,
        canonical_tsv=canonical,
    )


def fetch_iac_table(dataset: IacDataset, *, timeout_s: float = 15.0) -> IacTable:
    url = IAC_DATA_URLS[dataset]
    request = Request(url, headers={"User-Agent": "OC-GNSS-STRUCT-CONTROL/0.2.5"})
    try:
        with urlopen(request, timeout=timeout_s) as response:  # noqa: S310 - URL is fixed allowlist
            charset = response.headers.get_content_charset() or "utf-8"
            raw = response.read()
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        raise ValueError(f"IAC online source unavailable: {url}: {exc}") from exc
    try:
        content = raw.decode(charset)
    except (LookupError, UnicodeDecodeError) as exc:
        raise ValueError(f"IAC response cannot be decoded as {charset}") from exc
    if dataset == IacDataset.BEIDOU_CONSTELLATION:
        return parse_iac_html(dataset, content, source_url=url)
    return parse_iac_json(dataset, content, source_url=url)
