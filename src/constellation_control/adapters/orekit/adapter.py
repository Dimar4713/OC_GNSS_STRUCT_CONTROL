from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from threading import Event, Thread
from time import monotonic
from urllib.error import HTTPError, URLError
from urllib.request import Request
from uuid import uuid4

from constellation_control.adapters.orekit.http import open_orekit_url
from constellation_control.domain.models import PropagationRequest, PropagationResult

ProgressCallback = Callable[[dict[str, object]], None]
_PROGRESS_CALLBACK: ContextVar[ProgressCallback | None] = ContextVar("orekit_progress_callback", default=None)


@contextmanager
def orekit_progress_callback(callback: ProgressCallback | None) -> Iterator[None]:
    token = _PROGRESS_CALLBACK.set(callback)
    try:
        yield
    finally:
        _PROGRESS_CALLBACK.reset(token)


class OrekitSidecarPropagator:
    """HTTP adapter for the authoritative Java Orekit service.

    The sidecar exposes POST /v1/propagate. High-fidelity execution fails closed:
    backend identity, force-model fingerprint, gravity authority, Orekit version
    and orekit-data fingerprint are all validated before a result enters
    application code.

    Authoritative propagation has no arbitrary total wall-clock deadline by
    default. Every authoritative run receives a telemetry id and a liveness
    watchdog requires real movement in the physical work coordinates. Repeated
    copies of one snapshot do not count as progress. A separate startup grace
    period detects a sidecar that accepted the request but never starts reporting
    work. UI callbacks are optional and only control display, not watchdog safety.

    Callers may still pass an explicit finite transport timeout when their
    workflow genuinely requires one. Short progress-poll requests remain bounded
    independently.
    """

    def __init__(
        self,
        base_url: str,
        timeout_s: float | None = None,
        progress_callback: ProgressCallback | None = None,
        progress_stall_timeout_s: float = 600.0,
        progress_startup_grace_s: float = 60.0,
    ) -> None:
        root = base_url.rstrip("/")
        self._url = root + "/v1/propagate"
        self._progress_root = root + "/v1/progress"
        self._timeout_s = timeout_s
        self._progress_callback = progress_callback if progress_callback is not None else _PROGRESS_CALLBACK.get()
        self._progress_stall_timeout_s = progress_stall_timeout_s
        self._progress_startup_grace_s = progress_startup_grace_s

    def propagate(self, request: PropagationRequest) -> PropagationResult:
        request_payload = request.model_dump(mode="json")
        request_payload["force_model_fingerprint"] = request.force_model.fingerprint()
        body = json.dumps(request_payload, sort_keys=True, separators=(",", ":")).encode()
        telemetry_id = uuid4().hex
        headers = {
            "Content-Type": "application/json",
            "X-OC-GNSS-Progress-Id": telemetry_id,
        }

        http_request = Request(self._url, data=body, headers=headers, method="POST")
        payload = self._request_with_liveness_watchdog(http_request, telemetry_id)
        self._emit_final_progress(telemetry_id)
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

    def _request_with_liveness_watchdog(self, http_request: Request, telemetry_id: str) -> str:
        completed = Event()
        outcome: dict[str, object] = {}

        def worker() -> None:
            try:
                outcome["payload"] = self._read_propagation_response(http_request)
            except BaseException as error:  # noqa: BLE001 - re-raised on caller thread
                outcome["error"] = error
            finally:
                completed.set()

        worker_thread = Thread(
            target=worker,
            name=f"orekit-request-{telemetry_id[:8]}",
            daemon=True,
        )
        worker_thread.start()

        started_at = monotonic()
        last_movement_at = started_at
        last_signature: tuple[object, ...] | None = None
        telemetry_seen = False

        while not completed.wait(0.25):
            snapshot = self._read_progress(telemetry_id)
            if snapshot is not None:
                self._emit_progress(snapshot)
                signature = _progress_signature(snapshot)
                if signature != last_signature:
                    telemetry_seen = True
                    last_signature = signature
                    last_movement_at = monotonic()

            now = monotonic()
            if not telemetry_seen and now - started_at > self._progress_startup_grace_s:
                raise RuntimeError(
                    "Orekit sidecar liveness watchdog: no authoritative progress telemetry "
                    f"for {self._progress_startup_grace_s:.0f} s after request start"
                )
            if telemetry_seen and now - last_movement_at > self._progress_stall_timeout_s:
                raise RuntimeError(
                    "Orekit sidecar liveness watchdog: authoritative progress stopped changing "
                    f"for {self._progress_stall_timeout_s:.0f} s"
                )

        worker_thread.join(timeout=1.0)
        error = outcome.get("error")
        if isinstance(error, BaseException):
            raise error
        payload = outcome.get("payload")
        if not isinstance(payload, str):
            raise RuntimeError("Orekit sidecar returned no propagation payload")
        return payload

    def _read_propagation_response(self, http_request: Request) -> str:
        try:
            with open_orekit_url(http_request, self._timeout_s) as response:
                return response.read().decode()
        except HTTPError as error:
            detail = error.read().decode(errors="replace")
            raise RuntimeError(f"Orekit sidecar HTTP {error.code}: {detail}") from error
        except URLError as error:
            raise RuntimeError(f"Orekit sidecar connection failed: {error.reason}") from error
        except TimeoutError as error:
            if self._timeout_s is None:
                raise RuntimeError("Orekit sidecar transport timed out unexpectedly") from error
            raise RuntimeError(
                f"Orekit sidecar propagation exceeded configured deadline {self._timeout_s:.0f} s"
            ) from error

    def _emit_final_progress(self, telemetry_id: str | None) -> None:
        if telemetry_id is None:
            return
        snapshot = self._read_progress(telemetry_id)
        if snapshot is not None:
            self._emit_progress(snapshot)

    def _read_progress(self, telemetry_id: str) -> dict[str, object] | None:
        request = Request(f"{self._progress_root}/{telemetry_id}", method="GET")
        try:
            with open_orekit_url(request, 5.0) as response:
                payload = json.loads(response.read().decode())
        except HTTPError as error:
            if error.code == 404:
                return None
            return None
        except (URLError, TimeoutError, json.JSONDecodeError):
            return None
        return payload if isinstance(payload, dict) else None

    def _emit_progress(self, snapshot: dict[str, object]) -> None:
        callback = self._progress_callback
        if callback is None:
            return
        try:
            callback(_preview_progress_payload(snapshot))
        except Exception:  # noqa: BLE001 - telemetry must never change numerical authority
            return


def _progress_signature(snapshot: dict[str, object]) -> tuple[object, ...]:
    """Return physical work coordinates whose change proves calculation liveness."""
    return (
        snapshot.get("state"),
        snapshot.get("phase"),
        snapshot.get("satellite_id"),
        snapshot.get("satellite_index"),
        snapshot.get("point_index"),
        snapshot.get("time_s"),
        snapshot.get("epoch"),
        snapshot.get("error"),
    )


def _preview_progress_payload(snapshot: dict[str, object]) -> dict[str, object]:
    phase = str(snapshot.get("phase") or "propagation")
    satellite_index = _optional_int(snapshot.get("satellite_index"))
    satellite_total = _optional_int(snapshot.get("satellite_total"))
    point_index = _optional_int(snapshot.get("point_index"))
    point_total = _optional_int(snapshot.get("point_total"))
    percent = 1.0
    if (
        satellite_index is not None
        and satellite_total is not None
        and point_index is not None
        and point_total is not None
        and satellite_total > 0
        and point_total > 0
    ):
        second_phase = phase in {"osculating_to_mean", "mean_to_osculating"}
        entered_units = ((satellite_index - 1) * point_total + (point_index - 1)) * 2 + (2 if second_phase else 1)
        total_units = satellite_total * point_total * 2
        percent = min(94.0, 1.0 + 93.0 * entered_units / total_units)

    payload: dict[str, object] = {
        "phase": phase,
        "percent": percent,
        "satellite_index": satellite_index,
        "satellite_total": satellite_total,
        "point_index": point_index,
        "point_total": point_total,
        "message": f"Orekit {phase}",
    }
    for key in ("satellite_id", "time_s", "epoch", "error"):
        value = snapshot.get(key)
        if value is not None:
            payload[key] = value
    return payload


def _optional_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    return None
