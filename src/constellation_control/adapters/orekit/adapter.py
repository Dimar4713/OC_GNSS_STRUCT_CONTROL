from __future__ import annotations

import json
from urllib.request import Request, urlopen

from constellation_control.domain.models import PropagationRequest, PropagationResult


class OrekitSidecarPropagator:
    """HTTP adapter for an authoritative Java Orekit service.

    The sidecar must expose POST /v1/propagate and return the PropagationResult schema.
    There is deliberately no fallback to the screening backend.
    """

    def __init__(self, base_url: str, timeout_s: float = 300.0) -> None:
        self._url = base_url.rstrip("/") + "/v1/propagate"
        self._timeout_s = timeout_s

    def propagate(self, request: PropagationRequest) -> PropagationResult:
        body = request.model_dump_json().encode()
        http_request = Request(self._url, data=body, headers={"Content-Type": "application/json"}, method="POST")
        with urlopen(http_request, timeout=self._timeout_s) as response:  # noqa: S310
            payload = response.read().decode()
        result = PropagationResult.model_validate(json.loads(payload))
        if not result.backend.lower().startswith("orekit"):
            raise RuntimeError("high-fidelity sidecar returned a non-Orekit backend identity")
        if result.force_model_fingerprint != request.force_model.fingerprint():
            raise RuntimeError("Orekit result force-model fingerprint does not match request")
        return result
