[CmdletBinding()]
param(
    [string]$RuntimeRoot = "",
    [switch]$Warmup
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
if (-not $RuntimeRoot) {
    $RuntimeRoot = Join-Path (Split-Path $repoRoot -Parent) "openjarvis-runtime"
}
$runtimePath = [System.IO.Path]::GetFullPath($RuntimeRoot)
$voicePython = Join-Path $repoRoot ".venv-voice\Scripts\python.exe"
$requirements = Join-Path $repoRoot "configs\voice\requirements-windows.txt"
$piperModels = Join-Path $runtimePath "voice\models\piper"
$hfHome = Join-Path $runtimePath "voice\models\huggingface"

if (-not (Test-Path -LiteralPath $voicePython -PathType Leaf)) {
    $basePython = Get-Command python.exe -ErrorAction Stop
    $baseMinor = (& $basePython.Source -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')").Trim()
    if ($baseMinor -ne "3.11") {
        throw "Python 3.11 is required to create .venv-voice; found Python $baseMinor at $($basePython.Source)"
    }
    & $basePython.Source -m venv (Join-Path $repoRoot ".venv-voice")
}

$voiceMinor = (& $voicePython -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')").Trim()
if ($voiceMinor -ne "3.11") {
    throw ".venv-voice must use Python 3.11; found Python $voiceMinor"
}

& $voicePython -m pip install --upgrade "pip==26.2" "wheel==0.47.0"
& $voicePython -m pip install --requirement $requirements
& $voicePython -m pip check

New-Item -ItemType Directory -Force -Path $piperModels, $hfHome | Out-Null
& $voicePython -m piper.download_voices `
    --download-dir $piperModels `
    de_DE-thorsten-high

$env:HF_HOME = $hfHome
$env:HUGGINGFACE_HUB_CACHE = Join-Path $hfHome "hub"
$env:HF_HUB_DISABLE_TELEMETRY = "1"
$env:DO_NOT_TRACK = "1"

& $voicePython -c @"
import torch
from chatterbox.mtl_tts import ChatterboxMultilingualTTS
from piper.voice import PiperVoice
print(f"torch={torch.__version__}")
print(f"cuda={torch.cuda.is_available()}")
print(f"device={torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'cpu'}")
print("imports=ok")
"@

if ($Warmup) {
    & $voicePython -c @"
from chatterbox.mtl_tts import ChatterboxMultilingualTTS
model = ChatterboxMultilingualTTS.from_pretrained(device="cuda", t3_model="v3")
print(f"chatterbox_v3_sample_rate={model.sr}")
"@
}

Write-Output "Local voice environment is ready: $voicePython"
Write-Output "Voice runtime: $runtimePath\voice"
