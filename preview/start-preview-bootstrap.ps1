$ErrorActionPreference = "Stop"
$ScriptPath = Join-Path $PSScriptRoot "start-preview.ps1"
$ScriptText = [System.IO.File]::ReadAllText($ScriptPath, [System.Text.Encoding]::UTF8)
$ScriptBlock = [ScriptBlock]::Create($ScriptText)
& $ScriptBlock @args
exit $LASTEXITCODE
