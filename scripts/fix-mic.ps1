# Install deps, build frontend, restart backend - full mic fix pipeline.
$ErrorActionPreference = "Stop"
$Root = Split-Path $PSScriptRoot -Parent
Set-Location $Root

$uv = (Get-Command uv -ErrorAction SilentlyContinue).Source
if (-not $uv) {
    $uvCandidates = @(
        "$env:USERPROFILE\.local\bin\uv.exe",
        "$env:LOCALAPPDATA\Programs\uv\uv.exe"
    )
    foreach ($c in $uvCandidates) {
        if (Test-Path $c) { $uv = $c; break }
    }
}
if (-not $uv) { throw "uv not found. Install from https://docs.astral.sh/uv/" }

Write-Host "=== OpenJarvis Mic Fix ===" -ForegroundColor Cyan
Write-Host ""

Write-Host "[1/5] Installing Python dependencies..." -ForegroundColor Yellow
& $uv sync --extra speech --extra speech-tts --extra server
if ($LASTEXITCODE -ne 0) { throw "uv sync failed" }

Write-Host ""
Write-Host "[2/5] Checking ffmpeg..." -ForegroundColor Yellow
$ffmpeg = Get-Command ffmpeg -ErrorAction SilentlyContinue
if (-not $ffmpeg) {
    Write-Host "  Installing ffmpeg via winget..." -ForegroundColor Yellow
    winget install --id Gyan.FFmpeg -e --accept-source-agreements --accept-package-agreements
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" +
                [System.Environment]::GetEnvironmentVariable("Path", "User")
}
$ffmpeg = Get-Command ffmpeg -ErrorAction SilentlyContinue
if ($ffmpeg) {
    Write-Host "  OK: $($ffmpeg.Source)" -ForegroundColor Green
} else {
    Write-Host "  WARNING: ffmpeg still not found. Mic will fail until installed." -ForegroundColor Red
}

Write-Host ""
Write-Host "[3/5] Building frontend..." -ForegroundColor Yellow
Push-Location (Join-Path $Root "frontend")
npm install
if ($LASTEXITCODE -ne 0) { Pop-Location; throw "npm install failed" }
npm run build
if ($LASTEXITCODE -ne 0) { Pop-Location; throw "npm run build failed" }
Pop-Location
Write-Host "  OK: static UI built into src/openjarvis/server/static" -ForegroundColor Green

Write-Host ""
Write-Host "[4/5] Restarting backend..." -ForegroundColor Yellow
& "$PSScriptRoot\restart-server.ps1"

Write-Host ""
Write-Host "[5/5] Running speech diagnosis..." -ForegroundColor Yellow
Start-Sleep -Seconds 5
& "$PSScriptRoot\diagnose-speech.ps1"

Write-Host ""
Write-Host "=== Done ===" -ForegroundColor Green
Write-Host "Open in Edge: http://127.0.0.1:8000"
Write-Host "Dev mode UI: http://localhost:5173"
Write-Host "Mic test: enable Speech-to-Text in Settings, then use the mic button."
