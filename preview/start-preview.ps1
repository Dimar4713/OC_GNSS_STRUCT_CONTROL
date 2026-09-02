param(
  [string]$Python = "py",
  [int]$Port = 8765,
  [switch]$NoBrowser
)

$ErrorActionPreference = "Stop"
if (-not [string]::IsNullOrWhiteSpace($env:OC_GNSS_PREVIEW_ROOT)) {
  $Root = (Resolve-Path $env:OC_GNSS_PREVIEW_ROOT).Path
} elseif (-not [string]::IsNullOrWhiteSpace($PSScriptRoot)) {
  $Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
} else {
  throw "Preview root is unavailable / Корневой каталог Preview не определён"
}
Set-Location $Root

$LoopbackNoProxy = "127.0.0.1,localhost,::1"
$env:NO_PROXY = $LoopbackNoProxy
$env:no_proxy = $LoopbackNoProxy

function Fail([string]$Ru, [string]$En) {
  Write-Host "ОШИБКА / ERROR: $Ru / $En" -ForegroundColor Red
  exit 1
}

function Read-AuthorityFile([string]$RelativePath, [int]$ExpectedLength) {
  $Path = Join-Path $Root $RelativePath
  if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
    Fail "Отсутствует файл authority: $RelativePath" "Missing authority file: $RelativePath"
  }
  $Value = (Get-Content -LiteralPath $Path -Raw).Trim()
  if ($Value.Length -ne $ExpectedLength -or $Value -notmatch '^[0-9a-f]+$') {
    Fail "Некорректное значение authority в $RelativePath" "Invalid authority value in $RelativePath"
  }
  return $Value
}

function Get-DirectJson([string]$Uri, [int]$TimeoutMs = 1000) {
  $Request = [System.Net.HttpWebRequest][System.Net.WebRequest]::Create($Uri)
  $Request.Method = "GET"
  $Request.Proxy = $null
  $Request.Timeout = $TimeoutMs
  $Request.ReadWriteTimeout = $TimeoutMs
  $Request.KeepAlive = $false
  $Response = $null
  $Reader = $null
  try {
    $Response = [System.Net.HttpWebResponse]$Request.GetResponse()
    $Reader = New-Object System.IO.StreamReader($Response.GetResponseStream())
    $Text = $Reader.ReadToEnd()
    return ($Text | ConvertFrom-Json)
  } finally {
    if ($Reader) { $Reader.Dispose() }
    if ($Response) { $Response.Dispose() }
  }
}

function Get-LoopbackListenerOwner([int]$LocalPort) {
  try {
    $Connection = Get-NetTCPConnection -State Listen -LocalPort $LocalPort -ErrorAction Stop |
      Where-Object { $_.LocalAddress -in @("127.0.0.1", "0.0.0.0", "::1", "::") } |
      Select-Object -First 1
    if ($Connection) { return [int]$Connection.OwningProcess }
  } catch { }
  return $null
}

function Clear-StaleOrekitListener([int]$LocalPort) {
  $OwnerPid = Get-LoopbackListenerOwner $LocalPort
  if ($null -eq $OwnerPid) { return }

  $ProcessInfo = $null
  try { $ProcessInfo = Get-CimInstance Win32_Process -Filter "ProcessId = $OwnerPid" -ErrorAction Stop } catch { }
  $ProcessName = if ($ProcessInfo) { [string]$ProcessInfo.Name } else { "unknown" }
  $CommandLine = if ($ProcessInfo) { [string]$ProcessInfo.CommandLine } else { "" }
  $LooksLikeOrekit = (
    $ProcessInfo -and
    $ProcessName -match '^java(w)?\.exe$' -and
    $CommandLine -match 'orekit-service(?:-0\.1\.0-SNAPSHOT)?\.jar'
  )
  if (-not $LooksLikeOrekit) {
    Fail (
      "Порт 127.0.0.1:$LocalPort уже занят процессом $ProcessName (PID $OwnerPid). Preview не будет завершать посторонний процесс."
    ) (
      "Port 127.0.0.1:$LocalPort is already occupied by $ProcessName (PID $OwnerPid). Preview will not terminate an unrelated process."
    )
  }
  Write-Host "Найден оставшийся Orekit sidecar PID $OwnerPid; завершаем перед чистым запуском. / Stale Orekit sidecar PID $OwnerPid found; stopping it before a clean launch." -ForegroundColor Yellow
  try { Stop-Process -Id $OwnerPid -Force -ErrorAction Stop } catch {
    Fail "Не удалось завершить оставшийся Orekit sidecar PID $OwnerPid" "Failed to stop stale Orekit sidecar PID $OwnerPid"
  }
  for ($Attempt = 0; $Attempt -lt 20; $Attempt++) {
    Start-Sleep -Milliseconds 250
    if ($null -eq (Get-LoopbackListenerOwner $LocalPort)) { return }
  }
  Fail "Порт 127.0.0.1:$LocalPort не освободился после остановки старого sidecar" "Port 127.0.0.1:$LocalPort did not become free after stopping the stale sidecar"
}

Write-Host "OC GNSS STRUCT CONTROL - Engineering Preview Python 0.2.5"
Write-Host "Корень / Root: $Root"

$PythonArgs = @()
if ($Python -eq "py") { $PythonArgs = @("-3.12") }
try {
  $Version = & $Python @PythonArgs -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
} catch {
  Fail "Python 3.12 не найден. Установите Python 3.12 для пользователя или задайте -Python <executable>." "Python 3.12 was not found. Install Python 3.12 for the user or pass -Python <executable>."
}
if (($Version | Select-Object -Last 1).Trim() -ne "3.12") {
  Fail "Engineering Preview требует Python 3.12; обнаружен $Version" "Engineering Preview requires Python 3.12; detected $Version"
}

$Venv = Join-Path $Root ".venv-preview"
$VenvPython = Join-Path $Venv "Scripts\python.exe"
if (-not (Test-Path -LiteralPath $VenvPython -PathType Leaf)) {
  Write-Host "Создание локального окружения Preview... / Creating local Preview environment..."
  & $Python @PythonArgs -m venv $Venv
}

Write-Host "Установка/обновление зависимостей Preview... / Installing/updating Preview dependencies..."
& $VenvPython -m pip install --disable-pip-version-check -r (Join-Path $Root "preview\requirements-preview.lock")
& $VenvPython -m pip install --disable-pip-version-check --no-deps -e $Root

$PinnedRevision = Read-AuthorityFile "sidecar\orekit-service\orekit-data-revision.txt" 40
$PinnedPhysicalSha = Read-AuthorityFile "sidecar\orekit-service\orekit-data-sha256.txt" 64
$env:OREKIT_DATA_REVISION = $PinnedRevision
Write-Host "Проверенная ревизия Orekit data / Reviewed revision: $PinnedRevision"
Write-Host "Проверенный physical SHA-256 / Reviewed SHA:   $PinnedPhysicalSha"
Write-Host "Runtime authority export / Экспорт authority: OREKIT_DATA_REVISION=$($env:OREKIT_DATA_REVISION)"

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
  if (Test-Path -LiteralPath $CandidateData -PathType Container) { $OrekitData = $CandidateData }
}

$SidecarStarted = $false
$Sidecar = $null
if ($OrekitJar -and $OrekitData -and (Test-Path -LiteralPath $OrekitData -PathType Container)) {
  Write-Host "Проверка physical fingerprint Orekit data... / Verifying Orekit physical data fingerprint..."
  $ActualSha = (& $VenvPython (Join-Path $Root "scripts\fingerprint_orekit_data.py") $OrekitData | Select-Object -Last 1).Trim()
  if ($ActualSha -ne $PinnedPhysicalSha) {
    Fail "Fingerprint Orekit data не совпадает. Ожидался $PinnedPhysicalSha, получен $ActualSha" "Orekit data fingerprint mismatch. Expected $PinnedPhysicalSha, got $ActualSha"
  }

  try { $JavaVersionText = (& java -version 2>&1 | Select-Object -First 1) } catch { $JavaVersionText = $null }
  if ($JavaVersionText) {
    $JavaMatch = [regex]::Match([string]$JavaVersionText, 'version "(?<major>[0-9]+)')
    if (-not $JavaMatch.Success -or [int]$JavaMatch.Groups['major'].Value -lt 17) {
      Fail "High-fidelity runtime требует Java 17+; обнаружено: $JavaVersionText" "High-fidelity runtime requires Java 17+; detected: $JavaVersionText"
    }

    Clear-StaleOrekitListener 8081
    Write-Host "Запуск проверенного Orekit sidecar на 127.0.0.1:8081... / Starting verified Orekit sidecar..."
    $env:OREKIT_DATA_PATH = $OrekitData
    $env:OREKIT_PORT = "8081"
    New-Item -ItemType Directory -Force -Path $RuntimeRoot | Out-Null
    $SidecarStdout = Join-Path $RuntimeRoot "orekit-sidecar.out.log"
    $SidecarStderr = Join-Path $RuntimeRoot "orekit-sidecar.err.log"
    $Sidecar = Start-Process -FilePath "java" -ArgumentList @("-jar", $OrekitJar) -RedirectStandardOutput $SidecarStdout -RedirectStandardError $SidecarStderr -PassThru
    $LastHealth = $null
    $LastHealthError = $null
    for ($Attempt = 0; $Attempt -lt 60; $Attempt++) {
      try {
        $Health = Get-DirectJson "http://127.0.0.1:8081/healthz" 1000
        $LastHealth = $Health
        $LastHealthError = $null
        if (
          $Health.status -eq "ok" -and
          $Health.backend -eq "orekit" -and
          $Health.orekit_version -eq "13.1.7" -and
          $Health.orekit_data_revision -eq $PinnedRevision -and
          $Health.orekit_data_sha256 -eq $PinnedPhysicalSha
        ) {
          $SidecarStarted = $true
          Write-Host "Orekit authority ГОТОВО / READY: version $($Health.orekit_version), data $($Health.orekit_data_revision)"
          break
        }
      } catch { $LastHealthError = $_.Exception.Message }
      if ($Sidecar.HasExited) { break }
      Start-Sleep -Milliseconds 500
    }
    if (-not $SidecarStarted) {
      if (-not $Sidecar.HasExited) { Stop-Process -Id $Sidecar.Id -Force }
      $HealthIdentity = if ($LastHealth) {
        "status=$($LastHealth.status), backend=$($LastHealth.backend), orekit=$($LastHealth.orekit_version), revision=$($LastHealth.orekit_data_revision), sha=$($LastHealth.orekit_data_sha256)"
      } elseif ($LastHealthError) { "health unavailable: $LastHealthError" } else { "health unavailable" }
      $StderrTail = ""
      if (Test-Path -LiteralPath $SidecarStderr -PathType Leaf) {
        $StderrTail = ((Get-Content -LiteralPath $SidecarStderr -Tail 8 -ErrorAction SilentlyContinue) -join " | ").Trim()
      }
      Fail (
        "Orekit sidecar не прошёл проверку revision/SHA. Получено: $HealthIdentity. stderr: $StderrTail. См. $SidecarStdout и $SidecarStderr"
      ) (
        "Orekit sidecar failed reviewed revision/SHA health verification. Actual: $HealthIdentity. stderr: $StderrTail. See $SidecarStdout and $SidecarStderr"
      )
    }
  } else {
    Write-Host "Java недоступна: Screening работает; Design/Validation будут НЕ ГОТОВО. / Java unavailable: Screening works; Design/Validation remain NOT READY." -ForegroundColor Yellow
  }
} else {
  Write-Host "Проверенный Orekit runtime отсутствует: Screening работает; Design/Validation будут НЕ ГОТОВО. / Verified Orekit runtime not present: Screening works; Design/Validation remain NOT READY." -ForegroundColor Yellow
  Write-Host "Для high fidelity нужны preview\runtime\orekit-service.jar и проверенный orekit-data (или OREKIT_DATA_PATH). / High fidelity requires the bundled JAR and verified orekit-data."
}

$Url = "http://127.0.0.1:$Port"
if (-not $NoBrowser) { Start-Process $Url }
Write-Host "Запуск Engineering Preview / Starting Engineering Preview: $Url"
try {
  & $VenvPython -m constellation_control.cli.main preview --host 127.0.0.1 --port $Port --scenarios (Join-Path $Root "scenarios") --output (Join-Path $Root "preview\results")
} finally {
  if ($SidecarStarted -and $Sidecar -and -not $Sidecar.HasExited) { Stop-Process -Id $Sidecar.Id -Force }
}
