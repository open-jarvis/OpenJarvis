<#
.SYNOPSIS
    OpenJarvis native Windows installer.

.DESCRIPTION
    Phase-1 of the native-Windows-support RFC (#298). Mirrors the
    behavior of scripts/install/install.sh (the curl-pipe-bash installer
    for Linux/WSL2/macOS) but for native Windows PowerShell - no WSL,
    no Docker, no MSYS2.

    Steps:
      1. Refuse non-Windows / Windows < 10.
      2. Check Python 3.10 - 3.13 on PATH (3.14 has no numpy wheels yet,
         see #432).
      3. Check git on PATH.
      4. Install uv (https://astral.sh/uv) if absent.
      5. Clone the OpenJarvis repository to $env:LOCALAPPDATA\OpenJarvis
         (override with $env:OPENJARVIS_HOME).
      6. Run `uv sync --extra desktop` so the FastAPI server and speech
         backend are importable.
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
# Output helpers - coloured but plain enough for Constrained Language Mode.
# ---------------------------------------------------------------------------

function Write-Info  ($msg) { Write-Host "[info]  $msg" -ForegroundColor Cyan }
function Write-Ok    ($msg) { Write-Host "[ok]    $msg" -ForegroundColor Green }
function Write-Warn2 ($msg) { Write-Host "[warn]  $msg" -ForegroundColor Yellow }
function Write-Fail  ($msg) {
    Write-Host "[fail]  $msg" -ForegroundColor Red
    exit 1
}

# ---------------------------------------------------------------------------
# Shared helpers - winget bootstrap + PATH refresh
# ---------------------------------------------------------------------------

# Pull the latest Machine + User PATH from the registry into the current
# PowerShell session. Tools installed by `winget install` (Python, git,
# Ollama, etc.) update the User PATH, but the running process inherits
# the parent shell's environment - so without this refresh the just-
# installed tool stays invisible to subsequent `Get-Command` calls.
#
# CRITICAL: registry PATH entries can be REG_EXPAND_SZ (with literal
# `%VAR%` placeholders); the Python.org installer in per-user mode adds
# entries like `%LOCALAPPDATA%\Programs\Python\Python313\` unexpanded.
# `GetEnvironmentVariable` returns the raw string and PowerShell does
# NOT auto-expand on assignment to `$env:Path`, so `Get-Command python`
# would miss the just-installed binary. Expand explicitly.
function Update-PathFromRegistry {
    $machinePath = [System.Environment]::GetEnvironmentVariable('Path', 'Machine')
    $userPath    = [System.Environment]::GetEnvironmentVariable('Path', 'User')
    $combined    = "$machinePath;$userPath"
    $env:Path = [System.Environment]::ExpandEnvironmentVariables($combined)
}

# Bootstrap a tool by winget id. Returns the resolved command source on
# success, $null on failure. Caller decides whether failure is fatal.
function Install-WithWinget {
    param(
        [string] $WingetId,    # e.g. 'Python.Python.3.13'
        [string] $CommandName  # e.g. 'python' or 'git'
    )
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
        # Windows 10 pre-2004 / Windows Server / locked-down corporate
        # images may not have winget. Fall back to the caller's manual
        # instructions.
        return $null
    }
    Write-Info "  Installing $WingetId via winget (silent)..."
    & winget install --id $WingetId --silent --accept-source-agreements --accept-package-agreements 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Write-Warn2 "  winget install $WingetId exited $LASTEXITCODE"
        return $null
    }
    Update-PathFromRegistry
    $cmd = Get-Command $CommandName -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    return $null
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
    Write-Info "Python not on PATH - attempting auto-install via winget..."
    $pythonExe = Install-WithWinget -WingetId 'Python.Python.3.13' -CommandName 'python'
    if (-not $pythonExe) {
        Write-Fail @"
Python 3.10 - 3.13 not found and auto-install via winget failed.

Install manually from https://python.org (check 'Add python.exe to PATH'
during install) or via winget:

    winget install Python.Python.3.13

Then re-run this installer.
"@
    }
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
    Write-Info "git not on PATH - attempting auto-install via winget..."
    $gitExe = Install-WithWinget -WingetId 'Git.Git' -CommandName 'git'
    if (-not $gitExe) {
        Write-Fail @"
git not found and auto-install via winget failed.

Install manually via winget:

    winget install Git.Git

or download from https://git-scm.com, then re-run this installer.
"@
    }
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
    # refreshed automatically - prepend the install dir so the rest of
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
# 6. uv sync --extra desktop
# ---------------------------------------------------------------------------

Write-Info "Running 'uv sync --extra desktop' in $srcDir (this can take a few minutes)..."
Push-Location $srcDir
try {
    & $uvExe sync --extra desktop
    if ($LASTEXITCODE -ne 0) {
        Write-Fail "uv sync failed with exit code $LASTEXITCODE. Check the output above."
    }
} finally {
    Pop-Location
}
Write-Ok "Dependencies installed"

# ---------------------------------------------------------------------------
# 7. Ollama - install + start + wait for daemon
# ---------------------------------------------------------------------------

Write-Info "Checking Ollama..."
$ollamaExe = (Get-Command ollama -ErrorAction SilentlyContinue).Source
if (-not $ollamaExe) {
    Write-Info "  Ollama not on PATH - downloading the official installer (~150 MB)..."
    $ollamaSetup = Join-Path $env:TEMP 'OllamaSetup.exe'
    # SilentlyContinue is load-bearing in PS 5.1: the default progress
    # bar renderer slows Invoke-WebRequest down 30x on large downloads
    # (a known PS5.1 issue), turning a 30s download into 15+ minutes.
    $prevProgress = $ProgressPreference
    $ProgressPreference = 'SilentlyContinue'
    try {
        Invoke-WebRequest `
            -Uri 'https://ollama.com/download/OllamaSetup.exe' `
            -OutFile $ollamaSetup `
            -UseBasicParsing
    } catch {
        Remove-Item $ollamaSetup -ErrorAction SilentlyContinue  # clean up partial download
        $ProgressPreference = $prevProgress
        Write-Fail "Ollama download failed: $($_.Exception.Message)`nInstall manually from https://ollama.com, then re-run."
    } finally {
        $ProgressPreference = $prevProgress
    }
    # OllamaSetup.exe is built with NSIS, whose silent-install flag is
    # /S (uppercase). The Inno-Setup-style /silent would open the GUI
    # and hang `Start-Process -Wait` indefinitely.
    Write-Info "  Running OllamaSetup.exe /S (this can take a minute)..."
    Start-Process -FilePath $ollamaSetup -ArgumentList '/S' -Wait
    Remove-Item $ollamaSetup -ErrorAction SilentlyContinue
    Update-PathFromRegistry
    $ollamaExe = (Get-Command ollama -ErrorAction SilentlyContinue).Source
    if (-not $ollamaExe) {
        Write-Fail "Ollama installer ran but 'ollama' isn't on PATH. Open a fresh PowerShell and re-run, or install manually from https://ollama.com."
    }
}
Write-Ok "Ollama ($ollamaExe)"

# Make sure the daemon is actually responsive before pulling. The Ollama
# Windows installer launches the tray app at install time, but on a re-
# run with an existing install the daemon may not be running yet.
Write-Info "Waiting for Ollama daemon..."
$ollamaReady = $false
for ($i = 0; $i -lt 60; $i++) {
    # 'ollama list' writes to stderr until the daemon is reachable; under
    # $ErrorActionPreference='Stop' the 2>&1 merge surfaces that as a
    # terminating NativeCommandError that would abort the whole install on
    # the very first probe. Swallow it and rely on $LASTEXITCODE so the
    # Start-Process serve fallback below actually runs (issue #522).
    try { & $ollamaExe list 2>&1 | Out-Null } catch { }
    if ($LASTEXITCODE -eq 0) {
        $ollamaReady = $true
        break
    }
    if ($i -eq 5) {
        # Daemon clearly isn't auto-running - start it ourselves. Ollama
        # for Windows uses the tray app `ollama app.exe`; falling back to
        # `ollama serve` works headless.
        Start-Process -FilePath $ollamaExe -ArgumentList 'serve' -WindowStyle Hidden -ErrorAction SilentlyContinue
    }
    Start-Sleep -Seconds 1
}
if (-not $ollamaReady) {
    Write-Warn2 "Ollama daemon didn't become ready in 60s. Continuing - bg-orchestrator will retry later."
}

# ---------------------------------------------------------------------------
# 8. Pull a starter model (qwen3.5:2b - ~1.5 GB)
# ---------------------------------------------------------------------------

$modelPullOk = $false
if ($ollamaReady) {
    Write-Info "Pulling qwen3.5:2b (~1.5 GB) so 'jarvis' works on first run..."
    & $ollamaExe pull 'qwen3.5:2b'
    if ($LASTEXITCODE -eq 0) {
        $modelPullOk = $true
        Write-Ok "Starter model ready"
    } else {
        Write-Warn2 "ollama pull failed; the bg-orchestrator will retry once Ollama is reachable."
    }
} else {
    Write-Warn2 "Skipping model pull - daemon wasn't ready."
}

# ---------------------------------------------------------------------------
# 9. jarvis.cmd shim - so bare `jarvis` works in any new PowerShell
# ---------------------------------------------------------------------------

$binDir = Join-Path $installRoot 'bin'
$shimPath = Join-Path $binDir 'jarvis.cmd'

if (-not (Test-Path $binDir)) {
    New-Item -ItemType Directory -Path $binDir | Out-Null
}

# %~dp0 in a .cmd file resolves to the directory containing the script,
# so the shim is self-locating - moving %LOCALAPPDATA%\OpenJarvis won't
# break it as long as the user moves the whole tree. `uv` is resolved
# from PATH at runtime (astral installer adds it to User PATH); avoids
# pinning to the install-time uv.exe path which can shift on uv updates.
$shimContent = @"
@echo off
setlocal
set "SRC=%~dp0..\src"
uv run --project "%SRC%" jarvis %*
"@
Set-Content -Path $shimPath -Value $shimContent -Encoding ASCII

# Add %LOCALAPPDATA%\OpenJarvis\bin to User PATH if it isn't already
# there. The current process won't see it until restart - handled in the
# final banner.
#
# Compare against the EXPANDED form: a previous install may have written
# the entry as `%LOCALAPPDATA%\OpenJarvis\bin` (unexpanded) into User
# PATH, and a literal `-ieq` against the expanded `$binDir` would miss
# it and append a duplicate every re-run.
$userPath = [System.Environment]::GetEnvironmentVariable('Path', 'User')
$pathOnUser = $false
if ($userPath) {
    foreach ($entry in ($userPath -split ';')) {
        $expanded = [System.Environment]::ExpandEnvironmentVariables($entry)
        if ($expanded -ieq $binDir) { $pathOnUser = $true; break }
    }
}
$pathNeedsRefresh = $false
if (-not $pathOnUser) {
    $newUserPath = if ($userPath) { "$userPath;$binDir" } else { $binDir }
    [System.Environment]::SetEnvironmentVariable('Path', $newUserPath, 'User')
    $pathNeedsRefresh = $true
}
Write-Ok "jarvis shim installed at $shimPath"

# ---------------------------------------------------------------------------
# 10. Optional: register the scheduled-task service
# ---------------------------------------------------------------------------

$serviceScript = Join-Path $srcDir 'deploy\windows\jarvis-service.ps1'
$shouldInstallService = $false

# Pre-check admin if the user wants the service - Register-ScheduledTask
# requires elevation. We do this before the prompt so we don't ask "do
# you want the service?" only to fail with Access Denied after they say
# yes.
$isAdmin = ([Security.Principal.WindowsPrincipal] `
    [Security.Principal.WindowsIdentity]::GetCurrent()
).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)

if ($Service -and -not $isAdmin) {
    Write-Fail "-Service was requested, but this PowerShell is not elevated. Register-ScheduledTask needs admin rights - re-run from an elevated PowerShell, or drop -Service."
}
if ($Service) {
    $shouldInstallService = $true
} elseif ($SkipService) {
    $shouldInstallService = $false
} elseif (-not $isAdmin) {
    # Default to skip-with-explanation when we can't elevate, rather
    # than prompting and then failing at Register-ScheduledTask.
    Write-Warn2 "Skipping scheduled-task setup - this PowerShell is not elevated."
    Write-Warn2 "  Register-ScheduledTask requires admin. To install the service later:"
    Write-Warn2 "    Right-click PowerShell -> Run as administrator, then run:"
    Write-Warn2 "    powershell -ExecutionPolicy Bypass -File `"$serviceScript`" install"
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
        Write-Warn2 "Non-interactive install - skipping scheduled-task setup."
        Write-Warn2 "To register the service later, run (from an elevated PowerShell):"
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
Write-Host "  +----------------------------------+" -ForegroundColor Green
Write-Host "  |   OpenJarvis install complete    |" -ForegroundColor Green
Write-Host "  +----------------------------------+" -ForegroundColor Green
Write-Host ""
Write-Host "  Repo:    $srcDir"

# Tell the truth about what the user can run next, given (a) whether the
# starter model finished pulling and (b) whether the User-PATH update
# needs a fresh PowerShell to take effect.
$nextCmd = if ($modelPullOk) { 'jarvis' } else { 'jarvis doctor' }

if ($pathNeedsRefresh) {
    Write-Host ""
    Write-Host "  Run it:  open a NEW PowerShell, then: $nextCmd" -ForegroundColor Yellow
    Write-Host "           (the jarvis shim was added to your User PATH; the"
    Write-Host "            current PowerShell won't see it until restart)"
} else {
    Write-Host "  Run it:  $nextCmd"
}

if (-not $modelPullOk) {
    Write-Host ""
    Write-Host "  NOTE: the qwen3.5:2b model didn't finish downloading." -ForegroundColor Yellow
    Write-Host "        Chat will fail until the bg-orchestrator finishes the retry."
    Write-Host "        'jarvis doctor' shows progress."
}

if ($shouldInstallService) {
    Write-Host ""
    Write-Host "  Service: schtasks /Query /TN OpenJarvis     (status)"
    Write-Host "           powershell -File `"$serviceScript`" uninstall    (remove)"
}
Write-Host ""
Write-Host "  Docs:    https://open-jarvis.github.io/OpenJarvis/"
Write-Host ""
