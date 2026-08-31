from __future__ import annotations

from constellation_control.preview.consolidated_release_app import render_preview_page_for_test


def test_packaged_ui_contains_spacecraft_systems_catalog_validator() -> None:
    page = render_preview_page_for_test()
    assert 'id="spacecraftCatalogCard"' in page
    assert '/api/spacecraft-catalog/validate' in page
    assert 'spacecraftCatalogFile' in page
    assert 'масса, топливо и Isp' in page
