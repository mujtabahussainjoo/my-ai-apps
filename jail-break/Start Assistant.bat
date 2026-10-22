@echo off
rem One-click setup + launcher for Windows. Double-click this file.
rem
rem Works on a machine with nothing installed:
rem   - finds Node.js, or downloads a portable copy to %LOCALAPPDATA% (no admin)
rem   - installs npm dependencies, including Electron
rem   - builds the app
rem   - creates Desktop / Start Menu icons
rem   - starts the app
rem
rem Pass --install to set everything up without starting the app.
rem The real work lives in scripts\bootstrap.ps1, which runs before Node.js
rem exists (so it only needs PowerShell, which ships with Windows).

setlocal
set "ROOT=%~dp0"
if "%ROOT:~-1%"=="\" set "ROOT=%ROOT:~0,-1%"

pushd "%SystemRoot%"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%ROOT%\scripts\bootstrap.ps1" %*
set "RC=%ERRORLEVEL%"
popd

if not "%RC%"=="0" (
  echo.
  echo Setup did not finish. Check the message above.
  pause
)

exit /b %RC%
