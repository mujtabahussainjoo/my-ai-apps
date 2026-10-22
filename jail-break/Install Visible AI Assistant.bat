@echo off
rem "Install" button for Windows: sets everything up and exits.
rem
rem Installs Node.js if it is missing (portable copy, no administrator rights),
rem then npm dependencies + Electron, builds the app, and creates the
rem Desktop / Start Menu icons. Afterwards start the app from those icons.

setlocal
set "ROOT=%~dp0"
if "%ROOT:~-1%"=="\" set "ROOT=%ROOT:~0,-1%"

pushd "%SystemRoot%"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%ROOT%\scripts\bootstrap.ps1" --install
set "RC=%ERRORLEVEL%"
popd

echo.
if "%RC%"=="0" (
  echo Setup complete. Open "Visible AI Assistant" from your Desktop or Start Menu.
) else (
  echo Setup failed. Check the message above and try again.
)
pause
exit /b %RC%
