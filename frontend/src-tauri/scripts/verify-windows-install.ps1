<#
.SYNOPSIS
  Fresh-install, update and uninstall a Windows desktop bundle (NSIS or MSI)
  and verify the bundled Ollama runtime at each step.

.DESCRIPTION
  The update step mimics tauri-plugin-updater's installer arguments while the
  previously installed ollama.exe and a lib\ollama runner are running, as an
  installed app would leave them. The update installer must stop them, finish
  without requiring a reboot, and leave every runtime file identical to the
  expected stage. Build V2 from a stage whose Ollama binaries differ from V1
  so that the replacement of locked files is observable.

.EXAMPLE
  ./verify-windows-install.ps1 -Format nsis -V1 v1-setup.exe -V2 v2-setup.exe `
    -Stage binaries/ollama-runtime-x86_64-pc-windows-msvc `
    -Sidecar binaries/ollama-x86_64-pc-windows-msvc.exe -V2Version 1.0.2 `
    -InstallDir "$env:RUNNER_TEMP\oj-nsis"
#>
param(
  [Parameter(Mandatory)] [ValidateSet('nsis', 'msi')] [string] $Format,
  [Parameter(Mandatory)] [string] $V1,
  [Parameter(Mandatory)] [string] $V2,
  # Expected V2 runtime directory and sidecar, as staged by download-ollama.sh.
  [Parameter(Mandatory)] [string] $Stage,
  [Parameter(Mandatory)] [string] $Sidecar,
  [Parameter(Mandatory)] [string] $V2Version,
  [Parameter(Mandatory)] [string] $InstallDir,
  [string] $LogDir = (Join-Path ([IO.Path]::GetTempPath()) "openjarvis-install-$Format"),
  [int] $TimeoutSeconds = 900
)

$ErrorActionPreference = 'Stop'
$V1 = (Resolve-Path $V1).Path
$V2 = (Resolve-Path $V2).Path
$Stage = (Resolve-Path $Stage).Path
$Sidecar = (Resolve-Path $Sidecar).Path
$InstallDir = [IO.Path]::GetFullPath($InstallDir).TrimEnd('\')
$logDir = $LogDir
New-Item -ItemType Directory -Force $logDir | Out-Null

function Step($message) { Write-Host "==> [$Format] $message" }

function Invoke-Installer($file, [string[]] $arguments, $name) {
  Step "$name`: $file $($arguments -join ' ')"
  $process = Start-Process -FilePath $file -ArgumentList $arguments -PassThru
  if (-not $process.WaitForExit($TimeoutSeconds * 1000)) {
    $process | Stop-Process -Force
    throw "$name timed out after $TimeoutSeconds s (likely blocked on a file in use)"
  }
  if ($process.ExitCode -ne 0) {
    throw "$name exited with $($process.ExitCode) (3010 means files were in use and a reboot is required)"
  }
}

function Install-Fresh($installer) {
  if ($Format -eq 'nsis') {
    Invoke-Installer $installer @('/S', "/D=$InstallDir") 'Fresh install'
  } else {
    Invoke-Installer 'msiexec.exe' @('/i', "`"$installer`"", '/qn', '/norestart',
      "INSTALLDIR=`"$InstallDir\`"", '/l*v', "`"$logDir\install.log`"") 'Fresh install'
  }
}

function Update-WithUpdaterArgs($installer) {
  # Same arguments tauri-plugin-updater uses in its default passive mode, except
  # MSI's /promptrestart, which would block CI; /norestart surfaces 3010 instead.
  if ($Format -eq 'nsis') {
    Invoke-Installer $installer @('/P', '/UPDATE') 'Update'
  } else {
    Invoke-Installer 'msiexec.exe' @('/i', "`"$installer`"", '/passive', '/norestart',
      '/l*v', "`"$logDir\update.log`"") 'Update'
  }
}

function Uninstall($installer) {
  if ($Format -eq 'nsis') {
    $uninstaller = Join-Path $InstallDir 'uninstall.exe'
    Invoke-Installer $uninstaller @('/S') 'Uninstall'
  } else {
    Invoke-Installer 'msiexec.exe' @('/x', "`"$installer`"", '/qn', '/norestart') 'Uninstall'
  }
  # The NSIS uninstaller relaunches itself from %TEMP%, so wait for its effect.
  $deadline = (Get-Date).AddSeconds(120)
  while ((Test-Path (Join-Path $InstallDir 'ollama.exe')) -and (Get-Date) -lt $deadline) {
    Start-Sleep -Seconds 2
  }
  if (Test-Path (Join-Path $InstallDir 'ollama.exe')) { throw 'Uninstall left ollama.exe behind' }
  if (Test-Path (Join-Path $InstallDir 'lib\ollama')) { throw 'Uninstall left lib\ollama behind' }
}

function Get-StageFiles {
  Get-ChildItem -LiteralPath $Stage -Recurse -File | ForEach-Object {
    $_.FullName.Substring($Stage.Length).TrimStart('\')
  }
}

function Assert-RuntimePresent {
  $missing = @(Get-StageFiles | Where-Object { -not (Test-Path -LiteralPath (Join-Path $InstallDir $_)) })
  foreach ($required in @('openjarvis-desktop.exe', 'ollama.exe', 'lib\ollama\llama-server.exe')) {
    if (-not (Test-Path (Join-Path $InstallDir $required))) { $missing += $required }
  }
  if ($missing) { throw "Installed runtime is missing: $($missing -join ', ')" }
  & (Join-Path $InstallDir 'ollama.exe') --version 2>&1 | Out-Host
  if ($LASTEXITCODE -ne 0) { throw 'Installed ollama.exe --version failed' }
  & (Join-Path $InstallDir 'lib\ollama\llama-server.exe') --version 2>&1 | Out-Host
  if ($LASTEXITCODE -ne 0) { throw 'Installed llama-server.exe --version failed' }
  Step "runtime present ($(@(Get-StageFiles).Count) runtime files + sidecar)"
}

function Assert-RuntimeMatchesStage {
  $mismatched = @(Get-StageFiles | Where-Object {
    $installed = Join-Path $InstallDir $_
    -not (Test-Path -LiteralPath $installed) -or
      (Get-FileHash -LiteralPath $installed).Hash -ne (Get-FileHash -LiteralPath (Join-Path $Stage $_)).Hash
  })
  if ((Get-FileHash (Join-Path $InstallDir 'ollama.exe')).Hash -ne (Get-FileHash $Sidecar).Hash) {
    $mismatched += 'ollama.exe'
  }
  if ($mismatched) { throw "Update did not replace: $($mismatched -join ', ')" }
  $version = (Get-Item (Join-Path $InstallDir 'openjarvis-desktop.exe')).VersionInfo.ProductVersion
  if (-not $version.StartsWith($V2Version)) { throw "Installed app version is $version, expected $V2Version" }
  Step "runtime and app match the update ($version)"
}

function Start-AppOwnedOllama {
  # Stand-ins for what the app leaves running: the installed `ollama serve`
  # (a packaged file the update must replace while it is locked) and a process
  # executing from lib\ollama, where Ollama's runners live. A model-less
  # llama-server exits at once, so a copy of PING.EXE plays the runner.
  $env:OLLAMA_HOST = '127.0.0.1:11535'
  $env:OLLAMA_MODELS = Join-Path $logDir 'models'
  $serve = Start-Process (Join-Path $InstallDir 'ollama.exe') -ArgumentList 'serve' -PassThru -WindowStyle Hidden `
    -RedirectStandardError (Join-Path $logDir 'ollama.err') -RedirectStandardOutput (Join-Path $logDir 'ollama.out')
  Copy-Item "$env:SystemRoot\System32\PING.EXE" $script:RunnerStandIn
  $runner = Start-Process $script:RunnerStandIn -ArgumentList '-n', '900', '127.0.0.1' -PassThru -WindowStyle Hidden
  Start-Sleep -Seconds 5
  foreach ($p in @($serve, $runner)) {
    if ($p.HasExited) { throw "Lock holder $($p.Id) exited early with $($p.ExitCode)" }
  }
  Step "app-owned ollama.exe ($($serve.Id)) and lib\ollama runner ($($runner.Id)) running"
  return @($serve, $runner)
}

$script:RunnerStandIn = Join-Path $InstallDir 'lib\ollama\openjarvis-runner-standin.exe'

if (Test-Path (Join-Path $InstallDir 'ollama.exe')) { throw "$InstallDir already has an installation" }
# Both installers resume a previous install location from this key, and the
# MSI's AppSearch overrides INSTALLDIR with it, so require a clean machine.
if (Test-Path 'HKCU:\Software\openjarvis\OpenJarvis') {
  throw 'HKCU\Software\openjarvis\OpenJarvis exists; run on a machine without OpenJarvis install state'
}

Install-Fresh $V1
Assert-RuntimePresent

$holders = Start-AppOwnedOllama
try {
  Update-WithUpdaterArgs $V2
  $survivors = @($holders | Where-Object { -not $_.HasExited })
  if ($survivors) { throw "Update left app-owned processes running: $($survivors.Id -join ', ')" }
  Step 'update stopped the app-owned Ollama processes'
  Assert-RuntimeMatchesStage
  Assert-RuntimePresent
} finally {
  $holders | Where-Object { -not $_.HasExited } | Stop-Process -Force -ErrorAction SilentlyContinue
  Remove-Item -LiteralPath $script:RunnerStandIn -Force -ErrorAction SilentlyContinue
}

Uninstall $V2
Step 'fresh install, update and uninstall verified'
