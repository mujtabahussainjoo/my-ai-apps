@echo off
setlocal
title Install NexaPilot AI
echo ==========================================
echo  NexaPilot AI installer
echo ==========================================
echo.
echo  This window is the installer. Keep it open.
echo  A first build from source takes 10-20 minutes;
echo  a pre-built setup installs in under a minute.
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1" %*
set "rc=%ERRORLEVEL%"
echo.
if not "%rc%"=="0" (
    echo Installation failed with exit code %rc%. See the messages above.
) else (
    echo Installation finished.
)
echo.
pause
exit /b %rc%
