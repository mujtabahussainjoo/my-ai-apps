# NexaPilot AI - uninstaller wizard for Windows 10/11.
#
# Double-click "Uninstall NexaPilot AI.cmd" for an interactive wizard, or run:
#   .\uninstall.ps1           # ask whether to keep chats/settings
#   .\uninstall.ps1 -Purge    # remove the app and all local data
#   .\uninstall.ps1 -KeepData # remove the app, keep chats/settings
#   .\uninstall.ps1 -Purge -Yes -Silent
param(
    [switch]$Purge,
    [switch]$KeepData,
    [switch]$Yes,
    [switch]$Silent
)

$ErrorActionPreference = "Stop"
$AppName = "NexaPilot AI"

function Write-Step($msg) { Write-Host "`n==> $msg" -ForegroundColor Cyan }
function Write-Detail($msg) { Write-Host "    $msg" -ForegroundColor DarkGray }

function Find-UninstallEntry {
    foreach ($root in @(
        "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*",
        "HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*",
        "HKLM:\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*"
    )) {
        $entry = Get-ItemProperty -Path $root -ErrorAction SilentlyContinue |
            Where-Object { $_.DisplayName -eq $AppName -or $_.DisplayName -like "*NexaPilot*" } |
            Select-Object -First 1
        if ($entry) { return $entry }
    }
    return $null
}

if ($Purge -and $KeepData) {
    throw "Use either -Purge or -KeepData, not both."
}

Write-Host "NexaPilot AI uninstaller" -ForegroundColor White

if (-not $Purge -and -not $KeepData -and -not $Yes) {
    Write-Host ""
    Write-Host "  1. Remove the app, keep my chats and settings (recommended)"
    Write-Host "  2. Remove the app and all local data"
    Write-Host ""
    do { $choice = Read-Host "Choose 1 or 2" } while ($choice -notin @("1", "2"))
    if ($choice -eq "2") { $Purge = $true } else { $KeepData = $true }
}

if (-not $Yes -and -not $Silent) {
    $confirm = Read-Host "`nUninstall $AppName now? [Y/n]"
    if ($confirm -and $confirm -notmatch '^[Yy]') {
        Write-Host "Cancelled. Nothing was changed."
        exit 0
    }
}

Write-Step "Stopping NexaPilot"
foreach ($name in @("nexapilot-desktop", "nexapilot-server")) {
    $procs = Get-Process -Name $name -ErrorAction SilentlyContinue
    if ($procs) {
        $procs | Stop-Process -Force -ErrorAction SilentlyContinue
        Write-Detail "stopped $name"
    }
}
Start-Sleep -Seconds 1

Write-Step "Removing $AppName"
$entry = Find-UninstallEntry
$command = $null
if ($entry) {
    if ($entry.QuietUninstallString) { $command = $entry.QuietUninstallString }
    elseif ($entry.UninstallString) { $command = $entry.UninstallString }
}

if ($command) {
    Write-Detail "running the bundled uninstaller"
    $proc = Start-Process -FilePath "cmd.exe" -ArgumentList "/c", $command -Wait -PassThru
    if ($proc.ExitCode -ne 0) {
        Write-Detail "uninstaller exited with code $($proc.ExitCode); checking leftover files"
    }
} else {
    $candidates = @(
        (Join-Path $env:LOCALAPPDATA "$AppName\uninstall.exe"),
        (Join-Path $env:LOCALAPPDATA "Programs\$AppName\uninstall.exe"),
        (Join-Path $env:LOCALAPPDATA "$AppName\Uninstall.exe"),
        (Join-Path $env:LOCALAPPDATA "Programs\$AppName\Uninstall.exe"),
        (Join-Path ${env:ProgramFiles} "$AppName\uninstall.exe")
    )
    $exe = $candidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
    if ($exe) {
        Write-Detail "running $exe /S"
        $proc = Start-Process -FilePath $exe -ArgumentList "/S" -Wait -PassThru
        if ($proc.ExitCode -ne 0) {
            Write-Detail "uninstaller exited with code $($proc.ExitCode)"
        }
    } else {
        Write-Detail "No uninstaller found - the app may already be removed."
    }
}

Write-Step "Cleaning shortcuts"
foreach ($lnk in @(
    (Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\$AppName.lnk"),
    (Join-Path $env:USERPROFILE "Desktop\$AppName.lnk"),
    (Join-Path $env:PUBLIC "Desktop\$AppName.lnk")
)) {
    if (Test-Path -LiteralPath $lnk) {
        Remove-Item -LiteralPath $lnk -Force -ErrorAction SilentlyContinue
        Write-Detail "removed $lnk"
    }
}

if ($Purge) {
    Write-Step "Deleting local data"
    foreach ($dir in @(
        (Join-Path $env:APPDATA "nexapilot"),
        (Join-Path $env:APPDATA "ai.nexapilot.desktop"),
        (Join-Path $env:LOCALAPPDATA "ai.nexapilot.desktop"),
        (Join-Path $env:LOCALAPPDATA "NexaPilot\build")
    )) {
        if (Test-Path -LiteralPath $dir) {
            Remove-Item -LiteralPath $dir -Recurse -Force -ErrorAction SilentlyContinue
            Write-Detail "removed $dir"
        }
    }
    Write-Host ""
    Write-Host "Revoke Google OAuth grants at https://myaccount.google.com/permissions" -ForegroundColor Yellow
} else {
    Write-Step "Keeping your data"
    Write-Detail (Join-Path $env:APPDATA "nexapilot")
    Write-Host "Run this again with -Purge to remove chats, settings, and cached webview data."
}

Write-Step "Done"
