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
    $errorPath = Join-Path $RunRoot ("netstat-error-" + [Guid]::NewGuid().ToString('N') + '.txt')
    $priorOutputEncoding = [Console]::OutputEncoding
    try {
        [Console]::OutputEncoding = [Text.Encoding]::GetEncoding(
            [Globalization.CultureInfo]::CurrentCulture.TextInfo.OEMCodePage
        )
        $lines = @(& "$env:SystemRoot\System32\netstat.exe" -ano -p tcp 2> $errorPath)
        $exitCode = $LASTEXITCODE
        $stderr = @()
        if (Test-Path -LiteralPath $errorPath) {
            $stderr = @(Get-Content -LiteralPath $errorPath)
        }
        if ($exitCode -isnot [int]) {
            throw 'netstat.exe did not provide a numeric exit status.'
        }
        if ($exitCode -ne 0) {
            $detail = ($stderr -join ' ').Trim()
            if (-not [string]::IsNullOrWhiteSpace($detail)) {
                throw "netstat.exe failed with exit code $exitCode. $detail"
            }
            throw "netstat.exe failed with exit code $exitCode."
        }
        $owners = @(
            $lines | ForEach-Object {
                if ($_ -match '^\s*TCP\s+\S+:(\d+)\s+\S+\s+(?:LISTENING|ABH(?:\u00D6|O|OE)REN)\s+(\d+)\s*$' -and
                    [int]$Matches[1] -eq $Port) { [int]$Matches[2] }
            } | Sort-Object -Unique
        )
    } finally {
        [Console]::OutputEncoding = $priorOutputEncoding
        Remove-Item -LiteralPath $errorPath -Force -ErrorAction SilentlyContinue
    }
    if ($owners.Count -eq 0) { return $null }
    if ($owners.Count -ne 1) { throw "Port $Port has ambiguous owners." }
    return [int]$owners[0]
}

function Get-LaunchedRuntimeProcess([object]$LaunchedProcess, [object]$Health) {
    $healthPidProperty = $Health.PSObject.Properties['pid']
    [int]$healthPid = 0
    if ($null -eq $healthPidProperty -or
        -not [int]::TryParse([string]$healthPidProperty.Value, [ref]$healthPid) -or
        $healthPid -le 0) {
        throw 'Final health response did not provide a numeric process ID.'
    }
    $owner = Get-PortOwner
    if ($null -eq $owner -or [int]$owner -ne $healthPid) {
        throw 'Final health PID and listener ownership do not match.'
    }
    $LaunchedProcess.Refresh()
    if ($LaunchedProcess.HasExited) {
        throw 'Launched process exited before runtime ownership could be verified.'
    }
    if ($healthPid -ne [int]$LaunchedProcess.Id) {
        $currentId = $healthPid
        $visited = [Collections.Generic.HashSet[int]]::new()
        $isDescendant = $false
        while ($currentId -gt 0 -and $visited.Add($currentId)) {
            $records = @(Get-CimInstance -ClassName Win32_Process -Filter "ProcessId = $currentId")
            if ($null -eq $records -or $records.Count -ne 1 -or $null -eq $records[0]) { break }
            $parentProperty = $records[0].PSObject.Properties['ParentProcessId']
            [int]$parentId = 0
            if ($null -eq $parentProperty -or
                -not [int]::TryParse([string]$parentProperty.Value, [ref]$parentId)) { break }
            if ($parentId -eq [int]$LaunchedProcess.Id) {
                $isDescendant = $true
                break
            }
            $currentId = $parentId
        }
        if (-not $isDescendant) {
            throw 'Final health/listener process is not a descendant of the launched process.'
        }
    }
    $runtimeProcess = Get-Process -Id $healthPid -ErrorAction SilentlyContinue
    if ($null -eq $runtimeProcess) { throw 'Final health/listener process no longer exists.' }
    $runtimeProcess.Refresh()
    $LaunchedProcess.Refresh()
    if ($runtimeProcess.HasExited -or $LaunchedProcess.HasExited -or
        (Get-PortOwner) -ne $healthPid) {
        throw 'Final runtime ownership changed during verification.'
    }
    return $runtimeProcess
}

function Get-OwnedServer(
    [int]$ExpectedPid,
    [string]$ExpectedStartedAtUtc = '',
    [string]$ExpectedExecutable = ''
) {
    $process = Get-Process -Id $ExpectedPid -ErrorAction SilentlyContinue
    if ($null -eq $process) { return $null }
    if ([string]::IsNullOrWhiteSpace($ExpectedExecutable)) {
        $ExpectedExecutable = Join-Path $RepoRoot '.venv\Scripts\python.exe'
    }
    $expectedPath = [IO.Path]::GetFullPath($ExpectedExecutable)
    $executable = $process.Path
    if ([string]::IsNullOrWhiteSpace($executable) -or
        -not $executable.Equals($expectedPath, [StringComparison]::OrdinalIgnoreCase)) {
        throw "PID $ExpectedPid is not the recorded runtime executable."
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
$ServerOutputPath = Join-Path $RunRoot 'final-server.stdout.log'
$ServerErrorPath = Join-Path $RunRoot 'final-server.stderr.log'

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
            $process = Get-OwnedServer `
                ([int]$state.server_pid) `
                ([string]$state.started_at_utc) `
                ([string]$state.executable)
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
    $managedServer = $null
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
            ) -WorkingDirectory $RepoRoot -WindowStyle Hidden `
                -RedirectStandardOutput $ServerOutputPath `
                -RedirectStandardError $ServerErrorPath -PassThru
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
        $managedServer = Get-LaunchedRuntimeProcess $server $health
        $managedServer.Refresh()
        $serverStartedAtUtc = $managedServer.StartTime.ToUniversalTime().ToString(
            'o', [Globalization.CultureInfo]::InvariantCulture
        )
        $serverExecutable = $managedServer.Path
        if ([string]::IsNullOrWhiteSpace($serverExecutable)) {
            throw 'Final runtime executable path is unavailable.'
        }
        Get-OwnedServer $managedServer.Id $serverStartedAtUtc $serverExecutable | Out-Null
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
            server_pid = $managedServer.Id
            ui_pid = $uiPid
            port = $Port
            repo_root = $RepoRoot
            executable = $serverExecutable
            started_at_utc = $serverStartedAtUtc
        } | ConvertTo-Json | Set-Content -LiteralPath $StatePath -Encoding UTF8
        Show-Status
    } catch {
        $originalError = $_
        if ($null -ne $ui -and -not $ui.HasExited) {
            [void]$ui.CloseMainWindow()
            if (-not $ui.WaitForExit(3000)) { Stop-Process -Id $ui.Id -Force -ErrorAction SilentlyContinue }
        }
        if ($null -ne $managedServer -and -not $managedServer.HasExited) {
            try {
                $ownedHealth = Get-FinalHealth
                $ownedServer = if ($null -ne $ownedHealth) {
                    Get-LaunchedRuntimeProcess $server $ownedHealth
                } else { $null }
                if ($null -ne $ownedServer -and $ownedServer.Id -eq $managedServer.Id) {
                    Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:$Port/v1/final/shutdown" `
                        -Headers @{ 'X-OpenJarvis-Shutdown-Token' = $token } -TimeoutSec 3 | Out-Null
                    [void]$managedServer.WaitForExit(5000)
                }
            } catch { }
            if (-not $managedServer.HasExited) {
                Stop-Process -Id $managedServer.Id -Force -ErrorAction SilentlyContinue
                [void]$managedServer.WaitForExit(3000)
            }
        }
        if ($null -ne $server -and
            ($null -eq $managedServer -or $server.Id -ne $managedServer.Id) -and
            -not $server.HasExited) {
            if (-not $server.WaitForExit(3000)) {
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
    $server = Get-OwnedServer `
        ([int]$state.server_pid) `
        ([string]$state.started_at_utc) `
        ([string]$state.executable)
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
