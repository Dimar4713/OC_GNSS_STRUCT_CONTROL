$ErrorActionPreference = "Stop"
$PreviewDir = $PSScriptRoot
$env:OC_GNSS_PREVIEW_ROOT = (Resolve-Path (Join-Path $PreviewDir "..")).Path
$ScriptPath = Join-Path $PreviewDir "start-preview.ps1"
$ScriptText = [System.IO.File]::ReadAllText($ScriptPath, [System.Text.Encoding]::UTF8)
$ScriptBlock = [ScriptBlock]::Create($ScriptText)
& $ScriptBlock @args
exit $LASTEXITCODE
