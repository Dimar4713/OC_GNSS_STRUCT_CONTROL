@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0preview\start-preview-bootstrap.ps1" %*
set EXITCODE=%ERRORLEVEL%
if not "%EXITCODE%"=="0" (
  echo.
  echo Engineering Preview failed. See bilingual diagnostics above. Exit code %EXITCODE%.
  pause
)
exit /b %EXITCODE%
