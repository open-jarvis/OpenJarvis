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
$runtimePython = Join-Path $repoRoot ".venv\Scripts\python.exe"
$requirements = Join-Path $repoRoot "configs\speech\requirements-windows.txt"
$modelRoot = Join-Path $runtimePath "speech\models"
$hfHome = Join-Path $modelRoot "huggingface"

if (-not (Test-Path -LiteralPath $runtimePython -PathType Leaf)) {
    throw "Repository Python is missing: $runtimePython"
}

$runtimeMinor = (& $runtimePython -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')").Trim()
if ($runtimeMinor -ne "3.11") {
    throw ".venv must use Python 3.11; found Python $runtimeMinor"
}

& $runtimePython -m pip --version *> $null
if ($LASTEXITCODE -ne 0) {
    & $runtimePython -m ensurepip --upgrade
}

& $runtimePython -m pip install --requirement $requirements
if ($LASTEXITCODE -ne 0) { throw "Local speech dependency installation failed." }
& $runtimePython -m pip check
if ($LASTEXITCODE -ne 0) { throw "Local speech dependency check failed." }

New-Item -ItemType Directory -Force -Path $modelRoot, $hfHome | Out-Null
$env:HF_HOME = $hfHome
$env:HUGGINGFACE_HUB_CACHE = Join-Path $hfHome "hub"
$env:HF_HUB_DISABLE_TELEMETRY = "1"
$env:DO_NOT_TRACK = "1"

& $runtimePython -c "from importlib.metadata import version; import faster_whisper; print('faster_whisper=' + version('faster-whisper')); print('imports=ok')"
if ($LASTEXITCODE -ne 0) { throw "Local speech import check failed." }

if ($Warmup) {
    $env:OPENJARVIS_STT_MODEL_ROOT = $modelRoot
    & $runtimePython -c "import os; from faster_whisper import WhisperModel; WhisperModel('base', device='cpu', compute_type='int8', download_root=os.environ['OPENJARVIS_STT_MODEL_ROOT']); print('faster_whisper_base=ready')"
    if ($LASTEXITCODE -ne 0) { throw "Local speech model warmup failed." }
}

Write-Output "Local speech environment is ready: $runtimePython"
Write-Output "Speech runtime: $runtimePath\speech"
