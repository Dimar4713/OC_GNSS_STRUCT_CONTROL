from __future__ import annotations

import json
from datetime import datetime
from math import pi
from typing import Literal
from urllib.error import HTTPError, URLError
from urllib.request import Request

from pydantic import BaseModel, ConfigDict, Field

from constellation_control.adapters.orekit.http import open_orekit_url
from constellation_control.domain.models import (
    ForceModelConfig,
    FrameName,
    MeanOrbit,
    SpacecraftModel,
    TimeScaleName,
)


class OsculatingKeplerianElements(BaseModel):
    model_config = ConfigDict(frozen=True)

    a_m: float = Field(gt=0.0)
    e: float = Field(ge=0.0, lt=1.0)
    i_rad: float = Field(ge=0.0, lt=pi)
    pa_rad: float
    raan_rad: float
    anomaly_rad: float
    anomaly_type: Literal["mean", "eccentric", "true"]


class MeanConversionResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    mean_orbit: MeanOrbit
    backend_metadata: dict[str, str]


def _post_conversion(url: str, payload: dict[str, object], timeout_s: float, label: str) -> MeanConversionResult:
    body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    request = Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with open_orekit_url(request, timeout_s) as response:
            raw = response.read().decode()
    except HTTPError as error:
        detail = error.read().decode(errors="replace")
        raise RuntimeError(f"Orekit {label} HTTP {error.code}: {detail}") from error
    except URLError as error:
        raise RuntimeError(f"Orekit {label} connection failed: {error.reason}") from error
    except TimeoutError as error:
        raise RuntimeError(f"Orekit {label} exceeded {timeout_s:.0f} s") from error
    return MeanConversionResult.model_validate(json.loads(raw))


def _verify_common_result(
    result: MeanConversionResult,
    *,
    requested_gravity: str,
    fingerprint: str,
) -> None:
    metadata = result.backend_metadata
    if metadata.get("backend") != "orekit-dsst-mean-conversion":
        raise RuntimeError("mean conversion returned unexpected backend identity")
    if metadata.get("gravity_model") != requested_gravity:
        raise RuntimeError("mean conversion gravity authority does not match request")
    if not metadata.get("orekit_version"):
        raise RuntimeError("mean conversion omitted Orekit version")
    if not metadata.get("orekit_data_sha256"):
        raise RuntimeError("mean conversion omitted Orekit-data fingerprint")
    definition = result.mean_orbit.definition
    if definition.force_model_fingerprint != fingerprint:
        raise RuntimeError("mean conversion force-model fingerprint does not match request")
    if not definition.theory.startswith("orekit-dsst-"):
        raise RuntimeError("mean conversion returned an unrecognized mean-element definition")


class OrekitMeanConversionClient:
    """Convert Keplerian osculating elements to canonical mean elements via Orekit DSST.

    This is an authority boundary. There is deliberately no local mathematical
    fallback: if the sidecar is unavailable or its identity/provenance cannot be
    verified, conversion fails closed.
    """

    def __init__(self, base_url: str, timeout_s: float = 60.0) -> None:
        self._url = base_url.rstrip("/") + "/v1/orbits/osculating-to-mean"
        self._timeout_s = timeout_s

    def convert(
        self,
        *,
        epoch: datetime,
        frame: FrameName,
        time_scale: TimeScaleName,
        elements: OsculatingKeplerianElements,
        spacecraft: SpacecraftModel,
        force_model: ForceModelConfig,
    ) -> MeanConversionResult:
        requested_gravity = force_model.gravity_model
        if requested_gravity is None:
            raise RuntimeError("osculating-to-mean conversion requires explicit gravity authority")
        fingerprint = force_model.fingerprint()
        payload = {
            "epoch": epoch.isoformat().replace("+00:00", "Z"),
            "frame": frame.value,
            "time_scale": time_scale.value,
            **elements.model_dump(mode="json"),
            "spacecraft": spacecraft.model_dump(mode="json"),
            "force_model": force_model.model_dump(mode="json"),
            "force_model_fingerprint": fingerprint,
        }
        result = _post_conversion(self._url, payload, self._timeout_s, "mean conversion")
        _verify_common_result(
            result,
            requested_gravity=requested_gravity.value,
            fingerprint=fingerprint,
        )
        return result


class OrekitTleMeanConversionClient:
    """Convert raw TLE through Orekit SGP4/TEME and DSST mean authority.

    Raw NORAD mean elements are never reinterpreted locally. The sidecar must
    explicitly attest the SGP4/TEME conversion chain and the returned canonical
    mean definition must match the requested force-model fingerprint.
    """

    def __init__(self, base_url: str, timeout_s: float = 60.0) -> None:
        self._url = base_url.rstrip("/") + "/v1/orbits/tle-to-mean"
        self._timeout_s = timeout_s

    def convert(
        self,
        *,
        line1: str,
        line2: str,
        frame: FrameName,
        spacecraft: SpacecraftModel,
        force_model: ForceModelConfig,
    ) -> MeanConversionResult:
        requested_gravity = force_model.gravity_model
        if requested_gravity is None:
            raise RuntimeError("TLE-to-mean conversion requires explicit gravity authority")
        fingerprint = force_model.fingerprint()
        payload = {
            "line1": line1,
            "line2": line2,
            "frame": frame.value,
            "spacecraft": spacecraft.model_dump(mode="json"),
            "force_model": force_model.model_dump(mode="json"),
            "force_model_fingerprint": fingerprint,
        }
        result = _post_conversion(self._url, payload, self._timeout_s, "TLE conversion")
        _verify_common_result(
            result,
            requested_gravity=requested_gravity.value,
            fingerprint=fingerprint,
        )
        metadata = result.backend_metadata
        if metadata.get("source_authority") != "NORAD-TLE-SGP4":
            raise RuntimeError("TLE conversion returned unexpected source authority")
        if metadata.get("sgp4_frame") != "TEME":
            raise RuntimeError("TLE conversion did not attest TEME SGP4 authority")
        chain = metadata.get("conversion_chain", "")
        if "TLE->Orekit-SGP4/TEME" not in chain or "Orekit-DSST-mean" not in chain:
            raise RuntimeError("TLE conversion omitted the reviewed authority chain")
        if not metadata.get("norad_satellite_number"):
            raise RuntimeError("TLE conversion omitted NORAD satellite number")
        if not metadata.get("sgp4_epoch"):
            raise RuntimeError("TLE conversion omitted SGP4 epoch")
        return result
