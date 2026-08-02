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
$referenceSource = Join-Path $repoRoot "configs\voice\references"
$referenceManifestPath = Join-Path $referenceSource "manifest.json"
$referenceModels = Join-Path $runtimePath "voice\models\references"

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
if ($LASTEXITCODE -ne 0) { throw "Voice pip bootstrap failed" }
& $voicePython -m pip install --requirement $requirements
if ($LASTEXITCODE -ne 0) { throw "Voice dependency installation failed" }
& $voicePython -m pip check
if ($LASTEXITCODE -ne 0) { throw "Voice dependency check failed" }

New-Item -ItemType Directory -Force -Path $piperModels, $hfHome, $referenceModels | Out-Null

$referenceManifest = Get-Content -Raw -LiteralPath $referenceManifestPath | ConvertFrom-Json
foreach ($asset in $referenceManifest.assets) {
    $source = Join-Path $referenceSource $asset.file
    $destination = Join-Path $referenceModels $asset.file
    if (-not (Test-Path -LiteralPath $source -PathType Leaf)) {
        throw "Voice reference is missing: $source"
    }
    $sourceHash = (Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($sourceHash -ne $asset.sha256) {
        throw "Voice reference hash mismatch: $source"
    }
    Copy-Item -LiteralPath $source -Destination $destination -Force
    $destinationHash = (Get-FileHash -LiteralPath $destination -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($destinationHash -ne $asset.sha256) {
        throw "Deployed voice reference hash mismatch: $destination"
    }
}

& $voicePython -m piper.download_voices `
    --download-dir $piperModels `
    de_DE-thorsten-high
if ($LASTEXITCODE -ne 0) { throw "Piper model download failed" }

$env:HF_HOME = $hfHome
$env:HUGGINGFACE_HUB_CACHE = Join-Path $hfHome "hub"
$env:HF_HUB_DISABLE_TELEMETRY = "1"
$env:DO_NOT_TRACK = "1"

$importCheck = @'
import torch
from chatterbox.mtl_tts import ChatterboxMultilingualTTS
from piper.voice import PiperVoice
print(f"torch={torch.__version__}")
print(f"cuda={torch.cuda.is_available()}")
print(f"device={torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'cpu'}")
print("imports=ok")
'@
$importCheck | & $voicePython -
if ($LASTEXITCODE -ne 0) { throw "Voice runtime import check failed" }

if ($Warmup) {
    $warmupCheck = @'
from chatterbox.mtl_tts import ChatterboxMultilingualTTS
model = ChatterboxMultilingualTTS.from_pretrained(device="cuda", t3_model="v3")
print(f"chatterbox_v3_sample_rate={model.sr}")
'@
    $warmupCheck | & $voicePython -
    if ($LASTEXITCODE -ne 0) { throw "Chatterbox warmup failed" }
}

Write-Output "Local voice environment is ready: $voicePython"
Write-Output "Voice runtime: $runtimePath\voice"
