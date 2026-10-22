#Requires -Version 5.1
<#
  One-click setup for Windows.

  Runs before Node.js exists, so it only uses built-in PowerShell:
    1. Finds node.exe (PATH, then our portable copy).
    2. If missing/too old: downloads the official Node.js zip from nodejs.org,
       verifies its SHA256, and unpacks it into %LOCALAPPDATA% — no admin, no MSI.
    3. Hands off to scripts/launch.js, which installs npm packages (including
       Electron) and builds the app, then starts it (or installs shortcuts only
       when --install is passed).
#>
[CmdletBinding()]
param(
  [Parameter(ValueFromRemainingArguments = $true)]
  [string[]] $ForwardArgs
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

$Root = Split-Path -Parent $PSScriptRoot
$NodeDir = Join-Path $env:LOCALAPPDATA 'Visible AI Assistant\node'
$NodeExe = Join-Path $NodeDir 'node.exe'
$Launcher = Join-Path $Root 'scripts\launch.js'
$MinMajor = 18

function Write-Step([string] $Message) {
  Write-Host ("[install] " + $Message)
}

function Get-NodeMajor([string] $Exe) {
  try {
    $version = (& $Exe -p "process.versions.node" 2>$null | Select-Object -First 1)
    if (-not $version) { return 0 }
    return [int](($version -split '\.')[0])
  } catch {
    return 0
  }
}

function Find-Node {
  $cmd = Get-Command node.exe -ErrorAction SilentlyContinue
  if ($cmd -and (Get-NodeMajor $cmd.Source) -ge $MinMajor) { return $cmd.Source }
  if (Test-Path $NodeExe) {
    if ((Get-NodeMajor $NodeExe) -ge $MinMajor) { return $NodeExe }
  }
  return $null
}

function Install-PortableNode {
  Write-Step 'Node.js not found (or too old) - downloading a portable copy...'
  Write-Step 'No administrator rights needed.'

  [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
  $base = 'https://nodejs.org/dist/latest-v22.x'
  $sums = (Invoke-WebRequest -UseBasicParsing -Uri "$base/SHASUMS256.txt").Content

  $arch = if ($env:PROCESSOR_ARCHITECTURE -eq 'ARM64') { 'arm64' } else { 'x64' }
  $pattern = "win-$arch\.zip$"
  $line = ($sums -split "`n" | Where-Object { $_ -match $pattern } | Select-Object -First 1)
  if (-not $line) { throw "No Windows $arch build listed at nodejs.org." }

  $parts = ($line.Trim() -split '\s+')
  $hash = $parts[0].ToLower()
  $file = $parts[-1]
  $url = "$base/$file"
  $zip = Join-Path $env:TEMP $file

  Write-Step "Downloading $file ..."
  Invoke-WebRequest -UseBasicParsing -Uri $url -OutFile $zip

  Write-Step 'Verifying checksum...'
  $actual = (Get-FileHash -Algorithm SHA256 -Path $zip).Hash.ToLower()
  if ($actual -ne $hash) { throw 'Node.js download failed its SHA256 check.' }

  Write-Step 'Extracting Node.js...'
  $tmp = Join-Path $env:TEMP ('vai-node-' + [guid]::NewGuid().ToString('N'))
  Expand-Archive -Path $zip -DestinationPath $tmp -Force
  $inner = Get-ChildItem -Path $tmp -Directory | Select-Object -First 1
  if (-not $inner) { throw 'The Node.js zip did not contain a folder.' }

  New-Item -ItemType Directory -Force -Path (Split-Path -Parent $NodeDir) | Out-Null
  if (Test-Path $NodeDir) { Remove-Item -Path $NodeDir -Recurse -Force }
  Move-Item -Path $inner.FullName -Destination $NodeDir

  Remove-Item -Path $zip -Recurse -Force -ErrorAction SilentlyContinue
  Remove-Item -Path $tmp -Recurse -Force -ErrorAction SilentlyContinue

  if (-not (Test-Path $NodeExe)) { throw 'Node.js extraction failed.' }
  Write-Step ('Node.js ready: ' + (& $NodeExe --version))
}

try {
  if (-not (Test-Path $Launcher)) {
    throw "Cannot find $Launcher. Keep the whole project folder together."
  }

  $node = Find-Node
  if (-not $node) {
    Install-PortableNode
    $node = $NodeExe
  }

  # Make node/npm visible to the launcher and to npm's child processes.
  $env:PATH = (Split-Path -Parent $node) + ';' + $env:PATH

  Write-Step 'Starting setup...'
  Push-Location $env:SystemRoot
  try {
    & $node $Launcher @ForwardArgs
    $code = $LASTEXITCODE
  } finally {
    Pop-Location
  }
  if ($code -ne 0) { throw "Setup exited with code $code." }
  exit 0
} catch {
  $message = $_.Exception.Message
  Write-Host ''
  Write-Host ('[install] FAILED: ' + $message) -ForegroundColor Red
  Write-Host 'Check your internet connection and try again.'
  try {
    Add-Type -AssemblyName PresentationFramework
    [System.Windows.MessageBox]::Show(
      ($message + "`n`nVisible AI Assistant needs an internet connection the first time.`nTry again once you are online."),
      'Visible AI Assistant setup'
    ) | Out-Null
  } catch {
    Write-Host 'Press Enter to close...'
    Read-Host | Out-Null
  }
  exit 1
}
