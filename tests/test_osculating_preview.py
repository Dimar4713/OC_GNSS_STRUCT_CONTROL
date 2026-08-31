from __future__ import annotations

from pathlib import Path

import yaml

from constellation_control.adapters.orekit.mean_conversion import MeanConversionResult
from constellation_control.application.run import load_scenario
from constellation_control.domain.models import MeanElementDefinition, MeanOrbit
from constellation_control.preview import osculating_input as module
from constellation_control.preview.osculating_input import (
    OsculatingCreateRequest,
    OsculatingInputRequest,
    create_osculating_derived_scenario,
    preview_osculating_conversion,
)


def _copy_scenario(tmp_path: Path) -> Path:
    source = Path("scenarios/orekit_design_smoke.yaml")
    target = tmp_path / source.name
    target.write_bytes(source.read_bytes())
    return target


def _result(fingerprint: str) -> MeanConversionResult:
    return MeanConversionResult(
        mean_orbit=MeanOrbit(
            a_m=26_559_900.0,
            ex=0.0008,
            ey=0.0002,
            ix=0.5,
            iy=0.1,
            lambda_rad=1.2,
            definition=MeanElementDefinition(
                theory="orekit-dsst-13.1.7-from-osculating",
                force_model_fingerprint=fingerprint,
            ),
        ),
        backend_metadata={
            "backend": "orekit-dsst-mean-conversion",
            "orekit_version": "13.1.7",
            "orekit_data_sha256": "a" * 64,
            "gravity_model": "EIGEN-6S",
        },
    )


def _request(source_name: str, satellite_id: str) -> OsculatingInputRequest:
    return OsculatingInputRequest(
        source_scenario_name=source_name,
        satellite_id=satellite_id,
        a_m=26_560_000.0,
        e=0.001,
        i_deg=64.8,
        pa_deg=0.0,
        raan_deg=0.0,
        anomaly_deg=0.0,
        anomaly_type="true",
    )


def test_preview_is_immutable(tmp_path: Path, monkeypatch) -> None:
    source_path = _copy_scenario(tmp_path)
    source = load_scenario(source_path)
    satellite_id = source.constellation.satellites[0].satellite_id
    before = source_path.read_bytes()
    monkeypatch.setattr(
        module.OrekitMeanConversionClient,
        "convert",
        lambda self, **kwargs: _result(source.force_model.fingerprint()),
    )

    payload = preview_osculating_conversion(tmp_path, _request(source_path.name, satellite_id))

    assert payload["valid"] is True
    assert payload["satellite_id"] == satellite_id
    assert source_path.read_bytes() == before
    assert list(tmp_path.glob("*.yaml")) == [source_path]


def test_create_changes_only_selected_satellite_and_records_lineage(tmp_path: Path, monkeypatch) -> None:
    source_path = _copy_scenario(tmp_path)
    source = load_scenario(source_path)
    selected = source.constellation.satellites[0]
    untouched = source.constellation.satellites[1]
    before = source_path.read_bytes()
    converted = _result(source.force_model.fingerprint())
    monkeypatch.setattr(module.OrekitMeanConversionClient, "convert", lambda self, **kwargs: converted)

    request = OsculatingCreateRequest(
        **_request(source_path.name, selected.satellite_id).model_dump(),
        target_scenario_name="derived-osculating.yaml",
        new_scenario_id="derived-osculating",
    )
    result = create_osculating_derived_scenario(tmp_path, request)
    child = load_scenario(tmp_path / "derived-osculating.yaml")

    assert source_path.read_bytes() == before
    assert result["parent_config_hash"] == source.config_hash()
    child_selected = next(s for s in child.constellation.satellites if s.satellite_id == selected.satellite_id)
    child_untouched = next(s for s in child.constellation.satellites if s.satellite_id == untouched.satellite_id)
    assert child_selected.mean_orbit == converted.mean_orbit
    assert child_untouched.mean_orbit == untouched.mean_orbit
    assert child.digital_twin is not None
    assert child.digital_twin.lineage is not None
    assert child.digital_twin.lineage.transformation == "osculating_import"
    assert child.digital_twin.lineage.parent_config_hash == source.config_hash()


def test_existing_target_is_not_overwritten(tmp_path: Path, monkeypatch) -> None:
    source_path = _copy_scenario(tmp_path)
    source = load_scenario(source_path)
    satellite_id = source.constellation.satellites[0].satellite_id
    target = tmp_path / "existing.yaml"
    target.write_text(yaml.safe_dump({"sentinel": True}), encoding="utf-8")
    monkeypatch.setattr(
        module.OrekitMeanConversionClient,
        "convert",
        lambda self, **kwargs: _result(source.force_model.fingerprint()),
    )
    request = OsculatingCreateRequest(
        **_request(source_path.name, satellite_id).model_dump(),
        target_scenario_name=target.name,
        new_scenario_id="derived-osculating",
    )

    try:
        create_osculating_derived_scenario(tmp_path, request)
    except ValueError as exc:
        assert "overwrite" in str(exc)
    else:
        raise AssertionError("existing target must be rejected")
    assert yaml.safe_load(target.read_text(encoding="utf-8")) == {"sentinel": True}
