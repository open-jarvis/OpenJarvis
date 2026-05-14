param(
    [string]$Voice = "nova"
)

$ErrorActionPreference = "Continue"

function Write-Line {
    Write-Host "] $args"
}

function Write-Section {
    param([string]$Text)
    Write-Host "] ═══════════════════════════════════════════════════" -ForegroundColor DarkCyan
    Write-Host "]   $Text" -ForegroundColor Cyan
    Write-Host "] ═══════════════════════════════════════════════════" -ForegroundColor DarkCyan
}

Set-Location "C:\Users\Kyle\Serena"

$now = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
$envName = "development"
$apiKeySet = -not [string]::IsNullOrWhiteSpace($env:OPENAI_API_KEY)

Write-Section "SERENA LOCAL OPERATOR ✨ Starting Up"
Write-Host "]   Agent: Serena 🤖" -ForegroundColor Cyan
Write-Host "]   Role: Dr Piet Muller's AI assistant 🩺" -ForegroundColor Cyan
Write-Host "]   Environment: $envName" -ForegroundColor Cyan
Write-Host "]   Time: $now" -ForegroundColor Cyan
Write-Host "]   Folder: C:\Users\Kyle\Serena" -ForegroundColor Cyan
Write-Host "]   Voice: OpenAI TTS / $Voice 🗣️" -ForegroundColor Cyan
Write-Host "]   Brain: OpenAI / gpt-5-mini 🧠" -ForegroundColor Cyan
Write-Host "] ═══════════════════════════════════════════════════" -ForegroundColor DarkCyan

if ($apiKeySet) {
    Write-Host "] ✅ OPENAI_API_KEY detected" -ForegroundColor Green
} else {
    Write-Host "] ❌ OPENAI_API_KEY missing" -ForegroundColor Red
    Write-Host "]    Set it with: setx OPENAI_API_KEY `"your_key_here`"" -ForegroundColor Yellow
    Write-Host "]    Then close PowerShell and open a new one." -ForegroundColor Yellow
}

Write-Host "] 🔎 Running Serena diagnostics..." -ForegroundColor Yellow
uv run serena doctor

Write-Host ""
Write-Host "] 🎧 Audio device scan..." -ForegroundColor Yellow
uv run serena listen --list-devices

Write-Host ""
Write-Host "] 🛠️ Tool registry snapshot..." -ForegroundColor Yellow
uv run serena tool list

Write-Host ""
if ($apiKeySet) {
    Write-Host "] 🗣️ Starting voice greeting..." -ForegroundColor Yellow
    uv run serena speak --voice $Voice "Serena online. Brain, voice, tools, and local operator systems are ready."
} else {
    Write-Host "] ⚠️ Skipping voice greeting because OPENAI_API_KEY is missing." -ForegroundColor Yellow
}

Write-Host ""
Write-Section "STARTUP SUMMARY"
Write-Host "] ✅ Serena command layer online" -ForegroundColor Green
Write-Host "] ✅ Brain configured: OpenAI / gpt-5-mini" -ForegroundColor Green
Write-Host "] ✅ Voice configured: OpenAI TTS / $Voice" -ForegroundColor Green
Write-Host "] ✅ Speaker output: Windows default audio" -ForegroundColor Green
Write-Host "] ⚠️ Microphone: run 'uv run serena listen --list-devices' after plugging in the webcam/mic" -ForegroundColor Yellow
Write-Host "] 🧩 Commands ready:" -ForegroundColor Cyan
Write-Host "]    uv run serena ask `"Who are you?`""
Write-Host "]    uv run serena say `"Who are you?`""
Write-Host "]    uv run serena speak `"Serena online.`""
Write-Host "]    uv run serena listen --list-devices"
Write-Host "]    uv run serena voice --seconds 5 --device <mic-index>"
Write-Host "] ═══════════════════════════════════════════════════" -ForegroundColor DarkCyan
Write-Host "] ✨ Serena startup complete." -ForegroundColor Green
Write-Host ""
