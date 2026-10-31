@echo off
setlocal
title Uninstall NexaPilot AI
echo ==========================================
echo  NexaPilot AI uninstaller
echo ==========================================
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0uninstall.ps1" %*
set "rc=%ERRORLEVEL%"
echo.
if not "%rc%"=="0" (
    echo Uninstall failed with exit code %rc%. See the messages above.
) else (
    echo Uninstall finished.
)
echo.
pause
exit /b %rc%
