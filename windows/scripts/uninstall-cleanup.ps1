# Stops OpenJarvis child processes. User conversations and Foundry models stay
# unless -RemoveData is passed.
[CmdletBinding()]
param(
    [switch]$RemoveData
)

Get-Process -Name OpenJarvis, jarvis, foundry -ErrorAction SilentlyContinue | Stop-Process -Force
if ($RemoveData) {
    $paths = @(
        (Join-Path $env:LOCALAPPDATA "OpenJarvis"),
        (Join-Path $env:USERPROFILE ".openjarvis")
    )
    foreach ($path in $paths) {
        if (Test-Path $path) {
            Remove-Item -Recurse -Force $path
        }
    }
}
