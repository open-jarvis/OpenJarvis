[CmdletBinding()]
param(
    [ValidateSet('Config', 'BuildFinal', 'Start', 'Status', 'Stop', 'Restart')]
    [string]$Action = 'Status',
    [Parameter(Mandatory = $true)]
    [string]$RuntimeRoot,
    [Parameter(Mandatory = $true)]
    [string]$VaultPath,
    [string]$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path,
    [string]$ConfigPath = '',
    [string]$DesktopExecutable = '',
    [ValidateRange(1, 65535)]
    [int]$Port = 8000,
    [ValidateRange(2, 120)]
    [int]$TimeoutSeconds = 30
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$FinalMarker = 'OPENJARVIS-FINAL-RUNTIME'
$FinalRuntime = 'phase8-final'
if ($Port -ne 8000) { throw 'Final desktop runtime is bound to the canonical port 8000.' }

function Resolve-NormalDirectory([string]$Path, [string]$Label, [bool]$Create) {
    $full = [IO.Path]::GetFullPath($Path)
    if ($Create -and -not (Test-Path -LiteralPath $full)) {
        New-Item -ItemType Directory -Path $full | Out-Null
    }
    $item = Get-Item -LiteralPath $full -Force
    if (-not $item.PSIsContainer -or ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
        throw "$Label must be an existing normal directory: $full"
    }
    return $item.FullName
}

function Test-UnderRoot([string]$Candidate, [string]$Root) {
    $candidateFull = [IO.Path]::GetFullPath($Candidate).TrimEnd('\')
    $rootFull = [IO.Path]::GetFullPath($Root).TrimEnd('\')
    return $candidateFull.Equals($rootFull, [StringComparison]::OrdinalIgnoreCase) -or
        $candidateFull.StartsWith($rootFull + '\', [StringComparison]::OrdinalIgnoreCase)
}

function Assert-NoReparseAncestry([string]$Path, [string]$Label) {
    $cursor = [IO.Path]::GetFullPath($Path)
    while (-not [string]::IsNullOrWhiteSpace($cursor)) {
        if (Test-Path -LiteralPath $cursor) {
            $item = Get-Item -LiteralPath $cursor -Force
            if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) {
                throw "$Label ancestry contains a reparse point: $cursor"
            }
        }
        $parent = [IO.Directory]::GetParent($cursor)
        if ($null -eq $parent) { break }
        $cursor = $parent.FullName
    }
}

function Get-FinalHealth {
    try {
        $response = Invoke-RestMethod -Method Get -Uri "http://127.0.0.1:$Port/v1/final/health" -TimeoutSec 2
        if ($response.marker -eq $FinalMarker -and $response.runtime -eq $FinalRuntime -and
            $response.status -eq 'ready' -and $response.backend -eq 'python_sdk') {
            return $response
        }
    } catch { }
    return $null
}

function Get-PortOwner {
    $outputPath = Join-Path $RunRoot ("netstat-" + [Guid]::NewGuid().ToString('N') + '.txt')
    try {
        $netstat = Start-Process -FilePath "$env:SystemRoot\System32\netstat.exe" `
            -ArgumentList @('-ano', '-p', 'tcp') -RedirectStandardOutput $outputPath `
            -WindowStyle Hidden -PassThru
        if (-not $netstat.WaitForExit(5000)) {
            Stop-Process -Id $netstat.Id -Force -ErrorAction SilentlyContinue
            throw 'Bounded netstat inventory timed out.'
        }
        if ($netstat.ExitCode -ne 0) { throw "netstat failed with code $($netstat.ExitCode)." }
        $owners = @(
            Get-Content -LiteralPath $outputPath | ForEach-Object {
                if ($_ -match '^\s*TCP\s+\S+:(\d+)\s+\S+\s+LISTENING\s+(\d+)\s*$' -and
                    [int]$Matches[1] -eq $Port) { [int]$Matches[2] }
            } | Sort-Object -Unique
        )
    } finally {
        Remove-Item -LiteralPath $outputPath -Force -ErrorAction SilentlyContinue
    }
    if ($owners.Count -eq 0) { return $null }
    if ($owners.Count -ne 1) { throw "Port $Port has ambiguous owners." }
    return [int]$owners[0]
}

function Get-OwnedServer([int]$ExpectedPid, [string]$ExpectedStartedAtUtc = '') {
    $process = Get-Process -Id $ExpectedPid -ErrorAction SilentlyContinue
    if ($null -eq $process) { return $null }
    $python = Join-Path $RepoRoot '.venv\Scripts\python.exe'
    $executable = $process.Path
    if (-not $executable.Equals($python, [StringComparison]::OrdinalIgnoreCase)) {
        throw "PID $ExpectedPid is not the repository Python executable."
    }
    if (-not [string]::IsNullOrWhiteSpace($ExpectedStartedAtUtc)) {
        $expected = [DateTime]::Parse(
            $ExpectedStartedAtUtc,
            [Globalization.CultureInfo]::InvariantCulture,
            [Globalization.DateTimeStyles]::RoundtripKind
        ).ToUniversalTime()
        $actual = $process.StartTime.ToUniversalTime()
        if ($actual.Ticks -ne $expected.Ticks) {
            throw "PID $ExpectedPid start time does not match managed state."
        }
    }
    return $process
}

$RepoRoot = Resolve-NormalDirectory $RepoRoot 'repository' $false
$VaultPath = Resolve-NormalDirectory $VaultPath 'vault' $false
$proposedRuntimeRoot = [IO.Path]::GetFullPath($RuntimeRoot)
Assert-NoReparseAncestry $proposedRuntimeRoot 'OPENJARVIS_HOME'
if ((Test-UnderRoot $proposedRuntimeRoot $RepoRoot) -or
    (Test-UnderRoot $RepoRoot $proposedRuntimeRoot) -or
    (Test-UnderRoot $proposedRuntimeRoot $VaultPath) -or
    (Test-UnderRoot $VaultPath $proposedRuntimeRoot)) {
    throw 'Runtime root must be disjoint from repository and vault.'
}
$RuntimeRoot = Resolve-NormalDirectory $proposedRuntimeRoot 'OPENJARVIS_HOME' $true
if (-not (Test-Path -LiteralPath (Join-Path $RepoRoot 'pyproject.toml'))) {
    throw 'Repository root is missing pyproject.toml.'
}
$Python = Join-Path $RepoRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) { throw 'Repository Python is missing.' }
if ([string]::IsNullOrWhiteSpace($ConfigPath)) { $ConfigPath = Join-Path $RuntimeRoot 'config.toml' }
$ConfigPath = [IO.Path]::GetFullPath($ConfigPath)
if (-not (Test-UnderRoot $ConfigPath $RuntimeRoot)) { throw 'Config must remain under RuntimeRoot.' }
$RunRoot = Join-Path $RuntimeRoot 'run'
if (-not (Test-Path -LiteralPath $RunRoot)) { New-Item -ItemType Directory -Path $RunRoot | Out-Null }
$StatePath = Join-Path $RunRoot 'final-runtime.json'
$TokenPath = Join-Path $RunRoot 'shutdown.token'

function Write-LocalConfig {
    $priorHome = $env:OPENJARVIS_HOME
    try {
        $env:OPENJARVIS_HOME = $RuntimeRoot
        & $Python -m openjarvis.final_runtime config --home $RuntimeRoot --vault $VaultPath --config $ConfigPath --host 127.0.0.1 --port $Port
        if ($LASTEXITCODE -ne 0) { throw 'Final config generation failed.' }
    } finally {
        $env:OPENJARVIS_HOME = $priorHome
    }
}

function Read-State {
    if (-not (Test-Path -LiteralPath $StatePath -PathType Leaf)) { return $null }
    return (Get-Content -LiteralPath $StatePath -Raw | ConvertFrom-Json)
}

function Show-Status {
    $state = Read-State
    $health = Get-FinalHealth
    $portOwner = Get-PortOwner
    $owned = $false
    if ($null -ne $state -and $null -ne $health -and $null -ne $portOwner) {
        try {
            $process = Get-OwnedServer ([int]$state.server_pid) ([string]$state.started_at_utc)
            $owned = $null -ne $process -and $portOwner -eq [int]$state.server_pid -and
                [int]$health.pid -eq [int]$state.server_pid
        } catch { $owned = $false }
    }
    [pscustomobject]@{
        status = if ($owned) { 'ready' } else { 'stopped_or_unverified' }
        marker = if ($null -ne $health) { $health.marker } else { $null }
        server_pid = if ($null -ne $state) { $state.server_pid } else { $null }
        ui_pid = if ($null -ne $state) { $state.ui_pid } else { $null }
        port = $Port
        port_owner = $portOwner
    }
}

function Start-FinalRuntime {
    if ($null -ne (Get-PortOwner)) { throw "Port $Port is already occupied; refusing a second server." }
    if (Test-Path -LiteralPath $StatePath) { throw 'Managed state already exists; run Status/Stop first.' }
    Write-LocalConfig
    $token = [Guid]::NewGuid().ToString('N')
    [IO.File]::WriteAllText($TokenPath, $token, [Text.UTF8Encoding]::new($false))
    & icacls.exe $TokenPath /inheritance:r /grant:r "${env:USERNAME}:(R,W)" | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Remove-Item -LiteralPath $TokenPath -Force -ErrorAction SilentlyContinue
        throw 'Could not restrict the shutdown token ACL.'
    }
    $server = $null
    $ui = $null
    try {
        $priorHome = $env:OPENJARVIS_HOME
        $priorToken = $env:OPENJARVIS_SHUTDOWN_TOKEN
        try {
            $env:OPENJARVIS_HOME = $RuntimeRoot
            $env:OPENJARVIS_SHUTDOWN_TOKEN = $token
            $server = Start-Process -FilePath $Python -ArgumentList @(
                '-m', 'openjarvis.final_runtime', 'serve',
                '--home', ('"' + $RuntimeRoot + '"'),
                '--vault', ('"' + $VaultPath + '"'),
                '--config', ('"' + $ConfigPath + '"')
            ) -WorkingDirectory $RepoRoot -WindowStyle Hidden -PassThru
        } finally {
            $env:OPENJARVIS_HOME = $priorHome
            $env:OPENJARVIS_SHUTDOWN_TOKEN = $priorToken
        }
        $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
        $health = $null
        do {
            if ($server.HasExited) { throw "Final runtime exited early with code $($server.ExitCode)." }
            $health = Get-FinalHealth
            if ($null -ne $health) { break }
            Start-Sleep -Milliseconds 250
        } while ([DateTime]::UtcNow -lt $deadline)
        if ($null -eq $health) { throw 'Final runtime did not become ready.' }
        $owner = Get-PortOwner
        if ($owner -ne $server.Id -or [int]$health.pid -ne $server.Id) {
            throw 'Health PID and listener ownership do not match the launched process.'
        }
        $server.Refresh()
        $serverStartedAtUtc = $server.StartTime.ToUniversalTime().ToString(
            'o', [Globalization.CultureInfo]::InvariantCulture
        )
        Get-OwnedServer $server.Id $serverStartedAtUtc | Out-Null
        $uiPid = $null
        if (-not [string]::IsNullOrWhiteSpace($DesktopExecutable)) {
            $desktop = [IO.Path]::GetFullPath($DesktopExecutable)
            if (-not (Test-Path -LiteralPath $desktop -PathType Leaf)) { throw 'Desktop executable is missing.' }
            $priorAttach = $env:OPENJARVIS_FINAL_ATTACH_ONLY
            try {
                $env:OPENJARVIS_FINAL_ATTACH_ONLY = '1'
                $ui = Start-Process -FilePath $desktop -WorkingDirectory (Split-Path $desktop) -PassThru
                $uiPid = $ui.Id
            } finally {
                $env:OPENJARVIS_FINAL_ATTACH_ONLY = $priorAttach
            }
        }
        [pscustomobject]@{
            schema = 1
            server_pid = $server.Id
            ui_pid = $uiPid
            port = $Port
            repo_root = $RepoRoot
            executable = $Python
            started_at_utc = $serverStartedAtUtc
        } | ConvertTo-Json | Set-Content -LiteralPath $StatePath -Encoding UTF8
        Show-Status
    } catch {
        $originalError = $_
        if ($null -ne $ui -and -not $ui.HasExited) {
            [void]$ui.CloseMainWindow()
            if (-not $ui.WaitForExit(3000)) { Stop-Process -Id $ui.Id -Force -ErrorAction SilentlyContinue }
        }
        if ($null -ne $server -and -not $server.HasExited) {
            try {
                $ownedHealth = Get-FinalHealth
                if ($null -ne $ownedHealth -and [int]$ownedHealth.pid -eq $server.Id) {
                    Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:$Port/v1/final/shutdown" `
                        -Headers @{ 'X-OpenJarvis-Shutdown-Token' = $token } -TimeoutSec 3 | Out-Null
                    [void]$server.WaitForExit(5000)
                }
            } catch { }
            if (-not $server.HasExited) {
                Stop-Process -Id $server.Id -Force -ErrorAction SilentlyContinue
                [void]$server.WaitForExit(3000)
            }
        }
        Remove-Item -LiteralPath $StatePath -Force -ErrorAction SilentlyContinue
        Remove-Item -LiteralPath $TokenPath -Force -ErrorAction SilentlyContinue
        throw $originalError
    } finally {
        $token = $null
    }
}

function Stop-FinalRuntime {
    $state = Read-State
    if ($null -eq $state) { throw 'No managed final-runtime state exists.' }
    $uiCloseFailure = $null
    if ($null -ne $state.ui_pid) {
        $ui = Get-Process -Id ([int]$state.ui_pid) -ErrorAction SilentlyContinue
        if ($null -ne $ui) {
            if (-not $ui.CloseMainWindow() -or -not $ui.WaitForExit($TimeoutSeconds * 1000)) {
                $uiCloseFailure = 'Desktop did not exit after WM_CLOSE; no forced kill was used.'
            }
        }
    }
    $server = Get-OwnedServer ([int]$state.server_pid) ([string]$state.started_at_utc)
    if ($null -ne $server) {
        if ((Get-PortOwner) -ne [int]$state.server_pid) { throw 'Managed server no longer owns its recorded port.' }
        $health = Get-FinalHealth
        if ($null -eq $health -or [int]$health.pid -ne [int]$state.server_pid) {
            throw 'Managed server no longer owns the exact final health identity.'
        }
        if (-not (Test-Path -LiteralPath $TokenPath -PathType Leaf)) { throw 'Shutdown token file is missing.' }
        $token = Get-Content -LiteralPath $TokenPath -Raw
        try {
            Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:$Port/v1/final/shutdown" `
                -Headers @{ 'X-OpenJarvis-Shutdown-Token' = $token } -TimeoutSec 3 | Out-Null
        } finally { $token = $null }
        $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
        while ((Get-Process -Id ([int]$state.server_pid) -ErrorAction SilentlyContinue) -and
            [DateTime]::UtcNow -lt $deadline) { Start-Sleep -Milliseconds 250 }
        if (Get-Process -Id ([int]$state.server_pid) -ErrorAction SilentlyContinue) {
            throw 'Server did not complete graceful shutdown; no forced kill was used.'
        }
    }
    if ($null -ne (Get-PortOwner)) { throw "Port $Port remains occupied after shutdown." }
    if ($null -ne $uiCloseFailure) { throw $uiCloseFailure }
    Remove-Item -LiteralPath $TokenPath -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $StatePath -Force
    Show-Status
}

switch ($Action) {
    'Config' { Write-LocalConfig; Get-Item -LiteralPath $ConfigPath | Select-Object FullName, Length, LastWriteTimeUtc }
    'BuildFinal' {
        $priorUpdater = $env:VITE_OPENJARVIS_NO_UPDATER
        try {
            $env:VITE_OPENJARVIS_NO_UPDATER = '1'
            & npm --prefix (Join-Path $RepoRoot 'frontend') run tauri build
            if ($LASTEXITCODE -ne 0) { throw 'Final Tauri build failed.' }
        } finally { $env:VITE_OPENJARVIS_NO_UPDATER = $priorUpdater }
    }
    'Start' { Start-FinalRuntime }
    'Status' { Show-Status }
    'Stop' { Stop-FinalRuntime }
    'Restart' { Stop-FinalRuntime; Start-FinalRuntime }
}
