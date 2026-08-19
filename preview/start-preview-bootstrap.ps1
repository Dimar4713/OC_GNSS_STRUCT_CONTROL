$ErrorActionPreference = "Stop"
$PreviewDir = $PSScriptRoot
$env:OC_GNSS_PREVIEW_ROOT = (Resolve-Path (Join-Path $PreviewDir "..")).Path
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
