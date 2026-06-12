# Start OpenJarvis backend + frontend and open the UI in Microsoft Edge.
$ErrorActionPreference = "Continue"
$Root = Split-Path $PSScriptRoot -Parent
$BackendPort = 8000
$FrontendPort = 5173
$BackendUrl = "http://127.0.0.1:$BackendPort/"
$FrontendUrl = "http://localhost:$FrontendPort/"

function Test-BackendUp {
    try {
        $h = Invoke-RestMethod "http://127.0.0.1:$BackendPort/health" -TimeoutSec 3
        return $h.status -eq "ok"
    } catch {
        return $false
    }
}

function Test-StaticUiUp {
    try {
        $r = Invoke-WebRequest "$BackendUrl" -TimeoutSec 3 -UseBasicParsing
        return $r.StatusCode -eq 200
    } catch {
        return $false
    }
}

function Test-FrontendUp {
    try {
        $r = Invoke-WebRequest $FrontendUrl -TimeoutSec 3 -UseBasicParsing
        return $r.StatusCode -eq 200
    } catch {
        return $false
    }
}

function Ensure-Built {
    $staticIndex = Join-Path $Root "src\openjarvis\server\static\index.html"
    if (-not (Test-Path $staticIndex)) {
        Write-Host "Building frontend (first run)..." -ForegroundColor Yellow
        Push-Location (Join-Path $Root "frontend")
        npm install 2>$null
        npm run build
        Pop-Location
    }
}

function Start-Backend {
    Write-Host "Starting Jarvis backend on port $BackendPort..."
    & "$PSScriptRoot\restart-server.ps1"
}

function Start-Frontend {
    Write-Host "Starting Jarvis frontend dev server on port $FrontendPort..."
    $frontendDir = Join-Path $Root "frontend"
    Start-Process powershell -ArgumentList @(
        "-NoExit",
        "-Command",
        "Set-Location '$frontendDir'; npm run dev"
    ) -WindowStyle Minimized
    for ($i = 0; $i -lt 30; $i++) {
        Start-Sleep -Seconds 1
        if (Test-FrontendUp) { return }
    }
    Write-Host "WARNING: Frontend dev server may still be starting." -ForegroundColor Yellow
}

function Open-EdgeTab {
    param([string]$Url)
    $edge = "${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe"
    if (-not (Test-Path $edge)) {
        $edge = "$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe"
    }
    if (Test-Path $edge) {
        Start-Process $edge -ArgumentList $Url
    } else {
        Start-Process $Url
    }
}

Ensure-Built

if (-not (Test-BackendUp)) {
    Start-Backend
    for ($i = 0; $i -lt 20; $i++) {
        Start-Sleep -Seconds 1
        if (Test-BackendUp) { break }
    }
}

# Prefer built-in UI on :8000 (no separate vite needed). Fall back to vite dev.
$openUrl = $BackendUrl
if (Test-StaticUiUp) {
    Write-Host "Using built UI at $BackendUrl" -ForegroundColor Green
} else {
    if (-not (Test-FrontendUp)) {
        Start-Frontend
    }
    $openUrl = $FrontendUrl
}

Open-EdgeTab -Url $openUrl

Write-Host ""
Write-Host "Jarvis ready:" -ForegroundColor Green
Write-Host "  Backend:  http://127.0.0.1:$BackendPort"
Write-Host "  UI:       $openUrl"
Write-Host "  Browser:  Microsoft Edge"
