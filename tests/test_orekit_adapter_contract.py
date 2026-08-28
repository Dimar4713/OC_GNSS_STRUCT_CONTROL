from datetime import UTC, datetime
import io
import json
from typing import Any
from urllib.error import HTTPError

import pytest

from constellation_control.adapters.orekit.adapter import OrekitSidecarPropagator
from constellation_control.domain.models import (
    ForceModelConfig,
    ForceMode,
    FrameName,
    GravityModelName,
    IntegratorConfig,
    MeanElementDefinition,
    MeanOrbit,
    PropagationRequest,
    SatelliteSpec,
    SpacecraftModel,
    TimeScaleName,
)


def _request() -> PropagationRequest:
    force = ForceModelConfig(
        mode=ForceMode.DESIGN,
        gravity_model=GravityModelName.EIGEN_6S,
        mu_m3_s2=3.986004418e14,
        reference_radius_m=6378137.0,
        flattening=1.0 / 298.257223563,
        j2=0.00108262668,
        earth_rotation_rate_rad_s=7.292115e-5,
        gravity_degree=2,
        gravity_order=0,
        moon=False,
        sun=False,
        srp=False,
    )
    definition = MeanElementDefinition(
        theory="test-dsst",
        force_model_fingerprint=force.fingerprint(),
    )
    satellite = SatelliteSpec(
        satellite_id="S",
        plane_id="P",
        role="reference",
        mean_orbit=MeanOrbit(
            a_m=26_560_000.0,
            ex=0.001,
            ey=0.0,
            ix=0.2,
            iy=0.0,
            lambda_rad=0.0,
            definition=definition,
        ),
        spacecraft=SpacecraftModel(
            dry_mass_kg=500.0,
            propellant_mass_kg=50.0,
            isp_s=220.0,
            area_m2=8.0,
            cr=1.3,
        ),
    )
    return PropagationRequest(
        scenario_id="orekit-contract",
        epoch=datetime(2026, 1, 1, tzinfo=UTC),
        frame=FrameName.EME2000,
        time_scale=TimeScaleName.UTC,
        satellites=(satellite,),
        duration_s=60.0,
        output_step_s=60.0,
        force_model=force,
        integrator=IntegratorConfig(
            min_step_s=0.1,
            max_step_s=30.0,
            abs_tolerance=1e-9,
            rel_tolerance=1e-12,
        ),
        seed=4713,
    )


class _FakeResponse:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self._payload).encode()


def _result_payload(request: PropagationRequest, *, include_data_hash: bool = True) -> dict[str, Any]:
    orbit = request.satellites[0].mean_orbit.model_dump(mode="json")
    metadata = {"orekit_version": "13.1.7", "gravity_model": "EIGEN-6S"}
    if include_data_hash:
        metadata["orekit_data_sha256"] = "a" * 64
    return {
        "backend": "orekit-dsst-design",
        "backend_version": "13.1.7",
        "force_model_fingerprint": request.force_model.fingerprint(),
        "backend_metadata": metadata,
        "times_s": [0.0],
        "mean_orbits": {"S": [orbit]},
        "cartesian_states": {
            "S": [{"epoch_s": 0.0, "r_m": [1.0, 0.0, 0.0], "v_m_s": [0.0, 1.0, 0.0]}]
        },
    }


def test_adapter_sends_exact_force_model_fingerprint(monkeypatch: pytest.MonkeyPatch) -> None:
    request = _request()
    captured: dict[str, Any] = {}

    def fake_open_orekit_url(http_request: Any, timeout: float) -> _FakeResponse:
        captured["timeout"] = timeout
        captured["body"] = json.loads(http_request.data.decode())
        return _FakeResponse(_result_payload(request))

    monkeypatch.setattr(
        "constellation_control.adapters.orekit.adapter.open_orekit_url",
        fake_open_orekit_url,
    )
    result = OrekitSidecarPropagator("http://orekit.invalid", timeout_s=12.0).propagate(request)

    assert captured["timeout"] == 12.0
    assert captured["body"]["force_model_fingerprint"] == request.force_model.fingerprint()
    assert captured["body"]["force_model"]["gravity_model"] == "EIGEN-6S"
    assert result.backend_metadata["orekit_data_sha256"] == "a" * 64
    assert result.backend_metadata["gravity_model"] == "EIGEN-6S"


def test_adapter_rejects_result_without_orekit_data_fingerprint(monkeypatch: pytest.MonkeyPatch) -> None:
    request = _request()

    def fake_open_orekit_url(http_request: Any, timeout: float) -> _FakeResponse:
        del http_request, timeout
        return _FakeResponse(_result_payload(request, include_data_hash=False))

    monkeypatch.setattr(
        "constellation_control.adapters.orekit.adapter.open_orekit_url",
        fake_open_orekit_url,
    )
    with pytest.raises(RuntimeError, match="orekit-data fingerprint"):
        OrekitSidecarPropagator("http://orekit.invalid").propagate(request)


def test_adapter_exposes_sidecar_http_error_body(monkeypatch: pytest.MonkeyPatch) -> None:
    request = _request()
    response = io.BytesIO(b'{"error":"invalid_propagation_request","detail":"gravity mismatch"}')

    def fake_open_orekit_url(http_request: Any, timeout: float) -> _FakeResponse:
        del http_request, timeout
        raise HTTPError(
            "http://orekit.invalid/v1/propagate",
            422,
            "Unprocessable Entity",
            hdrs=None,
            fp=response,
        )

    monkeypatch.setattr(
        "constellation_control.adapters.orekit.adapter.open_orekit_url",
        fake_open_orekit_url,
    )
    with pytest.raises(RuntimeError, match=r"HTTP 422.*gravity mismatch"):
        OrekitSidecarPropagator("http://orekit.invalid").propagate(request)
