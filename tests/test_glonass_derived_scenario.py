from __future__ import annotations

from pathlib import Path

import pytest

from constellation_control.adapters.orekit.mean_conversion import (
    MeanConversionResult,
    OrekitGlonassAlmanacMeanConversionClient,
)
from constellation_control.application.run import load_scenario
from constellation_control.domain.models import MeanElementDefinition, MeanOrbit
from constellation_control.preview.glonass_almanac_input import (
    GlonassAuthorityRequest,
    GlonassCreateRequest,
    create_glonass_derived_scenario,
    preview_glonass_authority,
)

AUTHORITY_SOURCE = """Slot: 1
Frequency channel: -7
Health: 0
Reference date: 2026-08-31
Reference time(s): 3600
Lambda(rad): 1.0
Delta i(rad): 0.01
Eccentricity: 0.001
Argument of perigee(rad): 0.5
Delta T(s): 0.2
Delta T dot: 0.0001
GLO to UTC(s): 0.0
GPS to GLO(s): 0.0
GLO time offset(s): 0.0
"""

LEGACY_SOURCE = """Slot: 1
Frequency channel: -7
Health: 0
Reference day: 100
Reference time(s): 3600
Lambda(rad): 1.0
Delta i(rad): 0.01
Eccentricity: 0.001
Argument of perigee(rad): 0.5
Draconian period(s): 40544
Draconian period rate(s/orbit): 0.0
"""


def _scenario_root(tmp_path: Path) -> Path:
    source = Path("scenarios/orekit_design_smoke.yaml").read_text(encoding="utf-8")
    root = tmp_path / "scenarios"
    root.mkdir()
    (root / "source.yaml").write_text(source, encoding="utf-8")
    return root


def _fake_convert(self, **kwargs):  # noqa: ANN001, ANN202
    assert kwargs["slot"] == 1
    assert kwargs["frequency_channel"] == -7
    force_model = kwargs["force_model"]
    return MeanConversionResult(
        mean_orbit=MeanOrbit(
            a_m=25_510_000.0,
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
            "source_authority": "GLONASS-ALMANAC-OREKIT-ANALYTICAL",
            "almanac_source_format": "glonass-labelled-authority-v1",
            "glonass_slot": "1",
            "frequency_channel": "-7",
            "almanac_epoch": "2026-08-31T01:00:00.000Z",
            "glonass_target_epoch": kwargs["target_epoch"].isoformat(),
            "glonass_target_time_scale": kwargs["target_time_scale"].value,
            "conversion_chain": "explicit-GLONASS-almanac->Orekit-GLONASSAlmanac->Orekit-GLONASSAnalyticalPropagator@target-epoch->osculating-PV->inertial-frame->Orekit-DSST-mean",
        },
    )


def test_creates_immutable_glonass_child_with_typed_lineage(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    root = _scenario_root(tmp_path)
    monkeypatch.setattr(OrekitGlonassAlmanacMeanConversionClient, "convert", _fake_convert)
    source_before = (root / "source.yaml").read_text(encoding="utf-8")
    result = create_glonass_derived_scenario(
        root,
        GlonassCreateRequest(
            filename="glo-authority.txt",
            content_text=AUTHORITY_SOURCE,
            source_scenario_name="source.yaml",
            satellite_id="SYNTH-REF",
            slot=1,
            target_scenario_name="derived.yaml",
            new_scenario_id="derived-glonass",
        ),
    )
    assert (root / "source.yaml").read_text(encoding="utf-8") == source_before
    child = load_scenario(root / "derived.yaml")
    ref = next(item for item in child.constellation.satellites if item.satellite_id == "SYNTH-REF")
    assert ref.mean_orbit.a_m == 25_510_000.0
    assert child.digital_twin is not None and child.digital_twin.lineage is not None
    lineage = child.digital_twin.lineage
    assert lineage.transformation == "glonass_almanac_import"
    assert lineage.source_type == "glonass_authority_v1"
    assert lineage.source_record_id == "1"
    assert lineage.authority == "GLONASS-ALMANAC-OREKIT-ANALYTICAL"
    assert lineage.source_sha256 == result["source_sha256"]


def test_preview_attests_slot_and_authority(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    root = _scenario_root(tmp_path)
    monkeypatch.setattr(OrekitGlonassAlmanacMeanConversionClient, "convert", _fake_convert)
    result = preview_glonass_authority(
        root,
        GlonassAuthorityRequest(
            filename="glo-authority.txt",
            content_text=AUTHORITY_SOURCE,
            source_scenario_name="source.yaml",
            satellite_id="SYNTH-REF",
            slot=1,
        ),
    )
    assert result["slot"] == 1
    assert result["backend_metadata"]["source_authority"] == "GLONASS-ALMANAC-OREKIT-ANALYTICAL"


def test_legacy_preview_format_cannot_enter_authority_flow(tmp_path: Path) -> None:
    root = _scenario_root(tmp_path)
    with pytest.raises(ValueError) as exc_info:
        preview_glonass_authority(
            root,
            GlonassAuthorityRequest(
                filename="legacy.txt",
                content_text=LEGACY_SOURCE,
                source_scenario_name="source.yaml",
                satellite_id="SYNTH-REF",
                slot=1,
            ),
        )
    assert "GLONASS authority" in str(exc_info.value)


def test_existing_target_is_never_overwritten(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    root = _scenario_root(tmp_path)
    monkeypatch.setattr(OrekitGlonassAlmanacMeanConversionClient, "convert", _fake_convert)
    target = root / "derived.yaml"
    target.write_text("sentinel\n", encoding="utf-8")
    with pytest.raises(ValueError, match="overwrite is forbidden"):
        create_glonass_derived_scenario(
            root,
            GlonassCreateRequest(
                filename="glo-authority.txt",
                content_text=AUTHORITY_SOURCE,
                source_scenario_name="source.yaml",
                satellite_id="SYNTH-REF",
                slot=1,
                target_scenario_name="derived.yaml",
                new_scenario_id="derived-glonass",
            ),
        )
    assert target.read_text(encoding="utf-8") == "sentinel\n"
