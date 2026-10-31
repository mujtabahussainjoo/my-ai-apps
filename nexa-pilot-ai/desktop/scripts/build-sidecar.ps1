# Build the standalone backend used as the Tauri sidecar on Windows.
$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$triple = (rustc -vV | Select-String '^host:').ToString().Split(' ')[1].Trim()
$outDir = Join-Path $repoRoot "desktop\src-tauri\binaries"
New-Item -ItemType Directory -Force -Path $outDir | Out-Null

function Invoke-Native {
    param(
        [string]$Label,
        [scriptblock]$Command
    )
    $previous = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        & $Command 2>&1 | ForEach-Object { Write-Host $_ }
        $code = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previous
    }
    if ($code -ne 0) { throw "$Label failed (exit $code)." }
}

Push-Location (Join-Path $repoRoot "backend")
try {
    Invoke-Native "uv sync" { uv sync --extra packaging }
    Invoke-Native "PyInstaller" {
        uv run pyinstaller `
            --noconfirm `
            --clean `
            --name nexapilot-server `
            --onefile `
            --collect-all langgraph `
            --collect-all langchain_core `
            --collect-submodules keyring `
            --collect-submodules uvicorn `
            --collect-submodules alembic `
            --add-data "$(Join-Path $repoRoot 'backend\alembic');alembic" `
            --add-data "$(Join-Path $repoRoot 'backend\alembic.ini');." `
            --hidden-import aiosqlite `
            --hidden-import icalendar `
            --distpath (Join-Path $outDir "tmp") `
            --workpath (Join-Path $outDir "work") `
            --specpath $outDir `
            "src/nexapilot/__main__.py"
    }

    Move-Item -Force (Join-Path $outDir "tmp\nexapilot-server.exe") `
        (Join-Path $outDir "nexapilot-server-$triple.exe")
} finally {
    Remove-Item -Recurse -Force (Join-Path $outDir "tmp") -ErrorAction SilentlyContinue
    Remove-Item -Recurse -Force (Join-Path $outDir "work") -ErrorAction SilentlyContinue
    Remove-Item -Force (Join-Path $outDir "nexapilot-server.spec") -ErrorAction SilentlyContinue
    Pop-Location
}

Write-Host "Sidecar written to $outDir\nexapilot-server-$triple.exe"
