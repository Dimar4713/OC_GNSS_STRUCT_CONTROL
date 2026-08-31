from __future__ import annotations

from pathlib import Path

import pytest

from constellation_control.adapters.orekit.mean_conversion import (
    MeanConversionResult,
    OrekitTleMeanConversionClient,
)
from constellation_control.application.run import load_scenario
from constellation_control.domain.models import MeanElementDefinition, MeanOrbit
from constellation_control.preview.norad_input import (
    NoradAuthorityRequest,
    NoradCreateRequest,
    create_norad_derived_scenario,
    preview_norad_authority,
)

LINE1 = "1 25544U 98067A   24001.50000000  .00000000  00000-0  00000-0 0  9992"
LINE2 = "2 25544  51.6400 123.4567 0005000  10.0000 350.0000 15.50000000123456"
TLE = f"ISS (ZARYA)\n{LINE1}\n{LINE2}\n"


def _scenario_root(tmp_path: Path, *, epoch: str = "2024-01-01T12:00:00Z") -> Path:
    source = Path("scenarios/orekit_design_smoke.yaml").read_text(encoding="utf-8")
    source = source.replace("2026-01-01T00:00:00Z", epoch)
    root = tmp_path / "scenarios"
    root.mkdir()
    (root / "source.yaml").write_text(source, encoding="utf-8")
    return root


def _fake_convert(self, *, line1, line2, frame, spacecraft, force_model):  # noqa: ANN001, ANN202
    assert line1 == LINE1
    assert line2 == LINE2
    return MeanConversionResult(
        mean_orbit=MeanOrbit(
            a_m=6_800_000.0,
            ex=0.001,
            ey=0.002,
            ix=0.1,
            iy=0.2,
            lambda_rad=0.3,
            definition=MeanElementDefinition(
                representation="equinoctial",
                theory="orekit-dsst-13.1.7-from-osculating",
                force_model_fingerprint=force_model.fingerprint(),
            ),
        ),
        backend_metadata={
            "backend": "orekit-dsst-mean-conversion",
            "source_authority": "NORAD-TLE-SGP4",
            "sgp4_frame": "TEME",
            "sgp4_epoch": "2024-01-01T12:00:00.000Z",
            "norad_satellite_number": "25544",
            "conversion_chain": "TLE->Orekit-SGP4/TEME->osculating-PV->inertial-frame->Orekit-DSST-mean",
        },
    )


def test_creates_immutable_tle_derived_scenario_with_provenance(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    root = _scenario_root(tmp_path)
    monkeypatch.setattr(OrekitTleMeanConversionClient, "convert", _fake_convert)
    source_before = (root / "source.yaml").read_text(encoding="utf-8")

    result = create_norad_derived_scenario(
        root,
        NoradCreateRequest(
            filename="iss.tle",
            content_text=TLE,
            source_scenario_name="source.yaml",
            satellite_id="SYNTH-REF",
            norad_satellite_number=25544,
            target_scenario_name="derived.yaml",
            new_scenario_id="derived-norad-tle",
        ),
    )

    assert result["saved"] is True
    assert (root / "source.yaml").read_text(encoding="utf-8") == source_before
    child = load_scenario(root / "derived.yaml")
    assert child.scenario_id == "derived-norad-tle"
    ref = next(item for item in child.constellation.satellites if item.satellite_id == "SYNTH-REF")
    assert ref.mean_orbit.a_m == 6_800_000.0
    assert child.digital_twin is not None
    lineage = child.digital_twin.lineage
    assert lineage is not None
    assert lineage.transformation == "norad_tle_import"
    assert lineage.source_type == "norad_tle"
    assert lineage.source_name == "iss.tle"
    assert lineage.source_record_id == "25544"
    assert lineage.authority == "NORAD-TLE-SGP4"
    assert lineage.source_sha256 == result["source_sha256"]


def test_blocks_tle_when_epoch_differs_from_parent(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    root = _scenario_root(tmp_path, epoch="2026-01-01T00:00:00Z")
    called = False

    def should_not_convert(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
        nonlocal called
        called = True
        raise AssertionError("authority must not be called for epoch mismatch")

    monkeypatch.setattr(OrekitTleMeanConversionClient, "convert", should_not_convert)
    with pytest.raises(ValueError, match="TLE epoch does not match parent scenario epoch"):
        preview_norad_authority(
            root,
            NoradAuthorityRequest(
                filename="iss.tle",
                content_text=TLE,
                source_scenario_name="source.yaml",
                satellite_id="SYNTH-REF",
                norad_satellite_number=25544,
            ),
        )
    assert called is False


def test_omm_remains_fail_closed_for_derived_scenario(tmp_path: Path) -> None:
    root = _scenario_root(tmp_path)
    omm = """{
      "NORAD_CAT_ID": 25544,
      "EPOCH": "2024-01-01T12:00:00Z",
      "INCLINATION": 51.64,
      "RA_OF_ASC_NODE": 123.4567,
      "ECCENTRICITY": 0.0005,
      "ARG_OF_PERICENTER": 10.0,
      "MEAN_ANOMALY": 350.0,
      "MEAN_MOTION": 15.5
    }"""
    with pytest.raises(ValueError, match="OMM remains non-promotable"):
        preview_norad_authority(
            root,
            NoradAuthorityRequest(
                filename="iss.json",
                content_text=omm,
                source_scenario_name="source.yaml",
                satellite_id="SYNTH-REF",
                norad_satellite_number=25544,
            ),
        )
