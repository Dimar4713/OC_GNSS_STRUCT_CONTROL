from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from constellation_control.preview.consolidated_release_app import create_preview_app, render_preview_page_for_test


YUMA = """
ID: 1
Health: 0
Eccentricity: 0.01
Time of Applicability(s): 589824
Orbital Inclination(rad): 0.96
Rate of Right Ascen(r/s): -8E-9
SQRT(A)  (m 1/2): 5153.65
Right Ascen at Week(rad): 1.2
Argument of Perigee(rad): 0.4
Mean Anom(rad): 2.3
Af0(s): 1E-4
Af1(s/s): 2E-12
week: 2234
"""


def test_consolidated_page_contains_gnss_almanac_card() -> None:
    page = render_preview_page_for_test()
    assert "GNSS Almanac intake" in page
    assert "/api/gnss-almanac/preview" in page
    assert "gps-yuma" in page
    assert "gps-sem" in page
    assert "glonass-text" in page


def test_packaged_route_returns_preview_only_almanac(tmp_path: Path) -> None:
    app = create_preview_app(tmp_path / "scenarios", tmp_path / "runs")
    response = TestClient(app).post(
        "/api/gnss-almanac/preview",
        json={"filename": "current.alm", "content_text": YUMA, "source_format": "gps-yuma"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["source_format"] == "gps-yuma"
    assert payload["runnable_promotion_allowed"] is False
    assert payload["records"][0]["prn"] == 1
