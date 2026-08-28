$ErrorActionPreference = "Stop"
$PreviewDir = $PSScriptRoot
$env:OC_GNSS_PREVIEW_ROOT = (Resolve-Path (Join-Path $PreviewDir "..")).Path

# Clean-PC authority contract: the bundled reviewed Orekit-data revision is the
# only revision the sidecar may report for this Preview package. Do not rely on
# a developer/CI machine having OREKIT_DATA_REVISION pre-populated.
$RevisionAuthorityPath = Join-Path $env:OC_GNSS_PREVIEW_ROOT "sidecar\orekit-service\orekit-data-revision.txt"
if (-not (Test-Path -LiteralPath $RevisionAuthorityPath -PathType Leaf)) {
  throw "Missing bundled Orekit revision authority: $RevisionAuthorityPath"
}
$BundledRevision = (Get-Content -LiteralPath $RevisionAuthorityPath -Raw).Trim()
if ($BundledRevision -notmatch '^[0-9a-f]{40}$') {
  throw "Invalid bundled Orekit revision authority: $BundledRevision"
}
$env:OREKIT_DATA_REVISION = $BundledRevision

$ScriptPath = Join-Path $PreviewDir "start-preview.ps1"
$ScriptText = [System.IO.File]::ReadAllText($ScriptPath, [System.Text.Encoding]::UTF8)

# Windows PowerShell 5.1 can turn native stderr from `java -version` into a
# terminating NativeCommandError under ErrorActionPreference=Stop. Capture
# Java version through cmd.exe so a healthy bundled JRE is not rejected.
$ScriptText = $ScriptText.Replace(
  '$JavaVersionText = (& java -version 2>&1 | Select-Object -First 1)',
  '$JavaVersionText = (& cmd.exe /d /c "java -version 2>&1" | Select-Object -First 1)'
)

$ScriptBlock = [ScriptBlock]::Create($ScriptText)
& $ScriptBlock @args
exit $LASTEXITCODE
