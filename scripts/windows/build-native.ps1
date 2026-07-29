[CmdletBinding()]
param(
    [string]$UvPath = "uv",
    [string]$RustBinPath = "",
    [string]$CargoHome = "",
    [string]$RustupHome = ""
)

$ErrorActionPreference = "Stop"
$repositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$manifestPath = Join-Path $repositoryRoot "rust\crates\openjarvis-python\Cargo.toml"

$vswhereCandidates = @()
if (${env:ProgramFiles(x86)}) {
    $vswhereCandidates += Join-Path ${env:ProgramFiles(x86)} `
        "Microsoft Visual Studio\Installer\vswhere.exe"
}
if ($env:ProgramFiles) {
    $vswhereCandidates += Join-Path $env:ProgramFiles `
        "Microsoft Visual Studio\Installer\vswhere.exe"
}
$vswhereCommand = Get-Command "vswhere.exe" -ErrorAction SilentlyContinue
if ($vswhereCommand) {
    $vswhereCandidates = @($vswhereCommand.Source) + $vswhereCandidates
}
$vswherePath = $vswhereCandidates |
    Where-Object { $_ -and (Test-Path -LiteralPath $_ -PathType Leaf) } |
    Select-Object -First 1
if (-not $vswherePath) {
    throw "vswhere.exe was not found. Install Visual Studio Build Tools 2022."
}

$installationPath = & $vswherePath -latest -products * `
    -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 `
    -property installationPath
if ($LASTEXITCODE -ne 0 -or -not $installationPath) {
    throw "Visual Studio Build Tools with the x64/x86 C++ tools were not found."
}
$installationPath = ($installationPath | Select-Object -First 1).Trim()
$vsDevCmd = Join-Path $installationPath "Common7\Tools\VsDevCmd.bat"
if (-not (Test-Path -LiteralPath $vsDevCmd -PathType Leaf)) {
    throw "VsDevCmd.bat was not found below: $installationPath"
}

# Import the developer environment into this PowerShell process only.
$developerCommand = "`"$vsDevCmd`" -no_logo -arch=x64 -host_arch=x64 >nul && set"
$developerEnvironment = & $env:ComSpec /d /s /c $developerCommand
if ($LASTEXITCODE -ne 0) {
    throw "VsDevCmd.bat failed to initialize the x64 developer environment."
}
foreach ($line in $developerEnvironment) {
    if (-not $line -or $line.StartsWith("=")) {
        continue
    }
    $separator = $line.IndexOf("=")
    if ($separator -le 0) {
        continue
    }
    $name = $line.Substring(0, $separator)
    $value = $line.Substring($separator + 1)
    Set-Item -LiteralPath "Env:$name" -Value $value
}

$compiler = Get-Command "cl.exe" -ErrorAction SilentlyContinue
$linker = Get-Command "link.exe" -ErrorAction SilentlyContinue
if (-not $compiler) {
    throw "cl.exe is unavailable after loading VsDevCmd.bat."
}
if (-not $linker) {
    throw "link.exe is unavailable after loading VsDevCmd.bat."
}

$uvCommand = Get-Command $UvPath -ErrorAction SilentlyContinue
if (-not $uvCommand) {
    throw "uv was not found. Pass its absolute path with -UvPath."
}
$resolvedUvPath = $uvCommand.Source
if (-not $resolvedUvPath) {
    $resolvedUvPath = $uvCommand.Path
}
if (-not $resolvedUvPath) {
    throw "The uv command could not be resolved to an executable."
}
$resolvedUvDirectory = Split-Path -Parent $resolvedUvPath
$env:Path = "$resolvedUvDirectory;$env:Path"
if (($CargoHome -and -not $RustupHome) -or ($RustupHome -and -not $CargoHome)) {
    throw "-CargoHome and -RustupHome must be provided together."
}
if ($CargoHome -and $RustupHome) {
    $resolvedCargoHome = (Resolve-Path -LiteralPath $CargoHome).Path
    $resolvedRustupHome = (Resolve-Path -LiteralPath $RustupHome).Path
    $cargoBin = Join-Path $resolvedCargoHome "bin"
    if (-not (Test-Path -LiteralPath $cargoBin -PathType Container)) {
        throw "The Cargo bin directory does not exist: $cargoBin"
    }
    $env:CARGO_HOME = $resolvedCargoHome
    $env:RUSTUP_HOME = $resolvedRustupHome
    $env:Path = "$cargoBin;$env:Path"
}
if ($RustBinPath) {
    $resolvedRustBinPath = (Resolve-Path -LiteralPath $RustBinPath).Path
    if (-not (Test-Path -LiteralPath (
        Join-Path $resolvedRustBinPath "rustc.exe"
    ) -PathType Leaf)) {
        throw "rustc.exe was not found in -RustBinPath: $resolvedRustBinPath"
    }
    if (-not (Test-Path -LiteralPath (
        Join-Path $resolvedRustBinPath "cargo.exe"
    ) -PathType Leaf)) {
        throw "cargo.exe was not found in -RustBinPath: $resolvedRustBinPath"
    }
    $env:Path = "$resolvedRustBinPath;$env:Path"
}
$rustCompiler = Get-Command "rustc.exe" -ErrorAction SilentlyContinue
$cargo = Get-Command "cargo.exe" -ErrorAction SilentlyContinue
if (-not $rustCompiler -or -not $cargo) {
    throw (
        "rustc.exe and cargo.exe are required. Load Rust process-locally " +
        "or pass the toolchain bin directory with -RustBinPath."
    )
}
if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) {
    throw "The openjarvis_rust Cargo manifest was not found: $manifestPath"
}

# These compatibility switches intentionally live only in this process and
# child build processes. The script never writes user or machine environment.
$env:AWS_LC_SYS_PREBUILT_NASM = "1"
$env:AWS_LC_SYS_NO_JITTER_ENTROPY = "1"

Push-Location $repositoryRoot
try {
    & $resolvedUvPath run rustc --version
    if ($LASTEXITCODE -ne 0) {
        throw "uv could not launch the process-local Rust compiler."
    }
    & $resolvedUvPath run cargo --version
    if ($LASTEXITCODE -ne 0) {
        throw "uv could not launch the process-local Cargo executable."
    }
    & $resolvedUvPath run maturin develop --uv --manifest-path $manifestPath
    if ($LASTEXITCODE -ne 0) {
        throw "The openjarvis_rust maturin build failed with exit code $LASTEXITCODE."
    }
    & $resolvedUvPath run python -c `
        "import openjarvis_rust; print('openjarvis_rust import: OK')"
    if ($LASTEXITCODE -ne 0) {
        throw "The native module built but could not be imported."
    }
}
finally {
    Pop-Location
}

Write-Host "Native Windows build and import smoke test completed successfully."
