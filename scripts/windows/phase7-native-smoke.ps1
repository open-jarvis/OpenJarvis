[CmdletBinding()]
param(
    [string]$ExecutablePath = ""
)

$ErrorActionPreference = "Stop"
$repositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
if (-not $ExecutablePath) {
    $ExecutablePath = Join-Path $repositoryRoot `
        "frontend\src-tauri\target\release\openjarvis-desktop.exe"
}
$ExecutablePath = (Resolve-Path -LiteralPath $ExecutablePath).Path
if (-not (Test-Path -LiteralPath $ExecutablePath -PathType Leaf)) {
    throw "Native OpenJarvis executable not found: $ExecutablePath"
}

$smokeRoot = Join-Path $env:TEMP (
    "openjarvis-phase7-smoke-" + [guid]::NewGuid().ToString("N")
)
$temporaryRoot = [IO.Path]::GetFullPath($env:TEMP).TrimEnd("\") + "\"
$resolvedSmokeRoot = [IO.Path]::GetFullPath($smokeRoot)
if (-not $resolvedSmokeRoot.StartsWith(
    $temporaryRoot,
    [StringComparison]::OrdinalIgnoreCase
)) {
    throw "Refusing to create smoke profile outside the temporary directory."
}

[void](New-Item -ItemType Directory -Path $resolvedSmokeRoot)
[void](New-Item -ItemType Directory -Path (
    Join-Path $resolvedSmokeRoot "appdata"
))
[void](New-Item -ItemType Directory -Path (
    Join-Path $resolvedSmokeRoot "localappdata"
))

$pythonPath = Join-Path $repositoryRoot ".venv\Scripts\python.exe"
$backendScript = Join-Path $PSScriptRoot "phase7_smoke_backend.py"
if (-not (Test-Path -LiteralPath $pythonPath -PathType Leaf)) {
    throw "Repository Python environment is unavailable: $pythonPath"
}
$backendStart = [Diagnostics.ProcessStartInfo]::new()
$backendStart.FileName = $pythonPath
$backendStart.Arguments = '"' + $backendScript + '"'
$backendStart.WorkingDirectory = $resolvedSmokeRoot
$backendStart.UseShellExecute = $false
$backendStart.CreateNoWindow = $true
$backendStart.RedirectStandardOutput = $true
$backendStart.RedirectStandardError = $true
$backend = [Diagnostics.Process]::Start($backendStart)
$backend.BeginOutputReadLine()
$backend.BeginErrorReadLine()

$application = $null
try {
    $backendReady = $false
    for ($attempt = 0; $attempt -lt 20; $attempt++) {
        try {
            $response = Invoke-RestMethod `
                -Uri "http://127.0.0.1:8000/health" `
                -TimeoutSec 1
            if ($response.status -eq "healthy") {
                $backendReady = $true
                break
            }
        }
        catch {
            # The bounded retry below handles listener startup latency.
        }
        Start-Sleep -Milliseconds 250
    }
    if (-not $backendReady) {
        throw "Synthetic loopback backend did not become ready."
    }

    $start = [Diagnostics.ProcessStartInfo]::new()
    $start.FileName = $ExecutablePath
    $start.WorkingDirectory = $resolvedSmokeRoot
    $start.UseShellExecute = $false
    $start.RedirectStandardOutput = $true
    $start.RedirectStandardError = $true
    $start.EnvironmentVariables["HOME"] = $resolvedSmokeRoot
    $start.EnvironmentVariables["USERPROFILE"] = $resolvedSmokeRoot
    $start.EnvironmentVariables["APPDATA"] = Join-Path `
        $resolvedSmokeRoot "appdata"
    $start.EnvironmentVariables["LOCALAPPDATA"] = Join-Path `
        $resolvedSmokeRoot "localappdata"
    $start.EnvironmentVariables["OPENJARVIS_ROOT"] = $repositoryRoot

    $application = [Diagnostics.Process]::Start($start)
    $application.BeginOutputReadLine()
    $application.BeginErrorReadLine()
    $windowReady = $false
    for ($attempt = 0; $attempt -lt 60; $attempt++) {
        if ($application.HasExited) {
            break
        }
        $application.Refresh()
        if ($application.MainWindowHandle -ne 0) {
            $windowReady = $true
            break
        }
        Start-Sleep -Milliseconds 500
    }

    Write-Host "Native PID: $($application.Id)"
    Write-Host "Window ready: $windowReady"
    Write-Host "Window title: $($application.MainWindowTitle)"
    if ($application.HasExited) {
        throw "Native application exited before the window smoke completed."
    }
    if (-not $windowReady) {
        throw "Native application did not expose a main window."
    }

    $closeSent = $application.CloseMainWindow()
    Write-Host "WM_CLOSE sent: $closeSent"
    Start-Sleep -Seconds 3
    $application.Refresh()
    Write-Host "Alive after close request: $(-not $application.HasExited)"

    if (-not $application.HasExited) {
        # The Phase-6 close guard intentionally keeps the tray application
        # alive. Kill only this exact, harness-owned process tree.
        & taskkill.exe /PID $application.Id /T /F | Out-Null
        [void]$application.WaitForExit(10000)
    }
    if (-not $application.HasExited) {
        throw "Harness-owned native process did not exit during cleanup."
    }
    Write-Host "Native start/close smoke: PASS"
}
finally {
    if ($null -ne $application -and -not $application.HasExited) {
        & taskkill.exe /PID $application.Id /T /F | Out-Null
    }
    if ($null -ne $backend -and -not $backend.HasExited) {
        Stop-Process -Id $backend.Id -Force -ErrorAction SilentlyContinue
        [void]$backend.WaitForExit(5000)
    }

    if ([IO.Directory]::Exists($resolvedSmokeRoot)) {
        for ($attempt = 0; $attempt -lt 10; $attempt++) {
            try {
                [IO.Directory]::Delete("\\?\$resolvedSmokeRoot", $true)
                break
            }
            catch [IO.IOException] {
                Start-Sleep -Milliseconds 250
            }
            catch [UnauthorizedAccessException] {
                Start-Sleep -Milliseconds 250
            }
        }
    }
    Write-Host "Temporary profile removed: $(-not (
        [IO.Directory]::Exists($resolvedSmokeRoot)
    ))"
}
