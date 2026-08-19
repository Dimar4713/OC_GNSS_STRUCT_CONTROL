@echo off
setlocal EnableExtensions DisableDelayedExpansion

rem OC GNSS STRUCT CONTROL - Engineering Preview portable USB launcher
rem The project root is the directory containing this BAT file.
set "ROOT=%~dp0"
if "%ROOT:~-1%"=="\" set "ROOT=%ROOT:~0,-1%"

set "OC_GNSS_PREVIEW_ROOT=%ROOT%"
set "OREKIT_DATA_REVISION=baf158744d38ec76cf94e2d396280d545b9f0ba2"
set "NO_PROXY=127.0.0.1,localhost,::1"
set "no_proxy=127.0.0.1,localhost,::1"

set "PYTHON_EXE=%ROOT%\.venv-preview\Scripts\python.exe"
if not exist "%PYTHON_EXE%" (
  echo.
  echo ERROR: Portable Preview Python was not found:
  echo   %PYTHON_EXE%
  echo.
  echo ОШИБКА: Не найден Python в .venv-preview на USB-накопителе.
  pause
  exit /b 10
)

rem Find a bundled Java 17+ runtime anywhere below ROOT\java.
set "JAVA_EXE="
if exist "%ROOT%\java\bin\java.exe" set "JAVA_EXE=%ROOT%\java\bin\java.exe"
if not defined JAVA_EXE if exist "%ROOT%\java" (
  for /r "%ROOT%\java" %%J in (java.exe) do (
    if not defined JAVA_EXE if /i "%%~nxJ"=="java.exe" if /i "%%~nxJ"=="java.exe" set "JAVA_EXE=%%~fJ"
  )
)
if not defined JAVA_EXE (
  echo.
  echo ERROR: Bundled Java runtime was not found below:
  echo   %ROOT%\java
  echo.
  echo ОШИБКА: Не найден переносимый Java runtime в каталоге java.
  pause
  exit /b 11
)

for %%J in ("%JAVA_EXE%") do set "JAVA_BIN=%%~dpJ"
for %%J in ("%JAVA_BIN%..") do set "JAVA_HOME=%%~fJ"
set "PATH=%JAVA_BIN%;%PATH%"

echo ============================================================
echo OC GNSS STRUCT CONTROL - Engineering Preview USB
echo Root       : %ROOT%
echo Python     : %PYTHON_EXE%
echo JAVA_HOME  : %JAVA_HOME%
echo Java       : %JAVA_EXE%
echo URL        : http://127.0.0.1:8766
echo ============================================================
echo.

rem Fail fast if the copied venv is not usable on this computer.
"%PYTHON_EXE%" -c "import sys; assert sys.version_info[:2] == (3,12); print('Portable Python OK:', sys.executable)"
if errorlevel 1 (
  echo.
  echo ERROR: The copied .venv-preview is not portable on this PC.
  echo A normal Windows venv can retain a dependency on the base Python installation.
  echo ОШИБКА: Перенесённый .venv-preview не может запуститься на этом ПК.
  echo Для полностью автономной поставки нужен bundled Python runtime, а не обычный venv.
  pause
  exit /b 12
)

"%JAVA_EXE%" -version >nul 2>&1
if errorlevel 1 (
  echo.
  echo ERROR: Bundled Java runtime cannot start.
  echo ОШИБКА: Переносимый Java runtime не запускается.
  pause
  exit /b 13
)

powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%ROOT%\preview\start-preview-bootstrap.ps1" -Python "%PYTHON_EXE%" -Port 8766
set "EXITCODE=%ERRORLEVEL%"
if not "%EXITCODE%"=="0" (
  echo.
  echo Engineering Preview failed. See bilingual diagnostics above. Exit code %EXITCODE%.
  pause
)
exit /b %EXITCODE%
