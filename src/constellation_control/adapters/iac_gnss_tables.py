from __future__ import annotations

import hashlib
import html
import re
from dataclasses import dataclass
from enum import StrEnum
from html.parser import HTMLParser
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


@dataclass(frozen=True)
class IacTable:
    dataset: IacDataset
    source_url: str | None
    source_sha256: str
    headers: tuple[str, ...]
    rows: tuple[tuple[str, ...], ...]
    canonical_tsv: str


class _TableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.tables: list[list[list[str]]] = []
        self._table: list[list[str]] | None = None
        self._row: list[str] | None = None
        self._cell: list[str] | None = None

    def handle_starttag(self, tag: str, attrs) -> None:
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


def parse_iac_html(dataset: IacDataset, content: str, *, source_url: str | None = None) -> IacTable:
    parser = _TableParser()
    parser.feed(content)
    if not parser.tables:
        raise ValueError("no HTML table found in IAC response")
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
    url = IAC_URLS[dataset]
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
    return parse_iac_html(dataset, content, source_url=url)
