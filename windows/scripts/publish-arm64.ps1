# Requires: Windows ARM64, .NET 9 SDK, Visual Studio 2022 WinUI workload, Rust aarch64-pc-windows-msvc, WiX 5, uv.
# Produces: dist/OpenJarvis-win-arm64/ (app), dist/OpenJarvis-<ver>-arm64.msi, dist/OpenJarvis-<ver>-arm64.exe (Burn)
[CmdletBinding()]
param(
    [string]$Configuration = "Release",
    [string]$Version = "1.0.0",
    [switch]$SkipPayload,
    [switch]$SkipInstaller
)

$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$WinUi = Join-Path $Root "windows\OpenJarvis.WinUI"
$PublishDir = Join-Path $WinUi "bin\publish\win-arm64"
$Dist = Join-Path $Root "dist\OpenJarvis-win-arm64"
$DistRoot = Join-Path $Root "dist"
$InstallerDir = Join-Path $Root "windows\installer"

Write-Host "Publishing WinUI ARM64 app..."
$msb = @(
    "${env:ProgramFiles}\Microsoft Visual Studio\18\Community\MSBuild\Current\Bin\MSBuild.exe",
    "${env:ProgramFiles}\Microsoft Visual Studio\2022\BuildTools\MSBuild\Current\Bin\MSBuild.exe",
    "${env:ProgramFiles}\Microsoft Visual Studio\2022\Community\MSBuild\Current\Bin\MSBuild.exe"
) | Where-Object { Test-Path $_ } | Select-Object -First 1

New-Item -ItemType Directory -Force -Path $PublishDir | Out-Null
if ($msb) {
    Write-Host "Using MSBuild: $msb"
    & $msb (Join-Path $WinUi "OpenJarvis.WinUI.csproj") `
        /t:Restore,Publish `
        /p:Configuration=$Configuration `
        /p:Platform=ARM64 `
        /p:RuntimeIdentifier=win-arm64 `
        /p:SelfContained=true `
        /p:WindowsAppSDKSelfContained=true `
        /p:PublishDir="$PublishDir\" `
        /v:m
    if ($LASTEXITCODE -ne 0) { throw "MSBuild publish failed with exit $LASTEXITCODE" }
} else {
    Write-Host "MSBuild not found; falling back to dotnet publish"
    dotnet publish $WinUi -c $Configuration -r win-arm64 --self-contained true `
        /p:Platform=ARM64 /p:WindowsAppSDKSelfContained=true `
        -o $PublishDir
    if ($LASTEXITCODE -ne 0) { throw "dotnet publish failed with exit $LASTEXITCODE" }
}

if (-not $SkipPayload) {
    Write-Host "Preparing backend payload..."
    & (Join-Path $PSScriptRoot "prepare-payload.ps1") -PublishDir $PublishDir
} else {
    Write-Host "Skipping prepare-payload (-SkipPayload)."
}

New-Item -ItemType Directory -Force -Path $DistRoot | Out-Null
New-Item -ItemType Directory -Force -Path $Dist | Out-Null
Copy-Item -Recurse -Force "$PublishDir\*" $Dist
Write-Host "App output: $Dist"

if ($SkipInstaller) {
    Write-Host "Skipping installer (-SkipInstaller)."
    return
}

$wix = Get-Command wix -ErrorAction SilentlyContinue
$hasDotnetWix = $false
try {
    dotnet build "$InstallerDir\OpenJarvis.Installer.wixproj" -c $Configuration -p:PublishDir="$PublishDir" -v q 2>$null | Out-Null
    $hasDotnetWix = $LASTEXITCODE -eq 0
} catch {
    $hasDotnetWix = $false
}

if (-not $wix -and -not (Get-Command dotnet -ErrorAction SilentlyContinue)) {
    Write-Warning "WiX / dotnet not available. Skipping MSI/Burn. Zip $Dist for sideload."
    return
}

Write-Host "Building MSI..."
Push-Location $InstallerDir
try {
    dotnet build OpenJarvis.Installer.wixproj -c $Configuration -p:PublishDir="$PublishDir"
    $msiCandidates = @(
        (Join-Path $InstallerDir "bin\$Configuration\*.msi"),
        (Join-Path $InstallerDir "bin\$Configuration\net6.0-windows\*.msi"),
        (Join-Path $InstallerDir "bin\$Configuration\arm64\*.msi")
    )
    $msi = Get-ChildItem $msiCandidates -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $msi) {
        $msi = Get-ChildItem (Join-Path $InstallerDir "bin") -Recurse -Filter "*.msi" -ErrorAction SilentlyContinue |
            Sort-Object LastWriteTime -Descending |
            Select-Object -First 1
    }
    if (-not $msi) {
        Write-Warning "MSI build did not produce an .msi under windows/installer/bin."
        return
    }

    $msiOut = Join-Path $DistRoot "OpenJarvis-$Version-arm64.msi"
    Copy-Item -Force $msi.FullName $msiOut
    Write-Host "MSI: $msiOut"

    Write-Host "Building Burn bundle..."
    dotnet build OpenJarvis.Bundle.wixproj -c $Configuration -p:MsiPath="$($msi.FullName)"
    $bundle = Get-ChildItem (Join-Path $InstallerDir "bin") -Recurse -Filter "*.exe" -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -match "OpenJarvis|Bundle" -or $_.DirectoryName -match "Bundle" } |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1
    if (-not $bundle) {
        $bundle = Get-ChildItem (Join-Path $InstallerDir "bin") -Recurse -Filter "OpenJarvis*.exe" -ErrorAction SilentlyContinue |
            Sort-Object LastWriteTime -Descending |
            Select-Object -First 1
    }
    if ($bundle) {
        $exeOut = Join-Path $DistRoot "OpenJarvis-$Version-arm64.exe"
        Copy-Item -Force $bundle.FullName $exeOut
        Write-Host "Burn bundle: $exeOut"
    } else {
        Write-Warning "Burn bundle .exe not found; MSI is still available at $msiOut"
    }
} finally {
    Pop-Location
}

Write-Host "Done. Artifacts under $DistRoot"
