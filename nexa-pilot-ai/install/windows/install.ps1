# NexaPilot AI - one-step installer for Windows 10/11 (64-bit).
#
# From PowerShell in this folder:
#   .\install.ps1                       install a pre-built .exe/.msi next to this script
#   .\install.ps1 -InstallerPath C:\path\NexaPilot-setup.exe
#   .\install.ps1 -Build                build from source, then install
#   .\install.ps1 -Build -InstallDeps   install build tools (winget)
#
# Running from \\wsl.localhost or a network share is supported: a source build is
# copied to %LOCALAPPDATA%\NexaPilot\build first.
#
# Uninstall: double-click 'Uninstall NexaPilot AI.cmd' or run .\uninstall.ps1
param(
    [switch]$Build,
    [switch]$InstallDeps,
    [switch]$NoLaunch,
    [switch]$Silent,
    [Parameter(Position = 0)]
    [string]$InstallerPath,
    [string]$CertificateThumbprint,
    [string]$PfxPath,
    [string]$TimestampUrl = "http://timestamp.digicert.com"
)

$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$repo = $null
$repoCandidate = Join-Path $here "..\.."
if (Test-Path -LiteralPath $repoCandidate) {
    $repo = [System.IO.Path]::GetFullPath($repoCandidate)
}
$AppName = "NexaPilot AI"
$script:Step = 0
$script:Started = Get-Date
$script:ImportedCertificate = $null
$tempDir = $env:TEMP
if (-not $tempDir) { $tempDir = [System.IO.Path]::GetTempPath() }
$script:LogFile = Join-Path $tempDir ("nexapilot-install-{0}.log" -f (Get-Date -Format "yyyyMMdd-HHmmss"))

function Write-Log($msg) {
    $script:Step++
    $elapsed = [int]((Get-Date) - $script:Started).TotalSeconds
    $line = "[{0:HH:mm:ss} +{1}s] [{2}] {3}" -f (Get-Date), $elapsed, $script:Step, $msg
    Write-Host "`n==> $line" -ForegroundColor Cyan
    Add-Content -LiteralPath $script:LogFile -Value $line -ErrorAction SilentlyContinue
}

function Write-Detail($msg) {
    Write-Host "    $msg" -ForegroundColor DarkGray
    Add-Content -LiteralPath $script:LogFile -Value "    $msg" -ErrorAction SilentlyContinue
}

function Die($msg) {
    Write-Host "`nERROR: $msg" -ForegroundColor Red
    Add-Content -LiteralPath $script:LogFile -Value "ERROR: $msg" -ErrorAction SilentlyContinue
    Write-Host "Log: $script:LogFile" -ForegroundColor Yellow
    exit 1
}

function Assert-ExitCode {
    param(
        [string]$Label,
        [int]$Code
    )
    if ($Code -ne 0) { Die "$Label failed (exit $Code)." }
}

function Invoke-Native {
    param(
        [string]$Label,
        [scriptblock]$Command,
        [switch]$AllowFailure
    )
    $previous = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        & $Command 2>&1 | ForEach-Object { Write-Host $_ }
        $code = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previous
    }
    if ($code -ne 0) {
        if ($AllowFailure) { Write-Detail "warning: $Label exited with code $code (continuing)" }
        else { Die "$Label failed (exit $code)." }
    }
}

function Resolve-SigningCertificate {
    if (-not $CertificateThumbprint -and -not $PfxPath) { return $null }

    if ($CertificateThumbprint) {
        $clean = ($CertificateThumbprint -replace '[^0-9A-Fa-f]', '').ToUpperInvariant()
        $cert = Get-Item -LiteralPath "Cert:\CurrentUser\My\$clean" -ErrorAction SilentlyContinue
        if (-not $cert) {
            Die "Code-signing certificate $clean was not found in Cert:\CurrentUser\My. Import the .pfx into that store or pass -PfxPath."
        }
        if (-not $cert.HasPrivateKey) { Die "Certificate $clean has no usable private key in this user's store." }
        return $cert
    }

    if (-not (Test-Path -LiteralPath $PfxPath -PathType Leaf)) { Die "PfxPath not found: $PfxPath" }
    if (-not (Get-Command Import-PfxCertificate -ErrorAction SilentlyContinue)) {
        Die "Import-PfxCertificate is unavailable. Import the .pfx into Cert:\CurrentUser\My and use -CertificateThumbprint instead."
    }
    $password = Read-Host -AsSecureString "Password for $PfxPath"
    $imported = Import-PfxCertificate -FilePath $PfxPath -CertStoreLocation "Cert:\CurrentUser\My" -Password $password -ErrorAction Stop
    $cert = @($imported) | Where-Object { $_.HasPrivateKey } | Select-Object -First 1
    if (-not $cert) { $cert = @($imported) | Select-Object -First 1 }
    if (-not $cert) { Die "No certificate could be imported from $PfxPath." }
    $script:ImportedCertificate = $cert
    return $cert
}

function Remove-ImportedCertificate {
    if ($script:ImportedCertificate) {
        Remove-Item -LiteralPath $script:ImportedCertificate.PSPath -ErrorAction SilentlyContinue
        $script:ImportedCertificate = $null
    }
}

function New-TauriSigningConfig {
    param($Certificate)

    $thumb = ($Certificate.Thumbprint -replace '\s', '')
    $config = @{
        bundle = @{
            windows = @{
                certificateThumbprint = $thumb
                digestAlgorithm = "sha256"
                timestampUrl = $TimestampUrl
            }
        }
    } | ConvertTo-Json -Depth 6

    $path = Join-Path $tempDir ("nexapilot-signing-{0}.json" -f ([guid]::NewGuid().ToString("N")))
    Set-Content -LiteralPath $path -Value $config -Encoding ASCII
    return $path
}

function Sign-Package {
    param(
        $File,
        $Certificate,
        [switch]$InstallerOnly
    )
    if (-not $Certificate) { return }

    Write-Log "Signing $($File.Name) with $($Certificate.Subject)"
    $sig = Set-AuthenticodeSignature -LiteralPath $File.FullName -Certificate $Certificate -TimestampServer $TimestampUrl -ErrorAction Stop
    if ($sig.Status -ne "Valid") { Die "Signing failed: $($sig.Status) - $($sig.StatusMessage)" }
    Write-Detail "signature: Valid"
    if ($InstallerOnly) {
        Write-Detail "note: only the installer was signed; Smart App Control also checks the installed app, so use -Build for full signing."
    }
}

function Write-SignatureInfo {
    param($File)

    $status = "unknown"
    try {
        if (Get-Command Get-AuthenticodeSignature -ErrorAction SilentlyContinue) {
            $sig = Get-AuthenticodeSignature -LiteralPath $File.FullName -ErrorAction Stop
            $status = $sig.Status.ToString()
            if ($sig.SignerCertificate) {
                Write-Detail "signature: $status (publisher: $($sig.SignerCertificate.Subject))"
            } else {
                Write-Detail "signature: $status (no publisher certificate)"
            }
        }
    } catch {
        Write-Detail "signature: could not be read"
    }

    $policy = $null
    try {
        $policy = (Get-ItemProperty -Path "HKLM:\SYSTEM\CurrentControlSet\Control\CI\Policy" `
            -Name "VerifiedAndReputablePolicyState" -ErrorAction Stop).VerifiedAndReputablePolicyState
    } catch { }

    if ($policy -eq 1) {
        Write-Host "    Smart App Control is ON: it blocks unsigned/untrusted apps and has no per-app allow." -ForegroundColor Yellow
        Write-Host "    Sign with a CA-issued code-signing certificate (-CertificateThumbprint/-PfxPath) or turn Smart App Control off." -ForegroundColor Yellow
    } elseif ($policy -eq 2) {
        Write-Detail "Smart App Control is in evaluation mode; it reports blocks but does not enforce them."
    }
}

function Find-NexaPackage {
    $result = @{ Installer = $null; Msi = $null }

    if ($InstallerPath) {
        if (-not (Test-Path -LiteralPath $InstallerPath -PathType Leaf)) { Die "InstallerPath is not a file: $InstallerPath" }
        $picked = Get-Item -LiteralPath $InstallerPath
        if ($picked.Extension -notin @(".exe", ".msi")) {
            Die "InstallerPath must be a Windows .exe or .msi file (got $($picked.Extension)): $($picked.FullName)"
        }
        if ($picked.Extension -ieq ".msi") { $result.Msi = $picked } else { $result.Installer = $picked }
        return $result
    }

    $searchDirs = @($here)
    if ($repo) {
        $searchDirs += (Join-Path $repo "desktop\src-tauri\target\release\bundle\nsis")
        $searchDirs += (Join-Path $repo "desktop\src-tauri\target\release\bundle\msi")
    }
    $existing = @($searchDirs | Where-Object { Test-Path -LiteralPath $_ })
    if ($existing.Count -eq 0) { return $result }

    $result.Installer = Get-ChildItem -Path $existing -Filter "NexaPilot*.exe" -File -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if (-not $result.Installer) {
        $result.Msi = Get-ChildItem -Path $existing -Filter "NexaPilot*.msi" -File -ErrorAction SilentlyContinue |
            Sort-Object LastWriteTime -Descending | Select-Object -First 1
    }
    return $result
}

function Build-From-Source {
    if (-not $repo) { Die "Source checkout not found (looked for $repoCandidate)." }

    if ($InstallDeps) {
        if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
            Die "winget is not available. Install Rust, Node.js, and uv manually, or use install/windows/install.ps1 -Build."
        }
        Write-Log "Installing build dependencies via winget"
        Write-Detail "running: winget install Rustlang.Rustup"
        Invoke-Native "winget Rust" {
            winget install --id Rustlang.Rustup -e --source winget --accept-package-agreements --accept-source-agreements
        } -AllowFailure
        Write-Detail "running: winget install OpenJS.NodeJS.LTS"
        Invoke-Native "winget Node.js" {
            winget install --id OpenJS.NodeJS.LTS -e --source winget --accept-package-agreements --accept-source-agreements
        } -AllowFailure
        Write-Detail "running: winget install Git.Git"
        Invoke-Native "winget Git" {
            winget install --id Git.Git -e --source winget --accept-package-agreements --accept-source-agreements
        } -AllowFailure
        Write-Detail "running: winget install Microsoft.VisualStudio.2022.BuildTools (C++ workload, ~5 GB)"
        Invoke-Native "winget Visual Studio Build Tools" {
            winget install --id Microsoft.VisualStudio.2022.BuildTools -e --source winget --accept-package-agreements --accept-source-agreements --silent --override "--wait --quiet --norestart --nocache --add Microsoft.VisualStudio.Workload.VCTools --includeRecommended"
        } -AllowFailure
        $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" +
            [System.Environment]::GetEnvironmentVariable("Path", "User")
        if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
            Write-Detail "running: uv installer"
            irm https://astral.sh/uv/install.ps1 | iex
            $env:Path += ";$env:USERPROFILE\.local\bin"
        }
    }

    $cargoBin = Join-Path $env:USERPROFILE ".cargo\bin"
    if ((Test-Path -LiteralPath $cargoBin) -and ($env:Path -notlike "*$cargoBin*")) {
        $env:Path = "$cargoBin;$env:Path"
    }
    $uvBin = Join-Path $env:USERPROFILE ".local\bin"
    if ((Test-Path -LiteralPath $uvBin) -and ($env:Path -notlike "*$uvBin*")) {
        $env:Path = "$uvBin;$env:Path"
    }

    $missing = @()
    foreach ($tool in @("node", "npm", "cargo", "uv")) {
        if (-not (Get-Command $tool -ErrorAction SilentlyContinue)) { $missing += $tool }
    }
    if ($missing.Count -gt 0) {
        Die "Missing build tools: $($missing -join ', '). Run: .\install.ps1 -Build -InstallDeps"
    }

    Write-Log "Installing JavaScript dependencies (this can take a few minutes)"
    Write-Detail "running: npm --prefix frontend install"
    Invoke-Native "npm install frontend" {
        npm --prefix (Join-Path $repo "frontend") install
    }
    Write-Detail "running: npm --prefix desktop install"
    Invoke-Native "npm install desktop" {
        npm --prefix (Join-Path $repo "desktop") install
    }

    $sidecarScript = Join-Path $repo "desktop\scripts\build-sidecar.ps1"
    if (-not (Test-Path -LiteralPath $sidecarScript)) { Die "Missing build script: $sidecarScript" }
    Write-Log "Building the backend sidecar (PyInstaller, several minutes)"
    & $sidecarScript
    Assert-ExitCode "build-sidecar.ps1" $LASTEXITCODE

    Write-Log "Building the desktop bundle (NSIS, this can take 10-20 minutes)"
    $signingCert = Resolve-SigningCertificate
    $signingConfig = $null
    try {
        if ($signingCert) {
            $signingConfig = New-TauriSigningConfig $signingCert
            Write-Log "Code signing enabled for the app and installer: $($signingCert.Subject)"
        }
        Push-Location (Join-Path $repo "desktop")
        try {
            if ($signingConfig) {
                Write-Detail "running: npx tauri build --bundles nsis --config <signing>"
                Invoke-Native "npx tauri build" {
                    npx tauri build --bundles nsis --config $signingConfig
                }
            } else {
                Write-Detail "running: npx tauri build --bundles nsis (unsigned)"
                Invoke-Native "npx tauri build" {
                    npx tauri build --bundles nsis
                }
            }
        } finally {
            Pop-Location
        }
    } finally {
        if ($signingConfig) { Remove-Item -LiteralPath $signingConfig -ErrorAction SilentlyContinue }
        Remove-ImportedCertificate
    }
}

function Test-UncPath([string]$Path) {
    return [bool]($Path -match '^(\\\\|//)')
}

function Test-RequiresLocalStage([string]$Path) {
    if (Test-UncPath $Path) { return $true }
    try {
        $root = [System.IO.Path]::GetPathRoot($Path)
        $drive = New-Object System.IO.DriveInfo $root
        return $drive.DriveType -ne [System.IO.DriveType]::Fixed
    } catch {
        return $false
    }
}

function Copy-RepoToLocalStage {
    param([string]$SourceRepo)

    if (-not (Get-Command robocopy -ErrorAction SilentlyContinue)) {
        Die "robocopy is unavailable. Copy the repo to a local folder (for example C:\src\nexa-pilot-ai) and run install.ps1 there."
    }

    $stage = Join-Path $env:LOCALAPPDATA "NexaPilot\build\src"
    Write-Log "Copying the source tree to a local build folder"
    Write-Detail "from: $SourceRepo"
    Write-Detail "to:   $stage"
    Write-Detail "node_modules, .venv, target, dist and caches are skipped; a 9p/WSL copy can take a minute."

    New-Item -ItemType Directory -Force -Path $stage | Out-Null
    $excludeDirs = @(
        "node_modules", ".venv", "venv", "target", "binaries", ".git", "__pycache__",
        ".mypy_cache", ".pytest_cache", ".ruff_cache", "dist", "htmlcov"
    )
    $robocopyArgs = @($SourceRepo, $stage, "/MIR", "/R:1", "/W:1", "/NFL", "/NDL", "/NJH", "/NP", "/XD") + $excludeDirs
    $previous = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        & robocopy @robocopyArgs | ForEach-Object { Write-Host "    $_" -ForegroundColor DarkGray }
        $code = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previous
    }
    if ($code -ge 8) { Die "Copying the source to $stage failed (robocopy exit $code)." }

    Remove-Item -LiteralPath (Join-Path $stage "desktop\src-tauri\binaries") -Recurse -Force -ErrorAction SilentlyContinue
    return $stage
}

function Install-Package {
    param($Package)
    if ($Package.Installer) {
        $file = $Package.Installer
        Write-Log "Installing $($file.Name) (per-user)"
        Write-Detail "A SmartScreen prompt can appear for unsigned builds; choose More info > Run anyway."
        try { Unblock-File -LiteralPath $file.FullName -ErrorAction Stop } catch { }
        if ($file.FullName -match '^\\\\') {
            $local = Join-Path $env:TEMP $file.Name
            Write-Detail "Copying to $local first (Windows cannot reliably run installers from a network path)"
            Copy-Item -LiteralPath $file.FullName -Destination $local -Force
            try { Unblock-File -LiteralPath $local -ErrorAction Stop } catch { }
            $file = Get-Item -LiteralPath $local
        }
        Write-SignatureInfo $file
        $sw = [System.Diagnostics.Stopwatch]::StartNew()
        if ($Silent) {
            Write-Detail "running: setup /S (silent)"
            $proc = Start-Process -FilePath $file.FullName -ArgumentList "/S" -Wait -PassThru
        } else {
            $proc = Start-Process -FilePath $file.FullName -Wait -PassThru
        }
        $sw.Stop()
        if ($proc.ExitCode -eq 1223) { Die "Installation was cancelled." }
        if ($proc.ExitCode -ne 0) { Die "Installer exited with code $($proc.ExitCode)." }
        Write-Detail "installer finished in $([int]$sw.Elapsed.TotalSeconds)s"
        return
    }

    if ($Package.Msi) {
        $file = $Package.Msi
        Write-Log "Installing $($file.Name)"
        Write-SignatureInfo $file
        $sw = [System.Diagnostics.Stopwatch]::StartNew()
        $proc = Start-Process msiexec -ArgumentList @("/i", ('"{0}"' -f $file.FullName), "/passive", "/norestart") -Wait -PassThru
        $sw.Stop()
        if ($proc.ExitCode -eq 1602) { Die "Installation was cancelled." }
        if ($proc.ExitCode -eq 3010) { Write-Detail "A reboot is required to finish the installation." }
        elseif ($proc.ExitCode -ne 0) { Die "msiexec exited with code $($proc.ExitCode)." }
        Write-Detail "installer finished in $([int]$sw.Elapsed.TotalSeconds)s"
        return
    }

    Die "No installer to run."
}

Write-Host "NexaPilot AI installer" -ForegroundColor White
Write-Detail "Log: $script:LogFile"

if ($env:OS -ne "Windows_NT") { Die "This installer is for Windows. Use install/linux/install.sh on Linux." }

if ($here -match '^\\\\') {
    Write-Host "`nNOTICE: running from a network/WSL path:" -ForegroundColor Yellow
    Write-Host "         $here" -ForegroundColor Yellow
    Write-Host "         Installing an existing .exe/.msi is fine. A source build will be copied" -ForegroundColor Yellow
    Write-Host "         to %LOCALAPPDATA%\NexaPilot\build automatically before it runs." -ForegroundColor Yellow
    Add-Content -LiteralPath $script:LogFile -Value "NOTICE: running from network path $here" -ErrorAction SilentlyContinue
}

try {
    $package = Find-NexaPackage

    if (-not $package.Installer -and -not $package.Msi -and -not $Build) {
        $missing = @(@("node", "cargo", "uv") | Where-Object { -not (Get-Command $_ -ErrorAction SilentlyContinue) })
        if ($missing.Count -eq 0) {
            Write-Log "No pre-built installer found; build tools detected, so building from source"
            $Build = $true
        } else {
            Die "No NexaPilot*.exe/.msi found in $here. Put the Windows setup there, or run: .\install.ps1 -InstallerPath `"C:\path\to\NexaPilot AI_0.1.0_x64-setup.exe`" (the Linux .deb cannot be installed on Windows), or build with -Build -InstallDeps."
        }
    }

    if ($Build) {
        if (-not $repo) {
            Die "Source checkout not found next to this script. Put the repo here or pass -InstallerPath to a pre-built setup."
        }
        if ((Test-RequiresLocalStage $repo) -or (Test-RequiresLocalStage $here)) {
            $stage = Copy-RepoToLocalStage -SourceRepo $repo
            $here = Join-Path $stage "install\windows"
            $repo = $stage
        }
        Build-From-Source
        $package = Find-NexaPackage
    }

    if (-not $package.Installer -and -not $package.Msi) {
        Die "The build finished but no NexaPilot*.exe was produced under desktop\src-tauri\target\release\bundle\nsis."
    }

    if (-not $Build -and ($CertificateThumbprint -or $PfxPath)) {
        $cert = Resolve-SigningCertificate
        try {
            if ($package.Installer) { Sign-Package -File $package.Installer -Certificate $cert -InstallerOnly }
            else { Sign-Package -File $package.Msi -Certificate $cert -InstallerOnly }
        } finally {
            Remove-ImportedCertificate
        }
    }

    Install-Package $package
} catch {
    Die $_.Exception.Message
}

Write-Log "Done. Launch $AppName from the Start Menu."
Write-Host "Log saved to $script:LogFile" -ForegroundColor DarkGray

if (-not $NoLaunch) {
    $lnk = "$env:APPDATA\Microsoft\Windows\Start Menu\Programs\$AppName.lnk"
    if (Test-Path -LiteralPath $lnk) {
        Start-Process $lnk
    } else {
        $candidates = @(
            (Join-Path $env:LOCALAPPDATA "$AppName\nexapilot-desktop.exe"),
            (Join-Path $env:LOCALAPPDATA "Programs\$AppName\nexapilot-desktop.exe"),
            (Join-Path $env:LOCALAPPDATA "$AppName\$AppName.exe"),
            (Join-Path $env:LOCALAPPDATA "Programs\$AppName\$AppName.exe")
        )
        $exe = $candidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
        if ($exe) { Start-Process $exe }
    }
}

Write-Host "`nUninstall: double-click 'Uninstall NexaPilot AI.cmd' (or run .\uninstall.ps1 -Purge)"
