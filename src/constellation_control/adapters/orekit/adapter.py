from __future__ import annotations

import json
from urllib.request import Request, urlopen

from constellation_control.domain.models import PropagationRequest, PropagationResult


class OrekitSidecarPropagator:
    """HTTP adapter for the authoritative Java Orekit service.

    The sidecar exposes POST /v1/propagate. High-fidelity execution fails closed:
    backend identity, force-model fingerprint, Orekit version and Orekit-data
    fingerprint are all validated before a result enters application code.
    """

    def __init__(self, base_url: str, timeout_s: float = 300.0) -> None:
        self._url = base_url.rstrip("/") + "/v1/propagate"
        self._timeout_s = timeout_s

    def propagate(self, request: PropagationRequest) -> PropagationResult:
        request_payload = request.model_dump(mode="json")
        request_payload["force_model_fingerprint"] = request.force_model.fingerprint()
        body = json.dumps(request_payload, sort_keys=True, separators=(",", ":")).encode()
        http_request = Request(self._url, data=body, headers={"Content-Type": "application/json"}, method="POST")
        with urlopen(http_request, timeout=self._timeout_s) as response:  # noqa: S310
            payload = response.read().decode()
        result = PropagationResult.model_validate(json.loads(payload))
        if not result.backend.lower().startswith("orekit"):
            raise RuntimeError("high-fidelity sidecar returned a non-Orekit backend identity")
        if result.force_model_fingerprint != request.force_model.fingerprint():
            raise RuntimeError("Orekit result force-model fingerprint does not match request")
        if not result.backend_version:
            raise RuntimeError("Orekit result omitted backend version")
        if not result.backend_metadata.get("orekit_data_sha256"):
            raise RuntimeError("Orekit result omitted orekit-data fingerprint")
        return result
