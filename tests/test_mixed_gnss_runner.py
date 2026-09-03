from pathlib import Path
from types import SimpleNamespace

import yaml

from constellation_control.adapters.iac_gnss_tables import IacDataset, parse_iac_text
from constellation_control.application.run import load_scenario
from constellation_control.preview.gravity_release_app import render_preview_page_for_test
from constellation_control.preview.mixed_gnss_runner import MixedGnssBuildRequest, build_mixed_gnss_scenario

IAC_GLONASS_TEXT = """NS\tДата\tTΩ\tTоб\te\ti\tLΩ\tω\tδt2\tnl\tΔT
1\t08.08.26\t5679.75\t40543.81\t0.00039\t65.037445\t134.09329\t37.58972\t-1.7929077E-4\t1\t-4.272461E-4
"""

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


def _request() -> MixedGnssBuildRequest:
    return MixedGnssBuildRequest(
        source_scenario_name="orekit_design_smoke.yaml",
        template_satellite_id="SYNTH-REF",
        gps_source_format="yuma",
        gps_selection="healthy-only",
        glonass_health=0,
        glo_to_utc_s=1.0,
        gps_to_glo_s=2.0,
        glo_time_offset_s=3.0,
        target_scenario_name="mixed-current.yaml",
        new_scenario_id="mixed-current",
    )


def test_release_ui_exposes_full_mixed_constellation_builder() -> None:
    page = render_preview_page_for_test()
    assert 'id="mixedGnssRunnerCard"' in page
    assert "/api/mixed-gnss-runner/create" in page
    assert "Build full constellation" in page
    assert "ALMANAC-UNASSIGNED" in page


def test_batch_builder_replaces_parent_constellation_and_preserves_both_sources(tmp_path: Path, monkeypatch) -> None:
    source = load_scenario(Path("scenarios/orekit_design_smoke.yaml"))
    (tmp_path / "orekit_design_smoke.yaml").write_text(
        yaml.safe_dump(source.model_dump(mode="json"), sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    template = source.constellation.satellites[0]
    glo_table = parse_iac_text(
        IacDataset.GLONASS_ALMANAC,
        IAC_GLONASS_TEXT,
        source_url="https://glonass-iac.ru/glonass/ephemeris/ephemeris_json.php",
    )
    gps_url = "https://www.navcen.uscg.gov/sites/default/files/gps/almanac/current_yuma.alm"

    monkeypatch.setattr(
        "constellation_control.preview.mixed_gnss_runner.fetch_iac_table",
        lambda dataset: glo_table,
    )
    monkeypatch.setattr(
        "constellation_control.preview.mixed_gnss_runner.fetch_navcen_gps_almanac",
        lambda source_format: (gps_url, YUMA, __import__("hashlib").sha256(YUMA.encode()).hexdigest()),
    )

    class FakeGlonassClient:
        def __init__(self, url: str) -> None:
            assert url == source.orekit_sidecar_url

        def convert(self, **kwargs):
            return SimpleNamespace(
                mean_orbit=template.mean_orbit,
                backend_metadata={"glonass_slot": str(kwargs["slot"])},
            )

    class FakeGpsClient:
        def __init__(self, url: str) -> None:
            assert url == source.orekit_sidecar_url

        def convert(self, **kwargs):
            return SimpleNamespace(
                mean_orbit=template.mean_orbit,
                backend_metadata={"gps_prn": str(kwargs["prn"])},
            )

    monkeypatch.setattr(
        "constellation_control.preview.mixed_gnss_runner.OrekitGlonassAlmanacMeanConversionClient",
        FakeGlonassClient,
    )
    monkeypatch.setattr(
        "constellation_control.preview.mixed_gnss_runner.OrekitGpsAlmanacMeanConversionClient",
        FakeGpsClient,
    )

    payload = build_mixed_gnss_scenario(tmp_path, _request())
    assert payload["runnable"] is True
    assert payload["satellite_count"] == 2
    assert payload["glonass_count"] == 1
    assert payload["gps_count"] == 1
    assert payload["glonass_satellite_ids"] == ["GLO-01"]
    assert payload["gps_satellite_ids"] == ["GPS-01"]

    child = load_scenario(tmp_path / "mixed-current.yaml")
    assert [sat.satellite_id for sat in child.constellation.satellites] == ["GLO-01", "GPS-01"]
    assert all(sat.plane_id == "ALMANAC-UNASSIGNED" for sat in child.constellation.satellites)
    assert all(sat.spacecraft == template.spacecraft for sat in child.constellation.satellites)
    assert child.digital_twin is not None
    assert child.digital_twin.lineage is not None
    lineage = child.digital_twin.lineage
    assert lineage.transformation == "mixed_gnss_almanac_import"
    assert lineage.source_type == "mixed_gnss_almanac"
    assert glo_table.source_sha256 in lineage.authority
    assert payload["navcen_gps_source_sha256"] in lineage.authority
    assert lineage.source_sha256 == payload["source_manifest_sha256"]
