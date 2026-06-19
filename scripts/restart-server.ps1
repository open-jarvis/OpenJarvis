# Restart OpenJarvis API server on port 8000
$ErrorActionPreference = "Continue"
$Port = 8000
$Root = Split-Path $PSScriptRoot -Parent

Write-Host "Stopping anything on port $Port..."
$connections = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
foreach ($conn in $connections) {
    $procId = $conn.OwningProcess
    Write-Host "  Killing PID $procId"
    Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
    taskkill /F /PID $procId 2>$null | Out-Null
}
Start-Sleep -Seconds 2

$still = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if ($still) {
    Write-Host "ERROR: Port $Port still in use. Close the OpenJarvis desktop app, then run this script again." -ForegroundColor Red
    exit 1
}

Write-Host "Starting Jarvis server..."
$jarvis = Join-Path $Root ".venv\Scripts\jarvis.exe"
if (-not (Test-Path $jarvis)) {
    Write-Host "ERROR: jarvis.exe not found at $jarvis" -ForegroundColor Red
    exit 1
}

# Ensure ffmpeg is on PATH for the server process (Edge webm conversion).
$ffmpeg = Get-Command ffmpeg -ErrorAction SilentlyContinue
if ($ffmpeg) {
    $ffmpegDir = Split-Path $ffmpeg.Source -Parent
    if ($env:Path -notlike "*$ffmpegDir*") {
        $env:Path = "$ffmpegDir;$env:Path"
    }
}

Start-Process -FilePath $jarvis -ArgumentList "serve" -WorkingDirectory $Root -WindowStyle Normal
Start-Sleep -Seconds 8

Write-Host "Checking health..."
try {
    $health = Invoke-RestMethod "http://127.0.0.1:$Port/v1/speech/health" -TimeoutSec 10
    Write-Host "STT: $($health | ConvertTo-Json -Compress)"
    $tts = Invoke-RestMethod "http://127.0.0.1:$Port/v1/speech/tts/health" -TimeoutSec 10
    Write-Host "TTS: $($tts | ConvertTo-Json -Compress)"
} catch {
    Write-Host "Server may still be starting: $_" -ForegroundColor Yellow
}

Write-Host "Done. Server URL: http://127.0.0.1:$Port"
