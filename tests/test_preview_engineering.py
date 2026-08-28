import math

import pytest

from constellation_control.domain.models import (
    MeanElementDefinition,
    MeanOrbit,
    SatelliteSpec,
    SpacecraftModel,
)
from constellation_control.preview.engineering import (
    constellation_geometry_preflight,
    mean_orbit_engineering_elements,
)

MU = 398600441800000.0
DEFINITION = MeanElementDefinition(
    theory="engineer-feedback-regression",
    force_model_fingerprint="test",
)
SPACECRAFT = SpacecraftModel(
    dry_mass_kg=500.0,
    propellant_mass_kg=50.0,
    isp_s=220.0,
    area_m2=8.0,
    cr=1.3,
)


def _satellite(
    satellite_id: str,
    plane_id: str,
    ix: float,
    iy: float,
    lambda_rad: float,
) -> SatelliteSpec:
    return SatelliteSpec(
        satellite_id=satellite_id,
        plane_id=plane_id,
        role="reference",
        mean_orbit=MeanOrbit(
            a_m=25508039.165499,
            ex=0.0,
            ey=0.0,
            ix=ix,
            iy=iy,
            lambda_rad=lambda_rad,
            definition=DEFINITION,
        ),
        spacecraft=SPACECRAFT,
    )


def test_engineering_elements_recover_period_inclination_raan_and_mean_phase() -> None:
    satellite = _satellite(
        "GLO-01",
        "GLO-P1",
        -0.6128512204797385,
        -0.16478784655405554,
        2.8463677578328666,
    )

    derived = mean_orbit_engineering_elements(satellite.mean_orbit, MU)

    assert derived["period_s"] == pytest.approx(40544.0, abs=1.0)
    assert derived["period_h"] == pytest.approx(11.2622, abs=1e-3)
    assert derived["inclination_deg"] == pytest.approx(64.8, abs=1e-10)
    assert derived["raan_deg"] == pytest.approx(195.0501317627, abs=1e-9)
    assert derived["u_mean_deg"] == pytest.approx(328.0347277032, abs=1e-9)


def test_engineer_feedback_interplane_phasing_is_15_and_30_degrees_after_raan_removal() -> None:
    # These three mean-equinoctial states are copied from the engineer feedback package.
    # The test records the interpretation error that motivated #22: comparing lambda
    # directly mixes the orbital-plane RAAN offset into the in-plane phase.
    satellites = [
        _satellite(
            "GLO-01",
            "GLO-P1",
            -0.6128512204797385,
            -0.16478784655405554,
            2.8463677578328666,
        ),
        _satellite(
            "GLO-09",
            "GLO-P2",
            0.44912582134044515,
            -0.44836107036706313,
            -1.080646437586683,
        ),
        _satellite(
            "GLO-17",
            "GLO-P3",
            0.1637436308408136,
            0.6131310432317837,
            1.275525494613504,
        ),
    ]

    report = constellation_geometry_preflight(satellites, MU)
    planes = {plane["plane_id"]: plane for plane in report["planes"]}
    offsets = {item["plane_id"]: item for item in report["interplane"]}

    assert planes["GLO-P1"]["raan_mean_deg"] == pytest.approx(195.0501317627, abs=1e-9)
    assert planes["GLO-P2"]["raan_mean_deg"] == pytest.approx(315.0488218747, abs=1e-9)
    assert planes["GLO-P3"]["raan_mean_deg"] == pytest.approx(75.0474702020, abs=1e-9)

    assert offsets["GLO-P2"]["raan_offset_deg"] == pytest.approx(119.9986901120, abs=1e-9)
    assert offsets["GLO-P3"]["raan_offset_deg"] == pytest.approx(239.9973384393, abs=1e-9)
    assert offsets["GLO-P2"]["phase_offset_mod_slot_deg"] == pytest.approx(14.9999704025, abs=1e-9)
    assert offsets["GLO-P3"]["phase_offset_mod_slot_deg"] == pytest.approx(30.0000295975, abs=1e-9)

    # Direct lambda comparison is intentionally not the engineering phase comparison.
    direct_lambda_delta_deg = math.degrees(
        satellites[1].mean_orbit.lambda_rad - satellites[0].mean_orbit.lambda_rad
    ) % 360.0
    assert direct_lambda_delta_deg == pytest.approx(134.9986605145, abs=1e-9)


def test_engineer_feedback_plane_one_keeps_eight_slots_at_45_degrees() -> None:
    lambdas = [
        2.8463677578328666,
        2.0609695944354183,
        1.27557143103797,
        0.4901732676405217,
        -0.29522489575692656,
        -1.0806230591543748,
        -1.8660212225518231,
        -2.6514193859492714,
    ]
    satellites = [
        _satellite(
            f"GLO-{index:02d}",
            "GLO-P1",
            -0.6128512204797385,
            -0.16478784655405554,
            lambda_rad,
        )
        for index, lambda_rad in enumerate(lambdas, start=1)
    ]

    report = constellation_geometry_preflight(satellites, MU)
    plane = report["planes"][0]

    assert plane["satellite_count"] == 8
    assert plane["in_plane_spacing_mean_deg"] == pytest.approx(45.0, abs=1e-12)
    assert all(spacing == pytest.approx(45.0, abs=5e-3) for spacing in plane["in_plane_spacing_deg"])
    assert "not an osculating argument of latitude" in report["semantics_en"]
