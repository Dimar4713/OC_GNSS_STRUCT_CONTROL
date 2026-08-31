from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from constellation_control.adapters.orekit import mean_conversion as module
from constellation_control.adapters.orekit.mean_conversion import (
    OrekitMeanConversionClient,
    OsculatingKeplerianElements,
)
from constellation_control.domain.models import (
    ForceMode,
    ForceModelConfig,
    FrameName,
    GravityModelName,
    SpacecraftModel,
    TimeScaleName,
)


class _Response:
    def __init__(self, payload: dict[str, object]) -> None:
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self._payload).encode()


def _force_model() -> ForceModelConfig:
    return ForceModelConfig(
        mode=ForceMode.DESIGN,
        gravity_model=GravityModelName.EIGEN_6S,
        mu_m3_s2=3.986004418e14,
        reference_radius_m=6378137.0,
        flattening=0.0033528106647474805,
        j2=0.00108262668,
        earth_rotation_rate_rad_s=7.2921150e-5,
        gravity_degree=2,
        gravity_order=0,
        moon=False,
        sun=False,
        srp=False,
    )


def _spacecraft() -> SpacecraftModel:
    return SpacecraftModel(
        dry_mass_kg=500.0,
        propellant_mass_kg=50.0,
        isp_s=220.0,
        area_m2=8.0,
        cr=1.3,
    )


def _elements() -> OsculatingKeplerianElements:
    return OsculatingKeplerianElements(
        a_m=26_560_000.0,
        e=0.001,
        i_rad=1.13,
        pa_rad=0.2,
        raan_rad=0.4,
        anomaly_rad=0.6,
        anomaly_type="true",
    )


def test_mean_conversion_accepts_verified_orekit_result(monkeypatch: pytest.MonkeyPatch) -> None:
    force_model = _force_model()
    fingerprint = force_model.fingerprint()
    payload = {
        "mean_orbit": {
            "a_m": 26_559_900.0,
            "ex": 0.0008,
            "ey": 0.0002,
            "ix": 0.5,
            "iy": 0.1,
            "lambda_rad": 1.2,
            "definition": {
                "representation": "equinoctial",
                "theory": "orekit-dsst-13.1.7-from-osculating",
                "force_model_fingerprint": fingerprint,
            },
        },
        "backend_metadata": {
            "backend": "orekit-dsst-mean-conversion",
            "orekit_version": "13.1.7",
            "orekit_data_sha256": "a" * 64,
            "gravity_model": "EIGEN-6S",
        },
    }
    monkeypatch.setattr(module, "open_orekit_url", lambda request, timeout_s: _Response(payload))

    result = OrekitMeanConversionClient("http://127.0.0.1:8081").convert(
        epoch=datetime(2026, 1, 1, tzinfo=UTC),
        frame=FrameName.EME2000,
        time_scale=TimeScaleName.UTC,
        elements=_elements(),
        spacecraft=_spacecraft(),
        force_model=force_model,
    )

    assert result.backend_metadata["backend"] == "orekit-dsst-mean-conversion"
    assert result.mean_orbit.definition.force_model_fingerprint == fingerprint


def test_mean_conversion_rejects_wrong_fingerprint(monkeypatch: pytest.MonkeyPatch) -> None:
    force_model = _force_model()
    payload = {
        "mean_orbit": {
            "a_m": 26_559_900.0,
            "ex": 0.0008,
            "ey": 0.0002,
            "ix": 0.5,
            "iy": 0.1,
            "lambda_rad": 1.2,
            "definition": {
                "representation": "equinoctial",
                "theory": "orekit-dsst-13.1.7-from-osculating",
                "force_model_fingerprint": "wrong",
            },
        },
        "backend_metadata": {
            "backend": "orekit-dsst-mean-conversion",
            "orekit_version": "13.1.7",
            "orekit_data_sha256": "a" * 64,
            "gravity_model": "EIGEN-6S",
        },
    }
    monkeypatch.setattr(module, "open_orekit_url", lambda request, timeout_s: _Response(payload))

    with pytest.raises(RuntimeError, match="fingerprint"):
        OrekitMeanConversionClient("http://127.0.0.1:8081").convert(
            epoch=datetime(2026, 1, 1, tzinfo=UTC),
            frame=FrameName.EME2000,
            time_scale=TimeScaleName.UTC,
            elements=_elements(),
            spacecraft=_spacecraft(),
            force_model=force_model,
        )
