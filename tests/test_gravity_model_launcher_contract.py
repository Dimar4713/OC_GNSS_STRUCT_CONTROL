from pathlib import Path


def test_cli_launches_gravity_enabled_preview_through_progress_wrapper() -> None:
    source = Path("src/constellation_control/cli/main.py").read_text(encoding="utf-8")
    assert "from constellation_control.preview.progress_release_app import create_preview_app" in source
    assert "wraps gravity_release_app" in source


def test_windows_launcher_uses_cli_preview() -> None:
    source = Path("preview/start-preview.ps1").read_text(encoding="utf-8")
    assert "-m constellation_control.cli.main preview" in source
