# Setup the user's separate local OpenJarvis, including an offline voice.
# The existing Jarvis application and its files are not touched.
$ErrorActionPreference = 'Stop'
$repo = 'https://github.com/itsHALE101/OpenJarvis.git'
$root = Join-Path $env:LOCALAPPDATA 'OpenJarvis-Offline'
$src = Join-Path $root 'src'
$home = Join-Path $env:USERPROFILE '.openjarvis'
$folder = Split-Path -Parent $MyInvocation.MyCommand.Path
$parent = (Resolve-Path (Join-Path $folder '..')).Path
$upstream = Join-Path $parent 'deploy\windows\install.ps1'
if (-not (Test-Path $upstream)) {
    throw "Installer missing: $upstream. Extract the whole ZIP, then retry."
}

Write-Host '=== OFFLINE JARVIS for Windows ===' -ForegroundColor Cyan
Write-Host "Your separate installation: $root"
Write-Host 'This uses local Ollama, local Whisper, and local Piper speech.'
Write-Host 'Initial downloads require internet. No paid voice API is enabled.'
Write-Host 'Existing Jarvis application files will not be overwritten.'
Write-Host ''

$oldRepo = $env:OPENJARVIS_REPO_URL
$oldRoot = $env:OPENJARVIS_HOME
$oldSkip = $env:OPENJARVIS_SKIP_SERVICE
try {
    if (Test-Path (Join-Path $src '.git')) {
        $git = (Get-Command git -ErrorAction SilentlyContinue).Source
        if (-not $git) { throw 'Git is missing. Run the native installer first.' }
        $origin = & $git -C $src remote get-url origin
        if (($LASTEXITCODE -ne 0) -or ($origin -notmatch 'itsHALE101/OpenJarvis(\.git)?$')) {
            throw 'An unrelated project occupies the target folder. Refusing to overwrite it.'
        }
    }

    $env:OPENJARVIS_REPO_URL = $repo
    $env:OPENJARVIS_HOME = $root
    $env:OPENJARVIS_SKIP_SERVICE = '1'
    Write-Host '[1/5] Installing OpenJarvis and the local AI model...' -ForegroundColor Cyan
    & $upstream -SkipService
    if ($LASTEXITCODE -and $LASTEXITCODE -ne 0) { throw "Installer returned code $LASTEXITCODE" }

    $voiceDir = Join-Path $src 'jarvis_voice_setup'
    $ttsModule = Join-Path $src 'src\openjarvis\speech\jarvis_local_tts.py'
    if (-not (Test-Path $ttsModule)) { throw 'Local voice integration missing from clone.' }
    if (-not (Test-Path (Join-Path $voiceDir '01_Setup_Offline_Voice.bat'))) {
        throw 'Offline voice setup missing from clone.'
    }

    $uv = (Get-Command uv -ErrorAction SilentlyContinue).Source
    if (-not $uv) { $uv = Join-Path $env:USERPROFILE '.local\bin\uv.exe' }
    if (-not (Test-Path $uv)) { throw 'uv missing after installation.' }

    Write-Host '[2/5] Installing the British Piper voice...' -ForegroundColor Cyan
    & (Join-Path $voiceDir '01_Setup_Offline_Voice.bat')
    if ($LASTEXITCODE -ne 0) { throw 'Local Piper voice setup failed.' }

    Write-Host '[3/5] Installing local microphone and voice playback dependencies...' -ForegroundColor Cyan
    Push-Location $src
    try {
        & $uv sync --extra desktop --extra speech --extra voice --group desktop-native
        if ($LASTEXITCODE -ne 0) { throw 'Speech dependencies failed to install.' }
    } finally { Pop-Location }

    Write-Host '[4/5] Configuring Jarvis and backing up existing settings...' -ForegroundColor Cyan
    $python = Join-Path $src '.venv\Scripts\python.exe'
    if (-not (Test-Path $python)) { throw 'OpenJarvis Python environment missing.' }
    & $python (Join-Path $voiceDir 'configure_voice.py')
    if ($LASTEXITCODE -ne 0) { throw 'Jarvis configuration failed.' }

    Write-Host '[5/5] Starting the local offline voice...' -ForegroundColor Cyan
    $voicePython = Join-Path $home 'offline-voice-venv\Scripts\python.exe'
    $voiceServer = Join-Path $voiceDir 'voice_server.py'
    if (-not (Test-Path $voicePython)) { throw 'Offline voice Python missing.' }
    $ready = $false
    try {
        $check = Invoke-RestMethod -Uri 'http://127.0.0.1:4701/health' -TimeoutSec 2
        $ready = ($check.ready -eq $true)
    } catch { }
    if (-not $ready) {
        Start-Process -FilePath $voicePython -ArgumentList ('"' + $voiceServer + '"') -WorkingDirectory $voiceDir
        for ($i = 0; $i -lt 40; $i++) {
            Start-Sleep -Milliseconds 500
            try {
                $check = Invoke-RestMethod -Uri 'http://127.0.0.1:4701/health' -TimeoutSec 2
                if ($check.ready -eq $true) { $ready = $true; break }
            } catch { }
        }
    }
    if (-not $ready) { throw 'Local speech service not ready. Run 02_Start_Offline_Voice.bat to inspect.' }

    $wav = Join-Path $env:TEMP 'jarvis_local_voice_test.wav'
    $params = @{
        Uri = 'http://127.0.0.1:4701/speak'
        Method = 'POST'
        ContentType = 'application/json'
        Body = '{"text":"Good day sir. Your offline Jarvis is now ready."}'
        OutFile = $wav
        UseBasicParsing = $true
        TimeoutSec = 180
    }
    Invoke-WebRequest @params
    if (-not (Test-Path $wav) -or (Get-Item $wav).Length -lt 44) {
        throw 'Local voice returned no usable WAV data.'
    }
    Write-Host "Test voice created successfully: $wav" -ForegroundColor Green
    Start-Process -FilePath $wav
    Write-Host ''
    Write-Host 'Setup completed. Starting Jarvis voice chat...' -ForegroundColor Green
    $jarvisExe = Join-Path $src '.venv\Scripts\jarvis.exe'
    if (-not (Test-Path $jarvisExe)) { throw 'Jarvis CLI missing after install.' }
    Push-Location $src
    try { & $jarvisExe chat --voice }
    finally { Pop-Location }
} finally {
    $env:OPENJARVIS_REPO_URL = $oldRepo
    $env:OPENJARVIS_HOME = $oldRoot
    $env:OPENJARVIS_SKIP_SERVICE = $oldSkip
}
