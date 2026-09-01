from pathlib import Path

from constellation_control.application.run_duration import DurationRunResult
from constellation_control.preview import progress_release_app
from constellation_control.preview.progress_release_app import render_preview_page_for_test


def test_progress_ui_replaces_blocking_run_with_job_polling() -> None:
    page = render_preview_page_for_test()
    assert 'id="runProgressCard"' in page
    assert 'id="runProgressBar"' in page
    assert "fetch('/api/run-jobs'" in page
    assert "fetch('/api/run-jobs/'+encodeURIComponent(activeRunJobId))" in page
    assert "runScenario=async function()" in page
    assert "point ${d.point_index}/${d.point_total}" in page
    assert "${Number(d.percent||0).toFixed(1)} %" in page


def test_progress_ui_exposes_independent_kepler_drift_report_link() -> None:
    page = render_preview_page_for_test()
    assert 'id="keplerDriftReport"' in page
    assert "x.artifacts.kepler_drift_consistency" in page
    assert "drift.href=x.artifacts.kepler_drift_consistency" in page
    assert "Kepler ↔ Orekit drift consistency" in page


def test_result_payload_only_exposes_existing_kepler_drift_report(tmp_path: Path, monkeypatch) -> None:
    output_root = tmp_path / "runs"
    run_dir = output_root / "scenario-a" / "run-1"
    run_dir.mkdir(parents=True)
    execution = DurationRunResult(
        run_dir=run_dir,
        duration_s=86400.0,
        output_step_s=900.0,
        predicted_sample_count=97,
        preset="scenario",
    )
    monkeypatch.setattr(progress_release_app, "preview_operations_payload", lambda _: {})

    without_report = progress_release_app._result_payload(output_root, execution)
    assert "kepler_drift_consistency" not in without_report["artifacts"]

    (run_dir / "kepler_drift_consistency.html").write_text("<html>evidence</html>", encoding="utf-8")
    with_report = progress_release_app._result_payload(output_root, execution)
    assert with_report["artifacts"]["kepler_drift_consistency"] == (
        "/api/results/scenario-a/run-1/kepler_drift_consistency.html"
    )
