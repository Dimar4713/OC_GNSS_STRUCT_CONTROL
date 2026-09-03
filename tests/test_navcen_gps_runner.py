from pathlib import Path
from types import SimpleNamespace

import yaml
from fastapi.testclient import TestClient

from constellation_control.adapters.gnss_almanac import GnssAlmanacFormat, preview_gnss_almanac
from constellation_control.application.run import load_scenario
from constellation_control.preview.gravity_release_app import create_preview_app, render_preview_page_for_test
from constellation_control.preview.navcen_gps_runner import (
    NAVCEN_GPS_ALMANAC_URLS,
    NavcenGpsAuthorityRequest,
    fetch_navcen_gps_almanac,
)

YUMA = """******** Week 383 almanac for PRN-01 ********
ID:                         1
Health:                     000
Eccentricity:               0.123456E-002
Time of Applicability(s):  589824.0000
Orbital Inclination(rad):   0.959931
Rate of Right Ascen(r/s):  -0.800000E-008
SQRT(A)  (m 1/2):           5153.600000
Right Ascen at Week(rad):   1.000000
Argument of Perigee(rad):   0.500000
Mean Anom(rad):             2.000000
Af0(s):                     0.100000E-003
Af1(s/s):                   0.000000E+000
week:                       383
"""


class _Response:
    def __init__(self, body: bytes, content_type: str = "text/plain") -> None:
        self._body = body
        self.headers = {"Content-Type": content_type}

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self) -> bytes:
        return self._body


def test_navcen_urls_are_direct_current_almanac_files() -> None:
    assert NAVCEN_GPS_ALMANAC_URLS["yuma"].endswith("/current_yuma.alm")
    assert NAVCEN_GPS_ALMANAC_URLS["sem"].endswith("/current_sem.al3")
    assert all(url.startswith("https://www.navcen.uscg.gov/") for url in NAVCEN_GPS_ALMANAC_URLS.values())


def test_navcen_fetch_preserves_raw_sha_and_rejects_html(monkeypatch) -> None:
    monkeypatch.setattr(
        "constellation_control.preview.navcen_gps_runner.urlopen",
        lambda request, timeout: _Response(YUMA.encode("utf-8")),
    )
    url, text, sha256 = fetch_navcen_gps_almanac("yuma")
    assert url == NAVCEN_GPS_ALMANAC_URLS["yuma"]
    assert text == YUMA
    assert len(sha256) == 64

    monkeypatch.setattr(
        "constellation_control.preview.navcen_gps_runner.urlopen",
        lambda request, timeout: _Response(b"<html>blocked</html>", "text/html"),
    )
    try:
        fetch_navcen_gps_almanac("yuma")
    except ValueError as exc:
        assert "HTML" in str(exc)
    else:
        raise AssertionError("HTML response must fail closed")


def test_release_ui_exposes_navcen_gps_runnable_chain() -> None:
    page = render_preview_page_for_test()
    assert 'id="navcenGpsRunnerCard"' in page
    assert "/api/navcen-gps-runner/create" in page
    assert "USCG NAVCEN" in page


def test_create_endpoint_preserves_navcen_provenance(tmp_path: Path, monkeypatch) -> None:
    source = load_scenario(Path("scenarios/orekit_design_smoke.yaml"))
    source_path = tmp_path / "orekit_design_smoke.yaml"
    source_path.write_text(
        yaml.safe_dump(source.model_dump(mode="json"), sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    satellite = source.constellation.satellites[0]
    assert satellite.mean_orbit is not None
    preview = preview_gnss_almanac("current_yuma.alm", YUMA, GnssAlmanacFormat.GPS_YUMA)
    record = preview.records[0]
    result = SimpleNamespace(
        mean_orbit=satellite.mean_orbit,
        backend_metadata={"gps_prn": "1", "source_authority": "GPS-ALMANAC-OREKIT-GNSS"},
    )
    url = NAVCEN_GPS_ALMANAC_URLS["yuma"]

    def fake_authority(root, request):
        assert root == tmp_path
        assert request.prn == 1
        return url, preview, record, source, satellite, result

    monkeypatch.setattr("constellation_control.preview.navcen_gps_runner._authority", fake_authority)
    client = TestClient(create_preview_app(tmp_path, tmp_path / "runs"))
    response = client.post(
        "/api/navcen-gps-runner/create",
        json={
            "source_format": "yuma",
            "source_scenario_name": "orekit_design_smoke.yaml",
            "satellite_id": satellite.satellite_id,
            "prn": 1,
            "target_scenario_name": "navcen-gps-derived.yaml",
            "new_scenario_id": "navcen-gps-derived",
        },
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["runnable"] is True
    assert payload["provider"] == "USCG NAVCEN"
    assert payload["source_url"] == url
    assert payload["source_sha256"] == preview.source_sha256

    child = load_scenario(tmp_path / "navcen-gps-derived.yaml")
    assert child.digital_twin is not None
    assert child.digital_twin.lineage is not None
    assert child.digital_twin.lineage.source_type == "gps_yuma"
    assert child.digital_twin.lineage.source_name == url
    assert child.digital_twin.lineage.source_sha256 == preview.source_sha256
    assert "USCG NAVCEN direct online source" in child.digital_twin.lineage.authority


def test_authority_endpoint_validates_request_before_network() -> None:
    client = TestClient(create_preview_app())
    response = client.post(
        "/api/navcen-gps-runner/authority",
        json={
            "source_format": "invalid",
            "source_scenario_name": "orekit_design_smoke.yaml",
            "satellite_id": "SYNTH-REF",
            "prn": 1,
        },
    )
    assert response.status_code == 422
