from __future__ import annotations

from constellation_control.preview.consolidated_release_app import render_preview_page_for_test


def test_packaged_ui_contains_resource_state_table_and_snapshot_actions() -> None:
    page = render_preview_page_for_test()
    assert 'id="resourceStateCard"' in page
    assert '/api/resource-state/preview' in page
    assert '/api/resource-state/save' in page
    assert 'id="resourceStateRows"' in page
    assert 'resourceSnapshotName' in page
    assert 'orbital state' in page or 'орбитальной эпохи' in page
