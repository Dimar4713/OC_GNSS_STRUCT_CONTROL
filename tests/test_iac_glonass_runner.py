from pathlib import Path
from types import SimpleNamespace

import yaml
from fastapi.testclient import TestClient

from constellation_control.adapters.iac_glonass_almanac import normalize_iac_glonass_almanac
from constellation_control.adapters.iac_gnss_tables import IacDataset, parse_iac_text
from constellation_control.application.run import load_scenario
from constellation_control.preview.gravity_release_app import create_preview_app, render_preview_page_for_test
from constellation_control.preview.iac_glonass_runner import (
    IacGlonassRunnerAuthorityRequest,
    _table,
)


IAC_GLONASS_TEXT = """NS\tДата\tTΩ\tTоб\te\ti\tLΩ\tω\tδt2\tnl\tΔT
1\t08.08.26\t5679.75\t40543.81\t0.00039\t65.037445\t134.09329\t37.58972\t-1.7929077E-4\t1\t-4.272461E-4
"""


def _request(**extra):
    payload = dict(
        source_mode="offline",
        filename="glonass-iac.tsv",
        content_text=IAC_GLONASS_TEXT,
        source_scenario_name="orekit_design_smoke.yaml",
        satellite_id="SYNTH-REF",
        slot=1,
        health=0,
        glo_to_utc_s=1.0,
        gps_to_glo_s=2.0,
        glo_time_offset_s=3.0,
    )
    payload.update(extra)
    return IacGlonassRunnerAuthorityRequest(**payload)


def test_offline_iac_source_is_normalized_before_authority() -> None:
    table = _table(_request())
    almanac = normalize_iac_glonass_almanac(table)
    assert table.dataset == IacDataset.GLONASS_ALMANAC
    assert almanac.records[0].slot == 1
    assert almanac.records[0].frequency_channel == 1
    assert len(table.source_sha256) == 64


def test_release_ui_exposes_iac_glonass_runnable_chain() -> None:
    page = render_preview_page_for_test()
    assert 'id="iacGlonassRunnerCard"' in page
    assert "/api/iac-glonass-runner/create" in page
    assert "Build runnable scenario" in page


def test_create_endpoint_preserves_iac_provenance_and_writes_runnable_child(tmp_path: Path, monkeypatch) -> None:
    source = load_scenario(Path("scenarios/orekit_design_smoke.yaml"))
    source_path = tmp_path / "orekit_design_smoke.yaml"
    source_path.write_text(
        yaml.safe_dump(source.model_dump(mode="json"), sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    satellite = source.constellation.satellites[0]
    assert satellite.mean_orbit is not None
    table = parse_iac_text(IacDataset.GLONASS_ALMANAC, IAC_GLONASS_TEXT)
    record = normalize_iac_glonass_almanac(table).records[0]
    result = SimpleNamespace(
        mean_orbit=satellite.mean_orbit,
        backend_metadata={
            "glonass_slot": "1",
            "source_authority": "GLONASS-ALMANAC-OREKIT-ANALYTICAL",
        },
    )

    def fake_authority(root, request):
        assert root == tmp_path
        assert request.glo_to_utc_s == 1.0
        return table, record, source, satellite, result

    monkeypatch.setattr("constellation_control.preview.iac_glonass_runner._authority", fake_authority)
    client = TestClient(create_preview_app(tmp_path, tmp_path / "runs"))
    response = client.post(
        "/api/iac-glonass-runner/create",
        json={
            **_request().model_dump(mode="json"),
            "target_scenario_name": "iac-glonass-derived.yaml",
            "new_scenario_id": "iac-glonass-derived",
        },
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["runnable"] is True
    assert payload["source_sha256"] == table.source_sha256
    assert payload["scenario_name"] == "iac-glonass-derived.yaml"

    child = load_scenario(tmp_path / "iac-glonass-derived.yaml")
    assert child.scenario_id == "iac-glonass-derived"
    assert child.digital_twin is not None
    assert child.digital_twin.lineage is not None
    assert child.digital_twin.lineage.parent_scenario_id == source.scenario_id
    assert child.digital_twin.lineage.source_sha256 == table.source_sha256
    assert child.digital_twin.lineage.source_record_id == "1"
    assert "IAC normalized bridge" in child.digital_twin.lineage.authority


def test_offline_mode_fails_closed_without_time_authority_fields() -> None:
    client = TestClient(create_preview_app())
    response = client.post(
        "/api/iac-glonass-runner/authority",
        json={
            "source_mode": "offline",
            "filename": "glonass-iac.tsv",
            "content_text": IAC_GLONASS_TEXT,
            "source_scenario_name": "orekit_design_smoke.yaml",
            "satellite_id": "SYNTH-REF",
            "slot": 1,
            "health": 0,
        },
    )
    assert response.status_code == 422
