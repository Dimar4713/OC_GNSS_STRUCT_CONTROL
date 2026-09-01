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
