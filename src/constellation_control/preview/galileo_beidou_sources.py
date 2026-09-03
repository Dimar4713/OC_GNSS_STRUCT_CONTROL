from __future__ import annotations

import gzip
import hashlib
import re
from dataclasses import dataclass
from datetime import date
from html import unescape
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import Request, urlopen

GSC_ALMANAC_INDEX_URL = "https://www.gsc-europa.eu/gsc-products/almanac"
GSC_BASE_URL = "https://www.gsc-europa.eu/"
BKG_DAILY_BRDC_ROOT = "https://igs.bkg.bund.de/root_ftp/IGS/BRDC"
BKG_NTRIP_BRDC_ROOT = "https://igs.bkg.bund.de/root_ftp/NTRIP/BRDC/"


@dataclass(frozen=True)
class GnssSourceBlob:
    provider: str
    constellation: str
    source_url: str
    source_sha256: str
    content: bytes
    content_encoding: str

    def text(self) -> str:
        return self.content.decode(self.content_encoding)


def _fetch_bytes(url: str, *, timeout_s: float = 20.0) -> tuple[bytes, str]:
    request = Request(url, headers={"User-Agent": "OC-GNSS-STRUCT-CONTROL/0.2.6"})
    try:
        with urlopen(request, timeout=timeout_s) as response:
            raw = response.read()
            content_type = response.headers.get("Content-Type", "")
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        raise OSError(f"GNSS source fetch failed for {url}: {exc}") from exc
    if not raw:
        raise ValueError(f"GNSS source returned an empty response: {url}")
    return raw, content_type


def discover_gsc_current_almanac_url(index_html: str) -> str:
    current = re.search(
        r"Current\s+almanac(?P<section>.*?)(?:Historical\s+Records|$)",
        index_html,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if current is None:
        raise ValueError("GSC almanac page has no Current almanac section")
    match = re.search(r'href=["\'](?P<href>[^"\']+\.xml)["\']', current.group("section"), flags=re.IGNORECASE)
    if match is None:
        raise ValueError("GSC Current almanac section contains no XML link")
    url = urljoin(GSC_BASE_URL, unescape(match.group("href")))
    if not url.startswith(GSC_BASE_URL):
        raise ValueError("GSC current almanac link left the approved provider origin")
    return url


def fetch_gsc_current_almanac(*, timeout_s: float = 20.0) -> GnssSourceBlob:
    index_raw, index_type = _fetch_bytes(GSC_ALMANAC_INDEX_URL, timeout_s=timeout_s)
    if "html" not in index_type.lower() and b"<html" not in index_raw[:512].lower():
        raise ValueError("GSC almanac index did not return HTML")
    index_html = index_raw.decode("utf-8")
    xml_url = discover_gsc_current_almanac_url(index_html)
    raw, content_type = _fetch_bytes(xml_url, timeout_s=timeout_s)
    if b"<html" in raw[:512].lower() or "html" in content_type.lower():
        raise ValueError("GSC current almanac endpoint returned HTML instead of XML")
    if b"<?xml" not in raw[:256].lower() and b"<" not in raw[:32]:
        raise ValueError("GSC current almanac response is not XML-like")
    return GnssSourceBlob(
        provider="European GNSS Service Centre (GSC)",
        constellation="Galileo",
        source_url=xml_url,
        source_sha256=hashlib.sha256(raw).hexdigest(),
        content=raw,
        content_encoding="utf-8",
    )


def bkg_beidou_daily_url(day: date) -> str:
    doy = day.timetuple().tm_yday
    return (
        f"{BKG_DAILY_BRDC_ROOT}/{day.year:04d}/{doy:03d}/"
        f"BRDC00WRD_R_{day.year:04d}{doy:03d}0000_01D_CN.rnx.gz"
    )


def fetch_bkg_beidou_daily(day: date, *, timeout_s: float = 20.0) -> GnssSourceBlob:
    url = bkg_beidou_daily_url(day)
    raw, content_type = _fetch_bytes(url, timeout_s=timeout_s)
    if "html" in content_type.lower() or b"<html" in raw[:256].lower():
        raise ValueError("BKG BeiDou endpoint returned HTML instead of compressed RINEX")
    try:
        rinex = gzip.decompress(raw)
    except OSError as exc:
        raise ValueError("BKG BeiDou source is not valid gzip-compressed RINEX") from exc
    if b"RINEX" not in rinex[:256] or b"NAVIGATION" not in rinex[:256].upper():
        raise ValueError("BKG BeiDou payload does not look like a RINEX navigation file")
    return GnssSourceBlob(
        provider="BKG GNSS Data Center / IGS",
        constellation="BeiDou",
        source_url=url,
        source_sha256=hashlib.sha256(raw).hexdigest(),
        content=rinex,
        content_encoding="ascii",
    )
