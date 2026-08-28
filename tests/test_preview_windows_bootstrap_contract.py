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


def test_real_windows_launcher_reasserts_authority_and_clears_only_stale_orekit() -> None:
    text = Path("preview/start-preview.ps1").read_text(encoding="utf-8")

    assert "Engineering Preview Python 0.2.3" in text
    assert "$env:OREKIT_DATA_REVISION = $PinnedRevision" in text
    assert "Clear-StaleOrekitListener 8081" in text
    assert "Get-NetTCPConnection" in text
    assert "Get-CimInstance Win32_Process" in text
    assert "orekit-service(?:-0\\.1\\.0-SNAPSHOT)?\\.jar" in text
    assert "Preview will not terminate an unrelated process" in text
    assert '$Health.orekit_version -eq "13.1.7"' in text
    assert "$Health.orekit_data_revision -eq $PinnedRevision" in text
    assert "$Health.orekit_data_sha256 -eq $PinnedPhysicalSha" in text
    assert "$Attempt -lt 60" in text
    assert "stderr: $StderrTail" in text
