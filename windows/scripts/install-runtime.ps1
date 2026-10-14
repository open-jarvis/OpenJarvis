# First-run / bundle helper: stages the backend under %LOCALAPPDATA%\OpenJarvis
# and installs Foundry Local when the MSIX is present next to this script.
[CmdletBinding()]
param(
    [string]$FoundryMsix = ""
)

$ErrorActionPreference = "Stop"
Write-Progress -Activity "OpenJarvis setup" -Status "Creating data directories" -PercentComplete 10
$Dest = Join-Path $env:LOCALAPPDATA "OpenJarvis"
New-Item -ItemType Directory -Force -Path $Dest, (Join-Path $Dest "logs") | Out-Null

$Payload = Join-Path $PSScriptRoot "..\OpenJarvis.WinUI\bin\publish\win-arm64\payload"
if (-not (Test-Path $Payload)) {
    $Payload = Join-Path (Split-Path -Parent $MyInvocation.MyCommand.Path) "payload"
}

if (Test-Path (Join-Path $Payload "venv")) {
    Write-Progress -Activity "OpenJarvis setup" -Status "Copying Python environment" -PercentComplete 40
    Copy-Item -Recurse -Force (Join-Path $Payload "venv") (Join-Path $Dest "venv")
}

if ($FoundryMsix -and (Test-Path $FoundryMsix)) {
    Write-Progress -Activity "OpenJarvis setup" -Status "Installing Foundry Local (Windows ML)" -PercentComplete 70
    Add-AppxPackage -Path $FoundryMsix
} elseif (Get-Command foundry -ErrorAction SilentlyContinue) {
    Write-Host "Foundry Local already on PATH."
} else {
    Write-Warning "Foundry Local MSIX was not provided. Install foundry-*-win-arm64-winml.msix from the Foundry Local releases page."
}

Write-Progress -Activity "OpenJarvis setup" -Status "Done" -PercentComplete 100
Write-Host "OpenJarvis runtime is ready under $Dest"
