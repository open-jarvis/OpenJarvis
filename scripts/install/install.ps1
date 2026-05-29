# OpenJarvis — Windows (PowerShell) install entry point.
#
# Native Windows CLI install is NOT supported. OpenJarvis runs on Windows via
# WSL2 or the desktop app. This script intentionally does NOT install the CLI;
# it prints the two supported paths and exits non-zero — mirroring the
# MINGW/MSYS/CYGWIN refusal in install.sh — so PowerShell/cmd users who tried
#   curl -fsSL https://open-jarvis.github.io/OpenJarvis/install.sh | bash
# (and hit "bash: not recognized") get the right guidance instead (#334).
#
# Published at https://open-jarvis.github.io/OpenJarvis/install.ps1 so the
# PowerShell one-liner works:
#   irm https://open-jarvis.github.io/OpenJarvis/install.ps1 | iex
#
# Kept to plain Write-Host / exit so it runs under Constrained Language Mode.

Write-Host ''
Write-Host 'OpenJarvis on Windows' -ForegroundColor Cyan
Write-Host '====================='
Write-Host ''
Write-Host 'The native Windows (PowerShell/cmd) CLI is not supported.'
Write-Host 'OpenJarvis runs on Windows two ways:'
Write-Host ''
Write-Host '  1. WSL2 (recommended for the CLI / Python SDK).'
Write-Host '     One-time setup in an ADMIN PowerShell:'
Write-Host ''
Write-Host '         wsl --install -d Ubuntu-24.04'
Write-Host ''
Write-Host '     Then open the Ubuntu shell that gets installed and run:'
Write-Host ''
Write-Host '         curl -fsSL https://open-jarvis.github.io/OpenJarvis/install.sh | bash'
Write-Host ''
Write-Host '  2. Desktop app (no terminal needed). Download the .exe from Releases:'
Write-Host '         https://github.com/open-jarvis/OpenJarvis/releases'
Write-Host ''
Write-Host 'Full WSL2 walkthrough:'
Write-Host '         https://open-jarvis.github.io/OpenJarvis/getting-started/wsl2/'
Write-Host ''

# If WSL is already installed, point at option 1 explicitly.
if (Get-Command wsl -ErrorAction SilentlyContinue) {
    Write-Host 'Detected WSL on this machine - option 1 is your fastest path.' -ForegroundColor Green
    Write-Host ''
}

exit 1
