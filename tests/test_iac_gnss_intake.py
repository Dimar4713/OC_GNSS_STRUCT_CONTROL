from unittest.mock import patch

from fastapi.testclient import TestClient

from constellation_control.adapters.iac_gnss_tables import IAC_URLS, IacDataset, parse_iac_html, parse_iac_text
from constellation_control.preview.consolidated_release_app import create_preview_app, render_preview_page_for_test


def test_html_table_is_canonicalized_to_tsv() -> None:
    source = """<html><body><table><tr><th>PRN</th><th>e</th></tr><tr><td>1</td><td>0.01</td></tr></table></body></html>"""
    table = parse_iac_html(IacDataset.GPS_ALMANAC, source, source_url=IAC_URLS[IacDataset.GPS_ALMANAC])
    assert table.headers == ("PRN", "e")
    assert table.rows == (("1", "0.01"),)
    assert table.canonical_tsv == "PRN\te\n1\t0.01\n"
    assert len(table.source_sha256) == 64


def test_offline_text_accepts_tsv_and_semicolon_tables() -> None:
    tsv = parse_iac_text(IacDataset.GLONASS_ALMANAC, "slot\tT\n1\t40544\n")
    semi = parse_iac_text(IacDataset.BEIDOU_ALMANAC, "PRN;A\nC01;27800\n")
    assert tsv.rows[0] == ("1", "40544")
    assert semi.rows[0] == ("C01", "27800")


def test_preview_exposes_iac_card_and_all_fixed_sources() -> None:
    page = render_preview_page_for_test()
    assert 'id="iacGnssCard"' in page
    assert "/api/iac-gnss/online/" in page
    assert "beidou-constellation" in page

    client = TestClient(create_preview_app())
    response = client.get("/api/iac-gnss/sources")
    assert response.status_code == 200
    assert response.json() == {dataset.value: url for dataset, url in IAC_URLS.items()}


def test_offline_preview_preserves_source_hash_and_blocks_promotion() -> None:
    client = TestClient(create_preview_app())
    response = client.post(
        "/api/iac-gnss/offline-preview",
        json={"dataset": "gps-almanac", "filename": "gps.txt", "content_text": "PRN\te\n1\t0.01\n"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["source_filename"] == "gps.txt"
    assert payload["record_count"] == 1
    assert payload["runnable_promotion_allowed"] is False
    assert len(payload["source_sha256"]) == 64


def test_online_failure_is_fail_closed() -> None:
    client = TestClient(create_preview_app())
    with patch(
        "constellation_control.preview.iac_gnss_intake.fetch_iac_table",
        side_effect=ValueError("network unavailable"),
    ):
        response = client.get("/api/iac-gnss/online/glonass-almanac")
    assert response.status_code == 502
    assert "network unavailable" in response.json()["detail"]
