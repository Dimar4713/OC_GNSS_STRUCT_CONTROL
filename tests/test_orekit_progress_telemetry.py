from __future__ import annotations

from constellation_control.adapters.orekit.adapter import (
    OrekitSidecarPropagator,
    _preview_progress_payload,
    orekit_progress_callback,
)


def test_progress_percent_comes_from_real_work_units() -> None:
    first = _preview_progress_payload(
        {
            "phase": "numerical_propagation",
            "satellite_id": "GLO-17",
            "satellite_index": 17,
            "satellite_total": 30,
            "point_index": 4561,
            "point_total": 35041,
            "time_s": 4_104_000.0,
            "epoch": "2027-02-17T12:00:00Z",
        }
    )
    second = _preview_progress_payload(
        {
            "phase": "osculating_to_mean",
            "satellite_id": "GLO-17",
            "satellite_index": 17,
            "satellite_total": 30,
            "point_index": 4561,
            "point_total": 35041,
            "time_s": 4_104_000.0,
            "epoch": "2027-02-17T12:00:00Z",
        }
    )

    assert first["satellite_id"] == "GLO-17"
    assert first["point_index"] == 4561
    assert first["time_s"] == 4_104_000.0
    assert float(second["percent"]) > float(first["percent"])
    assert float(second["percent"]) < 95.0


def test_progress_callback_context_is_scoped_to_current_execution() -> None:
    updates: list[dict[str, object]] = []

    outside = OrekitSidecarPropagator("http://orekit.invalid")
    assert outside._progress_callback is None

    with orekit_progress_callback(updates.append):
        inside = OrekitSidecarPropagator("http://orekit.invalid")
        assert inside._progress_callback is not None
        inside._progress_callback({"phase": "numerical_propagation"})

    assert updates == [{"phase": "numerical_propagation"}]
    after = OrekitSidecarPropagator("http://orekit.invalid")
    assert after._progress_callback is None


def test_failed_sidecar_snapshot_preserves_exact_phase_and_error() -> None:
    payload = _preview_progress_payload(
        {
            "state": "failed",
            "phase": "osculating_to_mean",
            "satellite_id": "GLO-17",
            "satellite_index": 17,
            "satellite_total": 30,
            "point_index": 4561,
            "point_total": 35041,
            "time_s": 4_104_000.0,
            "epoch": "2027-02-17T12:00:00Z",
            "error": "unable to compute mean state after 201 iterations",
        }
    )

    assert payload["phase"] == "osculating_to_mean"
    assert payload["satellite_id"] == "GLO-17"
    assert payload["point_index"] == 4561
    assert payload["error"] == "unable to compute mean state after 201 iterations"
