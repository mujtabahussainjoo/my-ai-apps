@echo off
REM ============================================================
REM  myPA Setup for Windows — DOUBLE-CLICK THIS FILE to install
REM  No admin needed. Nothing installs without your permission.
REM ============================================================
cd /d "%~dp0"
where python >nul 2>nul
if errorlevel 1 (
  echo.
  echo  [myPA] Python 3.10+ was not found.
  echo  Please install it first from https://www.python.org/downloads/
  echo  Tick "Add python.exe to PATH" during install, then run this again.
  echo.
  pause
  exit /b 1
)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1"
echo.
pause
