from __future__ import annotations

import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from constellation_control.domain.models import PropagationRequest, PropagationResult


class OrekitSidecarPropagator:
    """HTTP adapter for the authoritative Java Orekit service.

    The sidecar exposes POST /v1/propagate. High-fidelity execution fails closed:
    backend identity, force-model fingerprint, gravity authority, Orekit version
    and Orekit-data fingerprint are all validated before a result enters
    application code.
    """

    def __init__(self, base_url: str, timeout_s: float = 300.0) -> None:
        self._url = base_url.rstrip("/") + "/v1/propagate"
        self._timeout_s = timeout_s

    def propagate(self, request: PropagationRequest) -> PropagationResult:
        request_payload = request.model_dump(mode="json")
        request_payload["force_model_fingerprint"] = request.force_model.fingerprint()
        body = json.dumps(request_payload, sort_keys=True, separators=(",", ":")).encode()
        http_request = Request(self._url, data=body, headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urlopen(http_request, timeout=self._timeout_s) as response:  # noqa: S310
                payload = response.read().decode()
        except HTTPError as error:
            detail = error.read().decode(errors="replace")
            raise RuntimeError(f"Orekit sidecar HTTP {error.code}: {detail}") from error
        except URLError as error:
            raise RuntimeError(f"Orekit sidecar connection failed: {error.reason}") from error

        result = PropagationResult.model_validate(json.loads(payload))
        if not result.backend.lower().startswith("orekit"):
            raise RuntimeError("high-fidelity sidecar returned a non-Orekit backend identity")
        if result.force_model_fingerprint != request.force_model.fingerprint():
            raise RuntimeError("Orekit result force-model fingerprint does not match request")
        if not result.backend_version:
            raise RuntimeError("Orekit result omitted backend version")
        if not result.backend_metadata.get("orekit_data_sha256"):
            raise RuntimeError("Orekit result omitted orekit-data fingerprint")

        requested_gravity = request.force_model.gravity_model
        if requested_gravity is None:
            raise RuntimeError("high-fidelity Orekit request omitted explicit gravity authority")
        actual_gravity = result.backend_metadata.get("gravity_model")
        if actual_gravity != requested_gravity.value:
            raise RuntimeError(
                "Orekit result gravity authority does not match request: "
                f"requested={requested_gravity.value} actual={actual_gravity}"
            )
        return result
