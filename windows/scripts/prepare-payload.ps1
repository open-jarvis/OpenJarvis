# Downloads embeddable CPython 3.12 win-arm64, syncs OpenJarvis with --extra server
# --group desktop-native, and stages payload next to the published WinUI app.
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$PublishDir,
    [string]$PythonVersion = "3.12.10",
    [string]$FoundryVersion = "0.11.0"
)

$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$Payload = Join-Path $PublishDir "payload"
New-Item -ItemType Directory -Force -Path $Payload | Out-Null

$Arch = [System.Runtime.InteropServices.RuntimeInformation]::OSArchitecture
if ($Arch -ne "Arm64") {
    Write-Warning "This script is intended for Windows ARM64. Current architecture: $Arch"
}

$PythonZip = Join-Path $env:TEMP "python-$PythonVersion-arm64.zip"
$PythonUrl = "https://www.python.org/ftp/python/$PythonVersion/python-$PythonVersion-embed-arm64.zip"
Write-Host "Downloading CPython $PythonVersion win-arm64..."
Invoke-WebRequest -Uri $PythonUrl -OutFile $PythonZip
$PythonDir = Join-Path $Payload "python"
if (Test-Path $PythonDir) { Remove-Item -Recurse -Force $PythonDir }
Expand-Archive -Path $PythonZip -DestinationPath $PythonDir -Force

$Pth = Get-ChildItem $PythonDir -Filter "python*._pth" | Select-Object -First 1
if ($Pth) {
    $content = Get-Content $Pth.FullName
    $content = $content -replace "^#import site", "import site"
    Set-Content -Path $Pth.FullName -Value $content
}

Write-Host "Installing uv..."
$UvDir = Join-Path $Payload "uv"
New-Item -ItemType Directory -Force -Path $UvDir | Out-Null
irm https://astral.sh/uv/install.ps1 | iex
$Uv = Get-Command uv -ErrorAction SilentlyContinue
if (-not $Uv) {
    throw "uv did not install. Install uv and re-run prepare-payload.ps1."
}

$Venv = Join-Path $Payload "venv"
& uv python install 3.12 --preview
& uv venv $Venv --python 3.12
$Env:VIRTUAL_ENV = $Venv
Write-Host "Syncing OpenJarvis (server extra + desktop-native Rust extension)..."
Push-Location $Root
try {
    & uv sync --python $Venv\Scripts\python.exe --extra server --group desktop-native
    # Ensure the venv has the project editable / jarvis entrypoint.
    & uv pip install --python $Venv\Scripts\python.exe -e ".[server]"
} finally {
    Pop-Location
}

# Stage a minimal source tree for uv run fallbacks and config discovery.
$PayloadSrc = Join-Path $Payload "src"
New-Item -ItemType Directory -Force -Path $PayloadSrc | Out-Null
foreach ($item in @("src", "pyproject.toml", "configs", "README.md")) {
    $from = Join-Path $Root $item
    if (Test-Path $from) {
        Copy-Item -Recurse -Force $from (Join-Path $PayloadSrc (Split-Path $item -Leaf))
    }
}

$FoundryNotes = @"
Foundry Local $FoundryVersion (ARM64)
OpenJarvis Setup installs Foundry Local automatically (no terminal).
Manual fallback:
  https://github.com/microsoft/Foundry-Local/releases/tag/cli-preview-$FoundryVersion
  Add-AppxPackage .\foundry-$FoundryVersion-win-arm64-winml.msix
  (or foundry-$FoundryVersion-win-arm64.msix on 0.11+)
  foundry server start
"@
Set-Content -Path (Join-Path $Payload "FOUNDRY_LOCAL.txt") -Value $FoundryNotes

$InstallCmd = Join-Path $Payload "install-runtime.ps1"
@'
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Dest = Join-Path $env:LOCALAPPDATA "OpenJarvis"
New-Item -ItemType Directory -Force -Path $Dest | Out-Null
if (Test-Path (Join-Path $Root "venv")) {
    Copy-Item -Recurse -Force (Join-Path $Root "venv") (Join-Path $Dest "venv")
}
if (Test-Path (Join-Path $Root "src")) {
    Copy-Item -Recurse -Force (Join-Path $Root "src") (Join-Path $Dest "src")
}
Write-Host "Runtime staged under $Dest"
'@ | Set-Content -Path $InstallCmd

Write-Host "Payload staged at $Payload"
