<#
.SYNOPSIS
    Register / unregister the OpenJarvis Windows scheduled task.

.DESCRIPTION
    The Windows equivalent of deploy/systemd/openjarvis.service and
    deploy/launchd/com.openjarvis.plist.

    Registers a per-user scheduled task named "OpenJarvis" that starts
    `jarvis serve` at logon and restarts on failure. Loopback default
    (127.0.0.1) so no API key is required — matches launchd parity.

    Subcommands:
      install   — create or replace the task
      uninstall — remove the task
      status    — show task state

    Arguments (install only):
      -InstallRoot <path>  default: %LOCALAPPDATA%\OpenJarvis (matches
                           install.ps1's default)
      -ListenHost <addr>   default: 127.0.0.1 (loopback). Set to 0.0.0.0
                           ONLY if you also set $env:OPENJARVIS_API_KEY
                           — the server refuses to start unauthenticated
                           on a non-loopback bind.
      -ListenPort <int>    default: 8000

    Usage:
      powershell -ExecutionPolicy Bypass -File jarvis-service.ps1 install
      powershell -ExecutionPolicy Bypass -File jarvis-service.ps1 uninstall
      powershell -ExecutionPolicy Bypass -File jarvis-service.ps1 status
#>

[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [ValidateSet('install', 'uninstall', 'status')]
    [string] $Command = 'status',

    [string] $InstallRoot,
    [string] $ListenHost = '127.0.0.1',
    [int]    $ListenPort = 8000
)

$ErrorActionPreference = 'Stop'
$TaskName = 'OpenJarvis'

function Write-Info  ($msg) { Write-Host "[info]  $msg" -ForegroundColor Cyan }
function Write-Ok    ($msg) { Write-Host "[ok]    $msg" -ForegroundColor Green }
function Write-Warn2 ($msg) { Write-Host "[warn]  $msg" -ForegroundColor Yellow }
function Write-Fail  ($msg) {
    Write-Host "[fail]  $msg" -ForegroundColor Red
    exit 1
}

function Get-DefaultInstallRoot {
    # Use $script: prefix so this is robust to being called from any
    # function scope (PowerShell's default dynamic lookup would also
    # work today, but $script: is the explicit contract).
    if ($script:InstallRoot) { return $script:InstallRoot }
    if ($env:OPENJARVIS_HOME) { return $env:OPENJARVIS_HOME }
    return (Join-Path $env:LOCALAPPDATA 'OpenJarvis')
}

# ---------------------------------------------------------------------------
# install
# ---------------------------------------------------------------------------

function Install-Task {
    $root = Get-DefaultInstallRoot
    $srcDir = Join-Path $root 'src'
    if (-not (Test-Path $srcDir)) {
        Write-Fail "OpenJarvis source not found at $srcDir. Run install.ps1 first."
    }

    $uvCmd = Get-Command uv -ErrorAction SilentlyContinue
    if (-not $uvCmd) {
        $uvFallback = Join-Path $env:USERPROFILE '.local\bin\uv.exe'
        if (Test-Path $uvFallback) {
            $uvPath = $uvFallback
        } else {
            Write-Fail "uv.exe not found on PATH or at $uvFallback. Re-run install.ps1."
        }
    } else {
        $uvPath = $uvCmd.Source
    }

    # Safety: refuse to register a non-loopback bind without an API key.
    # Mirrors deploy/systemd/openjarvis.service's EnvironmentFile guard.
    $isLoopback = ($ListenHost -eq '127.0.0.1' -or $ListenHost -eq 'localhost')
    if (-not $isLoopback -and -not $env:OPENJARVIS_API_KEY) {
        Write-Fail @"
ListenHost is $ListenHost (non-loopback) but `$env:OPENJARVIS_API_KEY is
not set. An unauthenticated non-loopback bind is refused by jarvis serve
and would also create a security hole. Set the env var first:

    `$env:OPENJARVIS_API_KEY = (uv run jarvis auth generate-key)

then re-run with -ListenHost 0.0.0.0.
"@
    }

    # CRITICAL: scheduled tasks do NOT inherit the registering session's
    # environment. If we registered the task now and stopped here, the
    # task would launch at logon with a clean env, find no API key, and
    # `jarvis serve` would refuse to bind 0.0.0.0 — failing silently every
    # logon. Persist the key to the User env scope so the task's logon
    # session picks it up. (Loopback path doesn't need the key, so this
    # only runs for the explicit LAN-exposed case.)
    if (-not $isLoopback) {
        Write-Info "Persisting OPENJARVIS_API_KEY to User environment so the scheduled task can read it at logon."
        [System.Environment]::SetEnvironmentVariable(
            'OPENJARVIS_API_KEY',
            $env:OPENJARVIS_API_KEY,
            'User'
        )
    }

    Write-Info "Registering scheduled task '$TaskName'..."
    Write-Info "  Working dir : $srcDir"
    Write-Info "  Listen      : $ListenHost`:$ListenPort"
    Write-Info "  User        : $env:USERNAME"

    # If a previous task exists, remove it first (idempotent install).
    $existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if ($existing) {
        Write-Info "Existing task found — replacing."
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    }

    $action = New-ScheduledTaskAction `
        -Execute $uvPath `
        -Argument "run jarvis serve --host $ListenHost --port $ListenPort" `
        -WorkingDirectory $srcDir

    $trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME

    $settings = New-ScheduledTaskSettingsSet `
        -AllowStartIfOnBatteries `
        -DontStopIfGoingOnBatteries `
        -StartWhenAvailable `
        -RestartCount 3 `
        -RestartInterval (New-TimeSpan -Minutes 1) `
        -ExecutionTimeLimit (New-TimeSpan -Seconds 0)

    $principal = New-ScheduledTaskPrincipal `
        -UserId $env:USERNAME `
        -LogonType Interactive `
        -RunLevel Limited

    Register-ScheduledTask `
        -TaskName $TaskName `
        -Action $action `
        -Trigger $trigger `
        -Settings $settings `
        -Principal $principal `
        -Description 'OpenJarvis API server (loopback default — see deploy/windows/README.md)' | Out-Null

    Write-Ok "Task '$TaskName' registered."
    Write-Info "It will start automatically at next logon."
    Write-Info "To start it now: Start-ScheduledTask -TaskName $TaskName"
}

# ---------------------------------------------------------------------------
# uninstall
# ---------------------------------------------------------------------------

function Uninstall-Task {
    $existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if (-not $existing) {
        Write-Warn2 "Task '$TaskName' is not registered — nothing to remove."
        return
    }
    Write-Info "Stopping '$TaskName' (if running)..."
    Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    Write-Info "Unregistering '$TaskName'..."
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Ok "Task '$TaskName' removed."
}

# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------

function Show-Status {
    $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if (-not $task) {
        Write-Host "Task '$TaskName' is not registered."
        Write-Host "Install it with:"
        Write-Host "  powershell -ExecutionPolicy Bypass -File `"$PSCommandPath`" install"
        return
    }
    $info = Get-ScheduledTaskInfo -TaskName $TaskName
    Write-Host "Task    : $TaskName"
    Write-Host "State   : $($task.State)"
    Write-Host "LastRun : $($info.LastRunTime)"
    Write-Host "LastRes : 0x$('{0:X8}' -f $info.LastTaskResult)"
    Write-Host "NextRun : $($info.NextRunTime)"
}

# ---------------------------------------------------------------------------
# dispatch
# ---------------------------------------------------------------------------

switch ($Command) {
    'install'   { Install-Task }
    'uninstall' { Uninstall-Task }
    'status'    { Show-Status }
}
