[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$DesktopExecutable,
    [Parameter(Mandatory = $true)]
    [string]$RuntimeRoot,
    [ValidateRange(1, 65535)]
    [int]$Port = 8000,
    [ValidateRange(3, 60)]
    [int]$TimeoutSeconds = 15
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$Marker = 'OPENJARVIS-FINAL-RUNTIME'
$RuntimeName = 'phase8-final'
if ($Port -ne 8000) { throw 'Final desktop smoke requires canonical port 8000.' }
$Executable = [IO.Path]::GetFullPath($DesktopExecutable)
$RuntimeRoot = [IO.Path]::GetFullPath($RuntimeRoot)
if (-not (Test-Path -LiteralPath $Executable -PathType Leaf)) { throw 'Desktop executable is missing.' }
if (-not (Test-Path -LiteralPath $RuntimeRoot -PathType Container)) { throw 'Runtime root is missing.' }
if ((Get-Item -LiteralPath $RuntimeRoot).Attributes -band [IO.FileAttributes]::ReparsePoint) {
    throw 'Runtime root must not be a reparse point.'
}

function Get-VerifiedBackend {
    $response = Invoke-RestMethod -Method Get -Uri "http://127.0.0.1:$Port/v1/final/health" -TimeoutSec 2
    if ($response.marker -ne $Marker -or $response.runtime -ne $RuntimeName -or
        $response.status -ne 'ready' -or $response.backend -ne 'python_sdk') {
        throw 'Existing backend does not expose the exact final runtime marker.'
    }
    return $response
}

$before = Get-VerifiedBackend
$profileRoot = Join-Path $RuntimeRoot ("native-smoke-" + [Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $profileRoot | Out-Null
$priorAttach = $env:OPENJARVIS_FINAL_ATTACH_ONLY
$priorProfile = $env:WEBVIEW2_USER_DATA_FOLDER
$app = $null
$forcedCleanup = $false
try {
    $env:OPENJARVIS_FINAL_ATTACH_ONLY = '1'
    $env:WEBVIEW2_USER_DATA_FOLDER = $profileRoot
    $app = Start-Process -FilePath $Executable -WorkingDirectory (Split-Path $Executable) -PassThru
    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    do {
        if ($app.HasExited) { throw "Desktop exited before the close smoke (code $($app.ExitCode))." }
        $app.Refresh()
        if ($app.MainWindowHandle -ne 0) { break }
        Start-Sleep -Milliseconds 200
    } while ([DateTime]::UtcNow -lt $deadline)
    if ($app.MainWindowHandle -eq 0) { throw 'Desktop never exposed a main window.' }
    if (-not $app.CloseMainWindow()) { throw 'WM_CLOSE could not be delivered.' }
    if (-not $app.WaitForExit($TimeoutSeconds * 1000)) {
        $forcedCleanup = $true
        Stop-Process -Id $app.Id -Force -ErrorAction SilentlyContinue
        throw 'Desktop required forced termination after WM_CLOSE.'
    }
    $after = Get-VerifiedBackend
    if ([int]$after.pid -ne [int]$before.pid) { throw 'Backend PID changed during attach-only smoke.' }
    [pscustomobject]@{
        status = 'passed'
        marker = $Marker
        backend_pid = [int]$after.pid
        desktop_exit_code = $app.ExitCode
        wm_close = $true
        forced_kill = $false
    }
} finally {
    $env:OPENJARVIS_FINAL_ATTACH_ONLY = $priorAttach
    $env:WEBVIEW2_USER_DATA_FOLDER = $priorProfile
    if ($null -ne $app -and -not $app.HasExited) {
        $forcedCleanup = $true
        Stop-Process -Id $app.Id -Force -ErrorAction SilentlyContinue
    }
    Remove-Item -LiteralPath $profileRoot -Recurse -Force -ErrorAction SilentlyContinue
    if ($forcedCleanup) {
        Write-Error 'Native smoke failed because forced cleanup was necessary.'
    }
}
