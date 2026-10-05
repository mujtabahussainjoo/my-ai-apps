# Windows entry point: powershell -ExecutionPolicy Bypass -File .\install.ps1
param([string]$Model = '', [string]$Prefix = '', [switch]$DryRun, [switch]$NoPath)
$ErrorActionPreference = 'Stop'
function Find-Python {
    foreach ($Name in @('python', 'python3')) {
        $Command = Get-Command $Name -ErrorAction SilentlyContinue
        if ($Command) {
            & $Command.Source -c "import sys, venv, ensurepip; sys.exit(0 if sys.version_info >= (3,10) else 1)" 2>$null
            if ($LASTEXITCODE -eq 0) { return $Command.Source }
        }
    }
    $Launcher = Get-Command py -ErrorAction SilentlyContinue
    if ($Launcher) {
        $Executable = & $Launcher.Source -3 -c "import sys, venv, ensurepip; print(sys.executable if sys.version_info >= (3,10) else '')" 2>$null
        if ($LASTEXITCODE -eq 0 -and $Executable) { return $Executable.Trim() }
    }
    return $null
}
$Python = Find-Python
if ($DryRun -and -not $Python) {
    Write-Output 'Plan: bootstrap Python 3.10+, create myPA virtual environment, install dependencies and Ollama, download the model, install launcher and PATH.'
    exit 0
}
if (-not $Python) {
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        & winget install --id Python.Python.3.14 --exact --silent --accept-package-agreements --accept-source-agreements
        if ($LASTEXITCODE -ne 0) { throw 'Python installation failed.' }
    } else {
        $Version = '3.14.8'
        $Architecture = if ($env:PROCESSOR_ARCHITECTURE -eq 'ARM64') { 'arm64' } else { 'amd64' }
        $Setup = Join-Path $env:TEMP 'mypa-python-setup.exe'
        Invoke-WebRequest -UseBasicParsing -Uri "https://www.python.org/ftp/python/$Version/python-$Version-$Architecture.exe" -OutFile $Setup
        $Process = Start-Process -FilePath $Setup -ArgumentList '/quiet', 'InstallAllUsers=0', 'PrependPath=1', 'Include_pip=1', 'Include_test=0' -Wait -PassThru
        if ($Process.ExitCode -notin @(0, 3010)) { throw 'Python installation failed.' }
        Remove-Item $Setup
    }
    $env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' + [Environment]::GetEnvironmentVariable('Path', 'User')
    $Python = Find-Python
    if (-not $Python) {
        $Candidate = Join-Path $env:LOCALAPPDATA 'Programs\Python\Python314\python.exe'
        if (Test-Path $Candidate) { $Python = $Candidate }
    }
    if (-not $Python) { throw 'Python was installed but could not be located. Open a new terminal and rerun.' }
}
$InstallArguments = @((Join-Path $PSScriptRoot 'install.py'))
if ($Model) { $InstallArguments += @('--model', $Model) }
if ($Prefix) { $InstallArguments += @('--prefix', $Prefix) }
if ($DryRun) { $InstallArguments += '--dry-run' }
if ($NoPath) { $InstallArguments += '--no-path' }
& $Python @InstallArguments
exit $LASTEXITCODE
