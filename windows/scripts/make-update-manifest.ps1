# Generates the JSON manifest UpdateChecker.cs polls (UpdateManifestUrl in
# appsettings.json -> winui-arm64-latest.json on the GitHub release).
#
# UpdateChecker expects: { "Version": "...", "Url": "...", "Notes": "..." }
# (OpenJarvis.WinUI\Services\UpdateChecker.cs, case-insensitive property match).
#
# This only writes the manifest file; it does not create or publish a GitHub
# release. Attach the output alongside the MSI/Burn bundle when cutting one:
#   gh release create v1.0.0 dist/OpenJarvis-1.0.0-arm64.exe dist/OpenJarvis-1.0.0-arm64.msi dist/winui-arm64-latest.json
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$Version,
    [string]$Notes = "",
    [string]$RepoSlug = "open-jarvis/OpenJarvis",
    [string]$OutFile = ""
)

$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..\..")
if (-not $OutFile) {
    $OutFile = Join-Path $Root "dist\winui-arm64-latest.json"
}

$tag = "v$Version"
$manifest = [ordered]@{
    Version = $Version
    Url     = "https://github.com/$RepoSlug/releases/download/$tag/OpenJarvis-$Version-arm64.exe"
    Notes   = $Notes
}

New-Item -ItemType Directory -Force -Path (Split-Path $OutFile) | Out-Null
$manifest | ConvertTo-Json | Set-Content -Path $OutFile -Encoding utf8
Write-Host "Wrote $OutFile"
Write-Host "Attach it to the '$tag' GitHub release as 'winui-arm64-latest.json' so UpdateManifestUrl resolves."
