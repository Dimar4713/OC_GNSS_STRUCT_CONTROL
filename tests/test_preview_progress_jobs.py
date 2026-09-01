from __future__ import annotations

from time import monotonic, sleep

from constellation_control.preview.progress_jobs import PreviewRunJobManager


def _wait_terminal(manager: PreviewRunJobManager, job_id: str, timeout_s: float = 2.0):
    deadline = monotonic() + timeout_s
    seen = []
    while monotonic() < deadline:
        snapshot = manager.get(job_id)
        assert snapshot is not None
        seen.append(snapshot)
        if snapshot.state in {"completed", "failed"}:
            return seen
        sleep(0.01)
    raise AssertionError("job did not reach terminal state")


def test_progress_is_monotonic_and_exactly_100_on_completion() -> None:
    manager = PreviewRunJobManager()

    def worker(update):
        update(phase="propagation", percent=20.0, point_index=2, point_total=10)
        update(phase="post_processing", percent=80.0, point_index=10, point_total=10)
        return {"ok": True}

    started = manager.start(
        scenario_name="case.yaml",
        duration_s=100.0,
        output_step_s=10.0,
        worker=worker,
    )
    seen = _wait_terminal(manager, started.job_id)
    percentages = [item.percent for item in seen]
    assert percentages == sorted(percentages)
    terminal = seen[-1]
    assert terminal.state == "completed"
    assert terminal.phase == "completed"
    assert terminal.percent == 100.0
    assert terminal.result == {"ok": True}


def test_failure_retains_last_known_progress_and_error() -> None:
    manager = PreviewRunJobManager()

    def worker(update):
        update(
            phase="osculating_to_mean",
            percent=42.0,
            satellite_id="GLO-17",
            satellite_index=17,
            satellite_total=30,
            time_s=4104000.0,
            point_index=4561,
            point_total=35041,
            epoch="2027-02-17T12:00:00Z",
        )
        raise RuntimeError("unable to compute DSST mean parameters after 201 iterations")

    started = manager.start(
        scenario_name="annual.yaml",
        duration_s=31536000.0,
        output_step_s=900.0,
        worker=worker,
    )
    terminal = _wait_terminal(manager, started.job_id)[-1]
    assert terminal.state == "failed"
    assert terminal.phase == "osculating_to_mean"
    assert terminal.percent == 42.0
    assert terminal.satellite_id == "GLO-17"
    assert terminal.satellite_index == 17
    assert terminal.satellite_total == 30
    assert terminal.time_s == 4104000.0
    assert terminal.epoch == "2027-02-17T12:00:00Z"
    assert terminal.point_index == 4561
    assert terminal.point_total == 35041
    assert "201 iterations" in (terminal.error or "")


def test_duplicate_active_start_returns_same_job() -> None:
    manager = PreviewRunJobManager()

    def worker(update):
        sleep(0.08)
        return {"ok": True}

    first = manager.start(
        scenario_name="case.yaml",
        duration_s=100.0,
        output_step_s=10.0,
        worker=worker,
    )
    second = manager.start(
        scenario_name="case.yaml",
        duration_s=100.0,
        output_step_s=10.0,
        worker=worker,
    )
    assert second.job_id == first.job_id
