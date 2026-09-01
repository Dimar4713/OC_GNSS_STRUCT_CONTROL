from constellation_control.preview.gravity_model_ui import gravity_model_label
from constellation_control.preview.progress_release_app import render_preview_page_for_test


def test_gravity_model_pr_gate_marker() -> None:
    assert gravity_model_label(8, 8) == "EIGEN-6S 8x8"


def test_packaged_source_contract_includes_progress_ui() -> None:
    page = render_preview_page_for_test()
    assert 'id="runProgressCard"' in page
    assert 'id="runProgressBar"' in page
    assert "/api/run-jobs" in page
    assert "epoch=${d.epoch}" in page
