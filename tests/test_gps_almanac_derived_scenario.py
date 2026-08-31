from __future__ import annotations

from pathlib import Path

import pytest

from constellation_control.adapters.gnss_almanac import GnssAlmanacFormat
from constellation_control.adapters.orekit.mean_conversion import (
    MeanConversionResult,
    OrekitGpsAlmanacMeanConversionClient,
)
from constellation_control.application.run import load_scenario
from constellation_control.domain.models import MeanElementDefinition, MeanOrbit
from constellation_control.preview.gps_almanac_promotion import (
    GpsAlmanacAuthorityRequest,
    GpsAlmanacCreateRequest,
    create_gps_almanac_derived_scenario,
    preview_gps_almanac_authority,
)

YUMA = """ID:                         1
Health:                     000
Eccentricity:               0.0100000000
Time of Applicability(s):  589824.0000
Orbital Inclination(rad):   0.9500000000
Rate of Right Ascen(r/s):  -0.8000000000D-08
SQRT(A)  (m 1/2):           5153.7950000000
Right Ascen at Week(rad):    1.0000000000
Argument of Perigee(rad):    0.5000000000
Mean Anom(rad):              0.2500000000
Af0(s):                      0.1000000000D-03
Af1(s/s):                    0.0000000000D+00
week:                        2399
"""


def _scenario_root(tmp_path: Path) -> Path:
    source = Path("scenarios/orekit_design_smoke.yaml").read_text(encoding="utf-8")
    root = tmp_path / "scenarios"
    root.mkdir()
    (root / "source.yaml").write_text(source, encoding="utf-8")
    return root


def _fake_convert(  # noqa: ANN202
    self,  # noqa: ANN001
    *,
    source_format,
    source_name,
    source_text,
    prn,
    frame,
    target_epoch,
    target_time_scale,
    spacecraft,
    force_model,
):  # noqa: ANN001
    assert source_format == "gps-yuma"
    assert source_name == "gps.alm"
    assert source_text == YUMA
    assert prn == 1
    assert target_time_scale.value == "UTC"
    return MeanConversionResult(
        mean_orbit=MeanOrbit(
            a_m=26_560_000.0,
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
            "source_authority": "GPS-ALMANAC-OREKIT-GNSS",
            "almanac_source_format": source_format,
            "gps_prn": str(prn),
            "almanac_epoch": "2025-12-13T23:59:42.000Z",
            "gnss_target_epoch": target_epoch.isoformat(),
            "gnss_target_time_scale": target_time_scale.value,
            "conversion_chain": "raw-YUMA->Orekit-YUMAParser->Orekit-GNSS-propagator@target-epoch->osculating-PV->inertial-frame->Orekit-DSST-mean",
        },
    )


def test_creates_immutable_gps_almanac_child_with_provenance(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    root = _scenario_root(tmp_path)
    monkeypatch.setattr(OrekitGpsAlmanacMeanConversionClient, "convert", _fake_convert)
    source_before = (root / "source.yaml").read_text(encoding="utf-8")

    result = create_gps_almanac_derived_scenario(
        root,
        GpsAlmanacCreateRequest(
            filename="gps.alm",
            content_text=YUMA,
            source_format=GnssAlmanacFormat.GPS_YUMA,
            source_scenario_name="source.yaml",
            satellite_id="SYNTH-REF",
            prn=1,
            target_scenario_name="derived.yaml",
            new_scenario_id="derived-gps-almanac",
        ),
    )

    assert result["saved"] is True
    assert (root / "source.yaml").read_text(encoding="utf-8") == source_before
    child = load_scenario(root / "derived.yaml")
    assert child.scenario_id == "derived-gps-almanac"
    ref = next(item for item in child.constellation.satellites if item.satellite_id == "SYNTH-REF")
    assert ref.mean_orbit.a_m == 26_560_000.0
    assert child.digital_twin is not None
    lineage = child.digital_twin.lineage
    assert lineage is not None
    assert lineage.transformation == "gps_almanac_import"
    assert lineage.source_type == "gps_yuma"
    assert lineage.source_name == "gps.alm"
    assert lineage.source_record_id == "1"
    assert lineage.authority == "GPS-ALMANAC-OREKIT-GNSS"
    assert lineage.source_sha256 == result["source_sha256"]


def test_preview_attests_parent_epoch_and_authority(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    root = _scenario_root(tmp_path)
    monkeypatch.setattr(OrekitGpsAlmanacMeanConversionClient, "convert", _fake_convert)
    result = preview_gps_almanac_authority(
        root,
        GpsAlmanacAuthorityRequest(
            filename="gps.alm",
            content_text=YUMA,
            source_format=GnssAlmanacFormat.GPS_YUMA,
            source_scenario_name="source.yaml",
            satellite_id="SYNTH-REF",
            prn=1,
        ),
    )
    assert result["backend_metadata"]["source_authority"] == "GPS-ALMANAC-OREKIT-GNSS"
    assert result["backend_metadata"]["gps_prn"] == "1"
    assert result["target_time_scale"] == "UTC"


def test_glonass_is_rejected_by_gps_promotion_path(tmp_path: Path) -> None:
    root = _scenario_root(tmp_path)
    with pytest.raises(ValueError, match="only GPS YUMA/SEM"):
        preview_gps_almanac_authority(
            root,
            GpsAlmanacAuthorityRequest(
                filename="glo.txt",
                content_text="Slot: 1",
                source_format=GnssAlmanacFormat.GLONASS_TEXT,
                source_scenario_name="source.yaml",
                satellite_id="SYNTH-REF",
                prn=1,
            ),
        )


def test_existing_target_is_never_overwritten(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    root = _scenario_root(tmp_path)
    monkeypatch.setattr(OrekitGpsAlmanacMeanConversionClient, "convert", _fake_convert)
    target = root / "derived.yaml"
    target.write_text("sentinel\n", encoding="utf-8")
    with pytest.raises(ValueError, match="overwrite is forbidden"):
        create_gps_almanac_derived_scenario(
            root,
            GpsAlmanacCreateRequest(
                filename="gps.alm",
                content_text=YUMA,
                source_format=GnssAlmanacFormat.GPS_YUMA,
                source_scenario_name="source.yaml",
                satellite_id="SYNTH-REF",
                prn=1,
                target_scenario_name="derived.yaml",
                new_scenario_id="derived-gps-almanac",
            ),
        )
    assert target.read_text(encoding="utf-8") == "sentinel\n"
