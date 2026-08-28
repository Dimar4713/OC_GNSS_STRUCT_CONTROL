from pathlib import Path


def test_windows_bootstrap_exports_bundled_orekit_revision_before_launcher() -> None:
    text = Path("preview/start-preview-bootstrap.ps1").read_text(encoding="utf-8")

    authority = '$RevisionAuthorityPath = Join-Path $env:OC_GNSS_PREVIEW_ROOT "sidecar\\orekit-service\\orekit-data-revision.txt"'
    export = "$env:OREKIT_DATA_REVISION = $BundledRevision"
    execute = "& $ScriptBlock @args"

    assert authority in text
    assert export in text
    assert execute in text
    assert text.index(authority) < text.index(export) < text.index(execute)
    assert "^[0-9a-f]{40}$" in text
    assert "Do not rely on" in text
