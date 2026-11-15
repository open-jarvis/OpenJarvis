# Restart the separate local OpenJarvis installation (no installation needed).
$ErrorActionPreference = 'Stop'
$root = Join-Path $env:LOCALAPPDATA 'OpenJarvis-Offline'
$src = Join-Path $root 'src'
$voiceDir = Join-Path $src 'jarvis_voice_setup'
$python = Join-Path $env:USERPROFILE '.openjarvis\offline-voice-venv\Scripts\python.exe'
$voice = Join-Path $voiceDir 'voice_server.py'
$jarvis = Join-Path $src '.venv\Scripts\jarvis.exe'
foreach ($path in @($python,$voice,$jarvis)) {
    if (-not (Test-Path -LiteralPath $path)) {
        throw 'OpenJarvis is not installed yet. Run START_OFFLINE_JARVIS_WINDOWS.bat first.'
    }
}
$env:OPENJARVIS_HOME = $root
$ready = $false
try {
    $status = Invoke-RestMethod -Uri 'http://127.0.0.1:4701/health' -TimeoutSec 2
    $ready = ($status.ready -eq $true)
} catch { }
if (-not $ready) {
    Start-Process -FilePath $python -ArgumentList ('"' + $voice + '"') -WorkingDirectory $voiceDir | Out-Null
    for ($i = 0; $i -lt 20; $i++) {
        Start-Sleep -Seconds 1
        try {
            $status = Invoke-RestMethod -Uri 'http://127.0.0.1:4701/health' -TimeoutSec 2
            if ($status.ready -eq $true) { $ready = $true; break }
        } catch { }
    }
}
if (-not $ready) {
    throw 'Local voice service did not start. Use 02_Start_Offline_Voice.bat to view the error.'
}
Push-Location $src
try {
    & $jarvis chat --voice
} finally {
    Pop-Location
}
