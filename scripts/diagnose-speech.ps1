# Diagnose OpenJarvis STT and TTS on the running server.
$ErrorActionPreference = "Continue"
$Base = "http://127.0.0.1:8000"
$Root = Split-Path $PSScriptRoot -Parent
$Python = Join-Path $Root ".venv\Scripts\python.exe"

Write-Host "=== OpenJarvis Speech Diagnosis ===" -ForegroundColor Cyan
Write-Host ""

Write-Host "[1] Server health"
try {
    $health = Invoke-RestMethod "$Base/health" -TimeoutSec 5
    Write-Host "  OK: $($health.status)" -ForegroundColor Green
} catch {
    Write-Host "  FAIL: Backend not running on $Base" -ForegroundColor Red
    Write-Host "  Run: .\scripts\start-jarvis.ps1"
    exit 1
}

Write-Host ""
Write-Host "[2] STT health (/v1/speech/health)"
try {
    $stt = Invoke-RestMethod "$Base/v1/speech/health" -TimeoutSec 10
    if ($stt.available) {
        Write-Host "  OK: $($stt.backend)" -ForegroundColor Green
    } else {
        Write-Host "  FAIL: $($stt.reason)" -ForegroundColor Red
    }
} catch {
    Write-Host "  FAIL: $_" -ForegroundColor Red
}

Write-Host ""
Write-Host "[3] TTS health (/v1/speech/tts/health)"
try {
    $tts = Invoke-RestMethod "$Base/v1/speech/tts/health" -TimeoutSec 10
    if ($tts.available) {
        Write-Host "  OK: $($tts.backend)" -ForegroundColor Green
    } else {
        Write-Host "  FAIL: $($tts.reason)" -ForegroundColor Red
    }
} catch {
    Write-Host "  FAIL: $_" -ForegroundColor Red
}

Write-Host ""
Write-Host "[4] Python speech packages"
if (Test-Path $Python) {
    & $Python -c @"
mods = ['faster_whisper', 'edge_tts']
import importlib.util as u
for m in mods:
    print(f'  {m}:', 'OK' if u.find_spec(m) else 'MISSING')
"@
} else {
    Write-Host "  SKIP: python not found at $Python" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "[5] ffmpeg (required for browser webm audio)"
$ffmpeg = (Get-Command ffmpeg -ErrorAction SilentlyContinue).Source
if ($ffmpeg) {
    Write-Host "  OK: $ffmpeg" -ForegroundColor Green
} else {
    Write-Host "  FAIL: ffmpeg not on PATH" -ForegroundColor Red
}

Write-Host ""
Write-Host "[6] TTS synthesize smoke test"
try {
    $body = @{ text = "Hello. Speech diagnosis complete." } | ConvertTo-Json
    $resp = Invoke-WebRequest "$Base/v1/speech/synthesize" -Method POST -Body $body -ContentType "application/json" -TimeoutSec 60 -UseBasicParsing
    Write-Host "  OK: $($resp.RawContentLength) bytes, $($resp.Headers['Content-Type'])" -ForegroundColor Green
} catch {
    Write-Host "  FAIL: $_" -ForegroundColor Red
}

Write-Host ""
Write-Host "[7] STT transcribe smoke test (synthetic webm via Python)"
if (Test-Path $Python) {
    $testScript = Join-Path $Root "tmp\test_api_speech.py"
    if (Test-Path $testScript) {
        try {
            & $Python $testScript 2>&1
        } catch {
            Write-Host "  FAIL: $_" -ForegroundColor Red
        }
    } else {
        Write-Host "  SKIP: $testScript not found" -ForegroundColor Yellow
    }
} else {
    Write-Host "  SKIP" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "=== Voice conversation checklist ==="
Write-Host "  Settings -> Speech-to-Text: ON"
Write-Host "  Settings -> Voice replies: ON"
Write-Host "  Settings -> Auto-send after dictation: ON"
Write-Host "  Mic is only blocked while transcribing or while Jarvis is generating a reply."
