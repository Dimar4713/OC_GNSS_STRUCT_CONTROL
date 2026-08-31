from __future__ import annotations

import math
from pathlib import Path

import pytest
from pydantic import ValidationError

from constellation_control.adapters.orekit.mean_conversion import OsculatingKeplerianElements
from constellation_control.application.run import load_scenario
from constellation_control.application.walker import WalkerDeltaRequest, build_walker_constellation
from constellation_control.preview.osculating_input import OSCULATING_CARD
from constellation_control.preview.walker_input import WALKER_CARD


def _walker_request(**updates: object) -> WalkerDeltaRequest:
    payload: dict[str, object] = {
        "source_scenario_name": "mvp_45deg.yaml",
        "target_scenario_name": "walker-derived.yaml",
        "new_scenario_id": "walker-derived",
        "template_satellite_id": "DEMO-REF",
        "total_satellites": 4,
        "planes": 2,
        "phasing": 1,
        "semi_major_axis_m": 26_560_000.0,
        "eccentricity": 0.01,
        "inclination_deg": 64.8,
        "raan0_deg": 10.0,
        "argument_of_perigee_deg": 30.0,
        "mean_anomaly0_deg": 20.0,
    }
    payload.update(updates)
    return WalkerDeltaRequest.model_validate(payload)


def test_walker_requires_all_engineering_angles() -> None:
    payload = _walker_request().model_dump()
    for field in ("raan0_deg", "argument_of_perigee_deg", "mean_anomaly0_deg"):
        incomplete = dict(payload)
        incomplete.pop(field)
        with pytest.raises(ValidationError):
            WalkerDeltaRequest.model_validate(incomplete)


def test_walker_rejects_singular_180_degree_inclination() -> None:
    with pytest.raises(ValidationError):
        _walker_request(inclination_deg=180.0)


def test_walker_argument_of_perigee_enters_equinoctial_definition() -> None:
    source = load_scenario(Path("scenarios/mvp_45deg.yaml"))
    request = _walker_request(template_satellite_id=source.constellation.satellites[0].satellite_id)
    first = build_walker_constellation(source, request).satellites[0].mean_orbit
    longitude_of_perigee = math.radians(40.0)
    expected_lambda = math.radians(60.0)
    assert first.ex == pytest.approx(0.01 * math.cos(longitude_of_perigee))
    assert first.ey == pytest.approx(0.01 * math.sin(longitude_of_perigee))
    assert first.lambda_rad == pytest.approx(expected_lambda)


def test_osculating_anomaly_type_is_required_and_180_is_rejected() -> None:
    common = {
        "a_m": 26_560_000.0,
        "e": 0.001,
        "i_rad": math.radians(64.8),
        "pa_rad": 0.0,
        "raan_rad": 0.0,
        "anomaly_rad": 0.0,
    }
    with pytest.raises(ValidationError):
        OsculatingKeplerianElements.model_validate(common)
    with pytest.raises(ValidationError):
        OsculatingKeplerianElements.model_validate(common | {"i_rad": math.pi, "anomaly_type": "true"})


def test_packaged_ui_contains_no_hidden_orbit_defaults() -> None:
    assert 'id="oscA" type="number" step="1" value=' not in OSCULATING_CARD
    assert 'id="oscType"><option value="true"' not in OSCULATING_CARD
    assert 'id="walkerT" type="number" min="1" value=' not in WALKER_CARD
    assert 'id="walkerOmega"' in WALKER_CARD
