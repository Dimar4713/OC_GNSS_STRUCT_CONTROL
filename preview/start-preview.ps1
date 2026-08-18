param(
  [string]$Python = "py",
  [int]$Port = 8765,
  [switch]$NoBrowser
)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $Root

# Loopback authority traffic must never be sent through a corporate/system proxy.
$LoopbackNoProxy = "127.0.0.1,localhost,::1"
$env:NO_PROXY = $LoopbackNoProxy
$env:no_proxy = $LoopbackNoProxy

function Fail([string]$Message) {
  Write-Host "ERROR: $Message" -ForegroundColor Red
  exit 1
}

function Read-AuthorityFile([string]$RelativePath, [int]$ExpectedLength) {
  $Path = Join-Path $Root $RelativePath
  if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
    Fail "Missing authority file: $RelativePath"
  }
  $Value = (Get-Content -LiteralPath $Path -Raw).Trim()
  if ($Value.Length -ne $ExpectedLength -or $Value -notmatch '^[0-9a-f]+$') {
    Fail "Invalid authority value in $RelativePath"
  }
  return $Value
}

Write-Host "OC GNSS STRUCT CONTROL - Engineering Preview Python 0.1"
Write-Host "Repository: $Root"

$PythonArgs = @()
if ($Python -eq "py") {
  $PythonArgs = @("-3.12")
}
try {
  $Version = & $Python @PythonArgs -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
} catch {
  Fail "Python 3.12 was not found. Install Python 3.12 or pass -Python <executable>."
}
if (($Version | Select-Object -Last 1).Trim() -ne "3.12") {
  Fail "Engineering Preview requires Python 3.12; detected $Version"
}

$Venv = Join-Path $Root ".venv-preview"
$VenvPython = Join-Path $Venv "Scripts\python.exe"
if (-not (Test-Path -LiteralPath $VenvPython -PathType Leaf)) {
  Write-Host "Creating local Preview environment..."
  & $Python @PythonArgs -m venv $Venv
}

Write-Host "Installing/updating Preview dependencies..."
& $VenvPython -m pip install --disable-pip-version-check -r (Join-Path $Root "preview\requirements-preview.lock")
& $VenvPython -m pip install --disable-pip-version-check --no-deps -e $Root

$PinnedRevision = Read-AuthorityFile "sidecar\orekit-service\orekit-data-revision.txt" 40
$PinnedPhysicalSha = Read-AuthorityFile "sidecar\orekit-service\orekit-data-sha256.txt" 64
Write-Host "Reviewed Orekit data revision: $PinnedRevision"
Write-Host "Reviewed physical SHA-256:      $PinnedPhysicalSha"

$RuntimeRoot = Join-Path $Root "preview\runtime"
$BundledJar = Join-Path $RuntimeRoot "orekit-service.jar"
$SourceJar = Join-Path $Root "sidecar\orekit-service\target\orekit-service-0.1.0-SNAPSHOT.jar"
$OrekitJar = $null
if (Test-Path -LiteralPath $BundledJar -PathType Leaf) {
  $OrekitJar = $BundledJar
} elseif (Test-Path -LiteralPath $SourceJar -PathType Leaf) {
  $OrekitJar = $SourceJar
}

$OrekitData = $env:OREKIT_DATA_PATH
if ([string]::IsNullOrWhiteSpace($OrekitData)) {
  $CandidateData = Join-Path $RuntimeRoot "orekit-data"
  if (Test-Path -LiteralPath $CandidateData -PathType Container) {
    $OrekitData = $CandidateData
  }
}

$SidecarStarted = $false
$Sidecar = $null
if ($OrekitJar -and $OrekitData -and (Test-Path -LiteralPath $OrekitData -PathType Container)) {
  Write-Host "Verifying Orekit physical data fingerprint..."
  $ActualSha = (& $VenvPython (Join-Path $Root "scripts\fingerprint_orekit_data.py") $OrekitData | Select-Object -Last 1).Trim()
  if ($ActualSha -ne $PinnedPhysicalSha) {
    Fail "Orekit data fingerprint mismatch. Expected $PinnedPhysicalSha, got $ActualSha"
  }

  try {
    $JavaVersionText = (& java -version 2>&1 | Select-Object -First 1)
  } catch {
    $JavaVersionText = $null
  }
  if ($JavaVersionText) {
    $JavaMatch = [regex]::Match([string]$JavaVersionText, 'version "(?<major>[0-9]+)')
    if (-not $JavaMatch.Success -or [int]$JavaMatch.Groups['major'].Value -lt 17) {
      Fail "High-fidelity runtime requires Java 17+; detected: $JavaVersionText"
    }

    Write-Host "Starting verified Orekit sidecar on 127.0.0.1:8081..."
    $env:OREKIT_DATA_PATH = $OrekitData
    $env:OREKIT_PORT = "8081"
    New-Item -ItemType Directory -Force -Path $RuntimeRoot | Out-Null
    $SidecarStdout = Join-Path $RuntimeRoot "orekit-sidecar.out.log"
    $SidecarStderr = Join-Path $RuntimeRoot "orekit-sidecar.err.log"
    $Sidecar = Start-Process -FilePath "java" -ArgumentList @("-jar", $OrekitJar) -RedirectStandardOutput $SidecarStdout -RedirectStandardError $SidecarStderr -PassThru
    for ($Attempt = 0; $Attempt -lt 30; $Attempt++) {
      try {
        $Health = Invoke-RestMethod -Uri "http://127.0.0.1:8081/healthz" -TimeoutSec 1 -NoProxy
        if (
          $Health.status -eq "ok" -and
          $Health.backend -eq "orekit" -and
          $Health.orekit_data_revision -eq $PinnedRevision -and
          $Health.orekit_data_sha256 -eq $PinnedPhysicalSha
        ) {
          $SidecarStarted = $true
          Write-Host "Orekit authority READY: version $($Health.orekit_version), data $($Health.orekit_data_revision)"
          break
        }
      } catch { }
      if ($Sidecar.HasExited) { break }
      Start-Sleep -Milliseconds 500
    }
    if (-not $SidecarStarted) {
      if (-not $Sidecar.HasExited) { Stop-Process -Id $Sidecar.Id -Force }
      Fail "Orekit sidecar failed reviewed revision/SHA health verification. See $SidecarStdout and $SidecarStderr"
    }
  } else {
    Write-Host "Java not available: Screening is usable; Design/Validation will remain NOT READY." -ForegroundColor Yellow
  }
} else {
  Write-Host "Verified Orekit runtime not present: Screening is usable; Design/Validation will remain NOT READY." -ForegroundColor Yellow
  Write-Host "For high fidelity, provide preview\runtime\orekit-service.jar and verified orekit-data (or OREKIT_DATA_PATH)."
}

$Url = "http://127.0.0.1:$Port"
if (-not $NoBrowser) {
  Start-Process $Url
}
Write-Host "Starting Engineering Preview at $Url"
try {
  & $VenvPython -m constellation_control.cli.main preview --host 127.0.0.1 --port $Port --scenarios (Join-Path $Root "scenarios") --output (Join-Path $Root "preview\results")
} finally {
  if ($SidecarStarted -and $Sidecar -and -not $Sidecar.HasExited) {
    Stop-Process -Id $Sidecar.Id -Force
  }
}
