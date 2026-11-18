# Instalador de un solo comando de Jarvis (HUD de voz + cerebro en Gemini).
#
# Uso, en PowerShell:
#   irm https://raw.githubusercontent.com/Juanesinfante/OpenJarvis/feature/jarvis-hud/scripts/jarvis-setup.ps1 | iex
#
# Requiere que el instalador oficial de OpenJarvis ya haya terminado.
# Se puede repetir sin riesgo: deja todo en el mismo estado final.

function Install-JarvisHud {
    $ErrorActionPreference = 'Stop'
    $RepoUrl = 'https://github.com/Juanesinfante/OpenJarvis.git'
    $Branch = 'feature/jarvis-hud'
    # Probado con una clave gratuita de AI Studio: responde en ~1 s.
    $Model = 'gemini-3.1-flash-lite-preview'
    $Src = Join-Path $env:LOCALAPPDATA 'OpenJarvis\src'
    $HudUrl = 'http://127.0.0.1:8000/hud'
    $GeminiUrl = "https://generativelanguage.googleapis.com/v1beta/models/${Model}:generateContent"

    function Step([string] $text) { Write-Host "`n==> $text" -ForegroundColor Cyan }
    function Ok([string] $text) { Write-Host "    $text" -ForegroundColor Green }
    function Warn([string] $text) { Write-Host "    $text" -ForegroundColor Yellow }

    # Prueba la clave contra Gemini con .NET (no con Python), con límite de 30 s.
    function Test-GeminiKey([string] $key) {
        $body = @{ contents = @(@{ parts = @(@{ text = 'Responde solo con la palabra: listo' }) }) } |
            ConvertTo-Json -Depth 6
        $clock = [Diagnostics.Stopwatch]::StartNew()
        try {
            $reply = Invoke-RestMethod -Method Post -Uri $GeminiUrl -TimeoutSec 30 `
                -Headers @{ 'x-goog-api-key' = $key } -ContentType 'application/json' -Body $body
            $text = $reply.candidates[0].content.parts[0].text
            return @{ Status = 'ok'; Detail = "respondió '$($text.Trim())' en $([int]$clock.Elapsed.TotalSeconds) s" }
        } catch {
            $code = 0
            if ($_.Exception.Response) { $code = [int]$_.Exception.Response.StatusCode }
            if ($code -in 400, 401, 403) { return @{ Status = 'invalid'; Detail = "Google rechazó la clave (HTTP $code)" } }
            if ($code -eq 429) { return @{ Status = 'quota'; Detail = 'sin cupo gratuito en este momento (HTTP 429)' } }
            return @{ Status = 'network'; Detail = "sin respuesta de Google: $($_.Exception.Message)" }
        }
    }

    # --- 1. Requisitos --------------------------------------------------------
    Step 'Comprobando la instalación de OpenJarvis'
    if (-not (Test-Path (Join-Path $Src '.git'))) {
        throw "No encuentro OpenJarvis en $Src. Ejecute primero el instalador oficial."
    }
    $git = (Get-Command git -ErrorAction SilentlyContinue).Source
    $uv = (Get-Command uv -ErrorAction SilentlyContinue).Source
    if (-not $uv) { $uv = Join-Path $env:USERPROFILE '.local\bin\uv.exe' }
    if (-not $git) { throw 'No encuentro git. Instálelo con: winget install Git.Git' }
    if (-not (Test-Path $uv)) { throw 'No encuentro uv. Repita el instalador oficial de OpenJarvis.' }
    Ok "OpenJarvis en $Src"

    # --- 2. Detener Jarvis ----------------------------------------------------
    # Un servidor en marcha bloquea archivos que hay que reemplazar.
    Step 'Deteniendo Jarvis si está corriendo'
    Stop-ScheduledTask -TaskName 'OpenJarvis' -ErrorAction SilentlyContinue
    Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -match 'jarvis(\.exe)?"?\s+serve' } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    try {
        Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction Stop |
            ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }
    } catch { }  # nada escuchando en el puerto 8000
    Start-Sleep -Seconds 2
    Ok 'Jarvis detenido'

    # --- 3. Código ------------------------------------------------------------
    Step 'Descargando la última versión de Jarvis'
    & $git -C $Src fetch $RepoUrl $Branch
    if ($LASTEXITCODE -ne 0) { throw 'git fetch falló. Revise su conexión a internet.' }
    # Se limpia solo la interfaz compilada: archivos de versiones anteriores.
    # Sin redirigir stderr: en Windows PowerShell 5.1, con 'Stop', un aviso de git sería fatal.
    & $git -C $Src clean -fdxq -- 'src/openjarvis/server/static'
    # -f reemplaza los archivos que dejaron los kits anteriores.
    & $git -C $Src checkout -f -B 'jarvis-hud' FETCH_HEAD
    if ($LASTEXITCODE -ne 0) { throw 'git checkout falló.' }
    Ok "Código actualizado ($(& $git -C $Src rev-parse --short HEAD))"

    # --- 4. Dependencias ------------------------------------------------------
    Step 'Instalando dependencias (Gemini; se retira la voz local que gastaba memoria)'
    Push-Location $Src
    try {
        & $uv sync --extra desktop --extra inference-google --group desktop-native
        if ($LASTEXITCODE -ne 0) { throw 'uv sync falló. Copie el error de arriba.' }
    } finally { Pop-Location }
    Ok 'Dependencias listas'

    # --- 5. Clave de Gemini ---------------------------------------------------
    Step 'Clave de Gemini'
    $key = [Environment]::GetEnvironmentVariable('GEMINI_API_KEY', 'User')
    $check = $null
    if ($key) {
        $check = Test-GeminiKey $key
        if ($check.Status -eq 'invalid') { Warn "La clave guardada no sirve: $($check.Detail)"; $key = $null }
        else { Ok 'Usando la clave guardada' }
    }
    $attempts = 0
    while (-not $key) {
        $attempts += 1
        if ($attempts -gt 3) { throw 'No se obtuvo una clave válida. Créela en https://aistudio.google.com/apikey' }
        Write-Host '    Créela en https://aistudio.google.com/apikey (gratis, sin tarjeta).'
        $secure = Read-Host '    Pegue su clave de Gemini y pulse Enter (verá asteriscos)' -AsSecureString
        $candidate = [Net.NetworkCredential]::new('', $secure).Password.Trim()
        if (-not $candidate) { continue }
        $check = Test-GeminiKey $candidate
        if ($check.Status -eq 'invalid') { Warn $check.Detail; continue }
        $key = $candidate
    }
    # Variables del usuario: el servidor y la tarea de inicio automático las heredan.
    [Environment]::SetEnvironmentVariable('GEMINI_API_KEY', $key, 'User')
    [Environment]::SetEnvironmentVariable('HF_HUB_DISABLE_XET', '1', 'User')
    # Gemini por su API compatible con OpenAI: la nativa rechazaba las herramientas de Jarvis.
    [Environment]::SetEnvironmentVariable('GEMINI_OPENAI_COMPAT', '1', 'User')
    $env:GEMINI_API_KEY = $key
    $env:HF_HUB_DISABLE_XET = '1'
    $env:GEMINI_OPENAI_COMPAT = '1'
    switch ($check.Status) {
        'ok' { Ok "Gemini desde este PC: $($check.Detail)" }
        'quota' { Warn "Gemini: $($check.Detail). Funcionará cuando se renueve el cupo." }
        default { Warn "Gemini desde este PC: $($check.Detail). Revise antivirus o VPN." }
    }

    # --- 6. Configuración -----------------------------------------------------
    Step 'Configurando Jarvis'
    Push-Location $Src
    try {
        $configPath = (& $uv run python -c 'from openjarvis.core.config import get_config_path; print(get_config_path())').Trim()
        if (-not (Test-Path $configPath)) {
            & $uv run jarvis init --no-analytics --engine ollama --no-download --no-scan
            if ($LASTEXITCODE -ne 0) { throw 'jarvis init falló.' }
        }
        & $uv run python scripts/jarvis_setup.py --model $Model
        if ($LASTEXITCODE -ne 0) { throw 'La configuración falló. Copie el error de arriba.' }
    } finally { Pop-Location }

    # --- 7. Arrancar ----------------------------------------------------------
    Step 'Arrancando Jarvis'
    # Ventana propia y minimizada: hereda la clave y muestra el registro si algo falla.
    $shell = (Get-Process -Id $PID).Path
    $command = "Set-Location '$Src'; `$host.UI.RawUI.WindowTitle = 'Jarvis (servidor) - no cerrar'; & '$uv' run jarvis serve"
    Start-Process -FilePath $shell -ArgumentList @('-NoExit', '-Command', $command) -WindowStyle Minimized
    $ready = $false
    foreach ($i in 1..90) {
        try {
            Invoke-WebRequest 'http://127.0.0.1:8000/health' -UseBasicParsing -TimeoutSec 2 | Out-Null
            $ready = $true; break
        } catch { Start-Sleep -Seconds 2 }
    }
    if (-not $ready) { throw 'El servidor no arrancó en 3 minutos. Abra la ventana "Jarvis (servidor)" y copie el error.' }
    $info = Invoke-RestMethod 'http://127.0.0.1:8000/v1/info' -TimeoutSec 10
    Ok "Servidor listo: modelo $($info.model)"

    # --- 8. Prueba de punta a punta ------------------------------------------
    Step 'Probando a Jarvis (puede tardar unos segundos)'
    $request = @{ model = $info.model; messages = @(@{ role = 'user'; content = 'Responde solo con la palabra: listo' }) } |
        ConvertTo-Json -Depth 5
    $clock = [Diagnostics.Stopwatch]::StartNew()
    try {
        $answer = Invoke-RestMethod -Method Post -Uri 'http://127.0.0.1:8000/v1/chat/completions' -TimeoutSec 120 `
            -ContentType 'application/json; charset=utf-8' -Body ([Text.Encoding]::UTF8.GetBytes($request))
        Ok "Jarvis respondió '$($answer.choices[0].message.content.Trim())' en $([int]$clock.Elapsed.TotalSeconds) s"
    } catch {
        Warn "Jarvis no respondió: $($_.Exception.Message)"
        Warn 'Abra la ventana "Jarvis (servidor)" y copie las últimas líneas para revisarlo.'
    }

    # --- 9. Abrir el HUD --------------------------------------------------------
    Step 'Abriendo el HUD'
    try { Start-Process 'msedge.exe' $HudUrl } catch { Start-Process $HudUrl }
    Write-Host "`nListo. Jarvis está en $HudUrl (mejor en Edge, por sus voces en español)." -ForegroundColor Green
    Write-Host 'Pulse "Iniciar sistemas" y diga: "Jarvis, ¿cuánto es 345 por 27?"'
    Write-Host 'Al reiniciar el PC, Jarvis arranca solo con la tarea programada OpenJarvis.'
}

try {
    Install-JarvisHud
} catch {
    Write-Host "`n[error] $($_.Exception.Message)" -ForegroundColor Red
    Write-Host 'Copie este mensaje y envíelo para revisarlo.' -ForegroundColor Red
}
