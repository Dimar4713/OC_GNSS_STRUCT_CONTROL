from datetime import date
import gzip

from constellation_control.preview.galileo_beidou_sources import (
    GSC_BASE_URL,
    bkg_beidou_daily_url,
    discover_gsc_current_almanac_url,
    fetch_bkg_beidou_daily,
    fetch_gsc_current_almanac,
)


class _Response:
    def __init__(self, body: bytes, content_type: str) -> None:
        self._body = body
        self.headers = {"Content-Type": content_type}

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self) -> bytes:
        return self._body


def test_discover_gsc_current_xml_link_stays_on_provider_origin() -> None:
    html = """<html><h2>Current almanac</h2><a href='/sites/default/files/sites/all/files/2026-09-01.xml'>2026-09-01</a><h2>Historical Records</h2></html>"""
    assert discover_gsc_current_almanac_url(html) == GSC_BASE_URL + "sites/default/files/sites/all/files/2026-09-01.xml"


def test_bkg_beidou_daily_url_uses_cn_rinex_product() -> None:
    url = bkg_beidou_daily_url(date(2026, 9, 3))
    assert "/2026/246/" in url
    assert url.endswith("BRDC00WRD_R_20262460000_01D_CN.rnx.gz")


def test_gsc_fetch_preserves_xml_sha(monkeypatch) -> None:
    index = b"<html><h2>Current almanac</h2><a href='/files/current.xml'>current</a><h2>Historical Records</h2></html>"
    xml = b"<?xml version='1.0'?><GalileoAlmanac><SVID>1</SVID></GalileoAlmanac>"

    def fake_urlopen(request, timeout):
        url = request.full_url
        if url.endswith("/gsc-products/almanac"):
            return _Response(index, "text/html")
        if url.endswith("/files/current.xml"):
            return _Response(xml, "text/xml")
        raise AssertionError(url)

    monkeypatch.setattr("constellation_control.preview.galileo_beidou_sources.urlopen", fake_urlopen)
    blob = fetch_gsc_current_almanac()
    assert blob.constellation == "Galileo"
    assert blob.source_url.endswith("/files/current.xml")
    assert len(blob.source_sha256) == 64
    assert blob.content == xml


def test_bkg_fetch_decompresses_and_validates_rinex(monkeypatch) -> None:
    rinex = b"     4.00           NAVIGATION DATA     M                   RINEX VERSION / TYPE\nEND OF HEADER\n"
    packed = gzip.compress(rinex)

    monkeypatch.setattr(
        "constellation_control.preview.galileo_beidou_sources.urlopen",
        lambda request, timeout: _Response(packed, "application/gzip"),
    )
    blob = fetch_bkg_beidou_daily(date(2026, 9, 3))
    assert blob.constellation == "BeiDou"
    assert blob.source_url.endswith("_CN.rnx.gz")
    assert blob.content == rinex
    assert len(blob.source_sha256) == 64
