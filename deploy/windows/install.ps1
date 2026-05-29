<#
.SYNOPSIS
    OpenJarvis native Windows installer.

.DESCRIPTION
    Phase-1 of the native-Windows-support RFC (#298). Mirrors the
    behavior of scripts/install/install.sh (the curl-pipe-bash installer
    for Linux/WSL2/macOS) but for native Windows PowerShell — no WSL,
    no Docker, no MSYS2.

    Steps:
      1. Refuse non-Windows / Windows < 10.
      2. Check Python 3.10 — 3.13 on PATH (3.14 has no numpy wheels yet,
         see #432).
      3. Check git on PATH.
      4. Install uv (https://astral.sh/uv) if absent.
      5. Clone the OpenJarvis repository to $env:LOCALAPPDATA\OpenJarvis
         (override with $env:OPENJARVIS_HOME).
      6. Run `uv sync --extra server` so the FastAPI server entry point
         is importable.
      7. Optionally register the scheduled-task service (see
         deploy/windows/jarvis-service.ps1).

    Usage (one-liner):
      irm https://open-jarvis.github.io/OpenJarvis/install.ps1 | iex

    Usage (file invocation, supports flags):
      irm https://open-jarvis.github.io/OpenJarvis/install.ps1 -OutFile install.ps1
      .\install.ps1 -SkipService

    Flags (when running the file directly):
      -SkipService    Don't prompt for / install the scheduled task.
      -Service        Install the scheduled task without prompting.
      -Force          Re-run all steps even if already done.

    Under `irm | iex` the param block is unreachable (Invoke-Expression
    can't pass named args into a piped script string), so the same knobs
    are honored via env vars when the corresponding flag is absent:
      $env:OPENJARVIS_SKIP_SERVICE = '1'
      $env:OPENJARVIS_SERVICE      = '1'
      $env:OPENJARVIS_FORCE        = '1'

.NOTES
    Loopback default: the scheduled-task service binds 127.0.0.1, so no
    API key is needed. To expose on the LAN, edit the registered task to
    pass `--host 0.0.0.0` AND set $env:OPENJARVIS_API_KEY (an
    unauthenticated 0.0.0.0 server refuses to start). See
    deploy/windows/README.md.
#>

[CmdletBinding()]
param(
    [switch] $SkipService,
    [switch] $Service,
    [switch] $Force
)

$ErrorActionPreference = 'Stop'

# Env-var fallback for the `irm | iex` path, where the param block is
# unreachable (see header comment). Any explicit -switch wins; env vars
# only fill in the gaps.
if (-not $SkipService -and $env:OPENJARVIS_SKIP_SERVICE) { $SkipService = $true }
if (-not $Service     -and $env:OPENJARVIS_SERVICE)      { $Service     = $true }
if (-not $Force       -and $env:OPENJARVIS_FORCE)        { $Force       = $true }

# ---------------------------------------------------------------------------
# Output helpers — coloured but plain enough for Constrained Language Mode.
# ---------------------------------------------------------------------------

function Write-Info  ($msg) { Write-Host "[info]  $msg" -ForegroundColor Cyan }
function Write-Ok    ($msg) { Write-Host "[ok]    $msg" -ForegroundColor Green }
function Write-Warn2 ($msg) { Write-Host "[warn]  $msg" -ForegroundColor Yellow }
function Write-Fail  ($msg) {
    Write-Host "[fail]  $msg" -ForegroundColor Red
    exit 1
}

# ---------------------------------------------------------------------------
# 1. OS check
# ---------------------------------------------------------------------------

Write-Info "Checking OS..."
if ($PSVersionTable.Platform -and $PSVersionTable.Platform -ne 'Win32NT') {
    Write-Fail "install.ps1 is for native Windows. On Linux/macOS use install.sh."
}

# Build number 17763 = Windows 10 1809 (the oldest LTS we test against).
$build = [System.Environment]::OSVersion.Version.Build
if ($build -lt 17763) {
    Write-Fail "Windows 10 1809 (build 17763) or newer is required. Detected build $build."
}
Write-Ok "Windows build $build"

# ---------------------------------------------------------------------------
# 2. Python check
# ---------------------------------------------------------------------------

function Get-PythonCommand {
    # Prefer `python3` (matches our cross-platform helper convention),
    # fall back to `python` (the Windows store / python.org default).
    foreach ($name in @('python3', 'python')) {
        $cmd = Get-Command $name -ErrorAction SilentlyContinue
        if ($cmd) { return $cmd.Source }
    }
    return $null
}

Write-Info "Checking Python (3.10 - 3.13)..."
$pythonExe = Get-PythonCommand
if (-not $pythonExe) {
    Write-Fail @"
Python 3.10 - 3.13 not found on PATH.

Install from https://python.org (check 'Add python.exe to PATH' during
install) or via winget:

    winget install Python.Python.3.13

Then re-run this installer.
"@
}

$verRaw = & $pythonExe --version 2>&1
$verMatch = [regex]::Match($verRaw, '(\d+)\.(\d+)\.(\d+)')
if (-not $verMatch.Success) {
    Write-Fail "Could not parse Python version from: $verRaw"
}
$pyMajor = [int]$verMatch.Groups[1].Value
$pyMinor = [int]$verMatch.Groups[2].Value
if ($pyMajor -ne 3 -or $pyMinor -lt 10 -or $pyMinor -gt 13) {
    Write-Fail @"
Found Python $pyMajor.$pyMinor at $pythonExe, but OpenJarvis requires
3.10 - 3.13. Python 3.14 has no numpy Windows wheels yet (#432, will
re-open once numpy ships cp314).
"@
}
Write-Ok "Python $pyMajor.$pyMinor ($pythonExe)"

# ---------------------------------------------------------------------------
# 3. git check
# ---------------------------------------------------------------------------

Write-Info "Checking git..."
$gitExe = (Get-Command git -ErrorAction SilentlyContinue).Source
if (-not $gitExe) {
    Write-Fail @"
git not found on PATH.

Install via winget:

    winget install Git.Git

or download from https://git-scm.com, then re-run this installer.
"@
}
Write-Ok "git ($gitExe)"

# ---------------------------------------------------------------------------
# 4. uv check / install
# ---------------------------------------------------------------------------

Write-Info "Checking uv..."
$uvExe = (Get-Command uv -ErrorAction SilentlyContinue).Source
if (-not $uvExe) {
    Write-Info "Installing uv via astral.sh/uv (official PowerShell installer)..."
    try {
        Invoke-RestMethod -Uri 'https://astral.sh/uv/install.ps1' -UseBasicParsing | Invoke-Expression
    } catch {
        Write-Fail "uv install failed: $($_.Exception.Message)"
    }
    # The astral installer puts uv at %USERPROFILE%\.local\bin\uv.exe and
    # adds that dir to the User PATH. The current process's PATH isn't
    # refreshed automatically — prepend the install dir so the rest of
    # this script picks it up.
    $uvDir = Join-Path $env:USERPROFILE '.local\bin'
    if (Test-Path (Join-Path $uvDir 'uv.exe')) {
        $env:Path = "$uvDir;$env:Path"
    }
    $uvExe = (Get-Command uv -ErrorAction SilentlyContinue).Source
    if (-not $uvExe) {
        Write-Fail "uv installed but isn't on PATH. Re-open a fresh PowerShell and re-run."
    }
}
Write-Ok "uv ($uvExe)"

# ---------------------------------------------------------------------------
# 5. Clone the repo
# ---------------------------------------------------------------------------

$installRoot = if ($env:OPENJARVIS_HOME) {
    $env:OPENJARVIS_HOME
} else {
    Join-Path $env:LOCALAPPDATA 'OpenJarvis'
}
$srcDir = Join-Path $installRoot 'src'

Write-Info "Install root: $installRoot"

if (-not (Test-Path $installRoot)) {
    New-Item -ItemType Directory -Path $installRoot | Out-Null
}

$repoUrl = if ($env:OPENJARVIS_REPO_URL) {
    $env:OPENJARVIS_REPO_URL
} else {
    'https://github.com/open-jarvis/OpenJarvis.git'
}

if (Test-Path (Join-Path $srcDir '.git')) {
    if ($Force) {
        Write-Info "Force: pulling latest from $repoUrl..."
        & $gitExe -C $srcDir pull --ff-only
        if ($LASTEXITCODE -ne 0) { Write-Fail "git pull failed" }
    } else {
        Write-Ok "Repository already cloned (use -Force to update)"
    }
} else {
    Write-Info "Cloning $repoUrl..."
    & $gitExe clone --depth 1 $repoUrl $srcDir
    if ($LASTEXITCODE -ne 0) { Write-Fail "git clone failed" }
    Write-Ok "Cloned to $srcDir"
}

# ---------------------------------------------------------------------------
# 6. uv sync --extra server
# ---------------------------------------------------------------------------

Write-Info "Running 'uv sync --extra server' in $srcDir (this can take a few minutes)..."
Push-Location $srcDir
try {
    & $uvExe sync --extra server
    if ($LASTEXITCODE -ne 0) {
        Write-Fail "uv sync failed with exit code $LASTEXITCODE. Check the output above."
    }
} finally {
    Pop-Location
}
Write-Ok "Dependencies installed"

# ---------------------------------------------------------------------------
# 7. Optional: register the scheduled-task service
# ---------------------------------------------------------------------------

$serviceScript = Join-Path $srcDir 'deploy\windows\jarvis-service.ps1'
$shouldInstallService = $false

if ($Service) {
    $shouldInstallService = $true
} elseif ($SkipService) {
    $shouldInstallService = $false
} else {
    # Interactive prompt only when there's a real user at the keyboard
    # AND stdin isn't piped. [Environment]::UserInteractive is the
    # canonical PowerShell idiom for "is this a user session" (false for
    # services, scheduled tasks, etc); we additionally guard against the
    # `irm | iex` case where stdin is redirected.
    $isInteractive = [Environment]::UserInteractive `
        -and -not [System.Console]::IsInputRedirected
    if ($isInteractive) {
        $reply = Read-Host "Register OpenJarvis as a Windows scheduled task (auto-start at logon, loopback only)? [y/N]"
        $shouldInstallService = ($reply -match '^[yY]')
    } else {
        Write-Warn2 "Non-interactive install — skipping scheduled-task setup."
        Write-Warn2 "To register the service later, run:"
        Write-Warn2 "  powershell -ExecutionPolicy Bypass -File `"$serviceScript`" install"
    }
}

if ($shouldInstallService) {
    if (-not (Test-Path $serviceScript)) {
        Write-Fail "Service script not found at $serviceScript (the clone may be missing files; try -Force)."
    }
    Write-Info "Installing scheduled task..."
    & powershell -ExecutionPolicy Bypass -File $serviceScript install -InstallRoot $installRoot
    if ($LASTEXITCODE -ne 0) {
        Write-Fail "Scheduled task setup failed."
    }
    Write-Ok "Scheduled task 'OpenJarvis' registered (loopback default)."
}

# ---------------------------------------------------------------------------
# 8. Final message
# ---------------------------------------------------------------------------

Write-Host ""
Write-Host "  ┌──────────────────────────────────┐" -ForegroundColor Green
Write-Host "  │   OpenJarvis install complete    │" -ForegroundColor Green
Write-Host "  └──────────────────────────────────┘" -ForegroundColor Green
Write-Host ""
Write-Host "  Repo:    $srcDir"
Write-Host "  Run it:  cd `"$srcDir`"; uv run jarvis serve"
if ($shouldInstallService) {
    Write-Host "  Service: schtasks /Query /TN OpenJarvis     (status)"
    Write-Host "           powershell -File `"$serviceScript`" uninstall    (remove)"
}
Write-Host ""
Write-Host "  Docs:    https://open-jarvis.github.io/OpenJarvis/"
Write-Host ""
