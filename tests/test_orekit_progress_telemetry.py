from __future__ import annotations

from constellation_control.adapters.orekit.adapter import (
    OrekitSidecarPropagator,
    _preview_progress_payload,
    _progress_signature,
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


def test_liveness_signature_ignores_repeated_poll_timestamp_but_tracks_real_work() -> None:
    base = {
        "state": "running",
        "phase": "numerical_propagation",
        "satellite_id": "GLO-LIN-DEP",
        "satellite_index": 2,
        "point_index": 772091,
        "time_s": 23_162_700.0,
        "epoch": "2020-09-25T02:05:00.000Z",
        "updated_at": "2026-09-03T08:00:00Z",
    }
    repeated = {**base, "updated_at": "2026-09-03T08:00:01Z"}
    advanced = {
        **base,
        "point_index": 772092,
        "time_s": 23_162_730.0,
        "epoch": "2020-09-25T02:05:30.000Z",
    }

    assert _progress_signature(base) == _progress_signature(repeated)
    assert _progress_signature(base) != _progress_signature(advanced)


def test_default_watchdog_is_stall_based_not_total_runtime_based() -> None:
    adapter = OrekitSidecarPropagator("http://orekit.invalid")

    assert adapter._timeout_s is None
    assert adapter._progress_startup_grace_s == 60.0
    assert adapter._progress_stall_timeout_s == 600.0
