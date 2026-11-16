"""Run Windows prerequisite helpers in PowerShell without installing anything."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

_INSTALLER = Path(__file__).parents[2] / "deploy" / "windows" / "install.ps1"
_POWERSHELL = (
    os.environ.get("OPENJARVIS_TEST_PWSH")
    # Prefer Windows PowerShell 5.1 where available: it is the installer's
    # minimum supported shell. The portable pwsh runtime also runs these tests.
    or shutil.which("powershell")
    or shutil.which("pwsh")
)
pytestmark = pytest.mark.skipif(not _POWERSHELL, reason="PowerShell is not installed")

_HARNESS = r"""
param([string]$Installer, [string]$Case)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$tokens = $null
$errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile(
    $Installer, [ref]$tokens, [ref]$errors)
if ($errors.Count) { throw ($errors | Out-String) }
$definitions = $ast.FindAll({
    param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -in @('Get-PythonCommand', 'Test-MsvcLinker')
}, $true)
foreach ($definition in $definitions) { Invoke-Expression $definition.Extent.Text }

$global:Probes = @()
$global:VswhereArguments = @()
$global:Installed = $false
function Write-Warn2 { param($Message) }
function Write-Info { param($Message) }
function Write-Fail { param($Message) throw $Message }
function Install-WithWinget {
    param($WingetId, $CommandName)
    $global:Installed = $true
    'Invoke-BadPython'
}
function Invoke-GoodPython {
    $global:Probes += 'good'
    $global:LASTEXITCODE = 0
    'Python 3.12.10'
}
function Invoke-BadPython {
    $global:Probes += 'bad'
    if ($Case -in @('python-too-old', 'python-too-new')) {
        $global:LASTEXITCODE = 0
        if ($Case -eq 'python-too-old') { 'Python 2.7.18' } else { 'Python 3.14.0' }
        return
    }
    $global:LASTEXITCODE = 9009
    'Python was not found'
}
function Invoke-TestVswhere {
    $global:VswhereArguments = @($args)
    $global:LASTEXITCODE = 0
    'C:\VS\VC\Tools\MSVC\14.0\bin\Hostx64\x64\link.exe'
}
function Get-Command {
    param([string]$Name, [switch]$All, $CommandType, $ErrorAction)
    if ($Name -eq 'python') {
        if ($Case -eq 'active-store-alias') {
            return [pscustomobject]@{Source='Invoke-GoodPython'}
        }
        if ($Case -in @('shadowed-python', 'python-too-old', 'python-too-new') -or
            ($Case -eq 'winget-shadowed-python' -and $global:Installed)) {
            $bad = [pscustomobject]@{Source='Invoke-BadPython'}
            $good = [pscustomobject]@{Source='Invoke-GoodPython'}
            if ($All) { return @($bad, $good) }
            return $bad
        }
        if ($Case -eq 'failed-python-alias') {
            return [pscustomobject]@{Source='Invoke-BadPython'}
        }
    }
    if ($Name -eq 'python3' -and $Case -eq 'failed-python-alias') {
        return [pscustomobject]@{Source='Invoke-GoodPython'}
    }
    if ($Name -eq 'link.exe' -and $Case -in @('gnu-linker', 'msvc-on-path')) {
        return [pscustomobject]@{Source='C:\tools\link.exe'}
    }
}
function Get-Item {
    param($LiteralPath, $ErrorAction)
    # Installed Store Python aliases can still have a zero-byte file size.
    $company = if ($Case -eq 'msvc-on-path') {
        'Microsoft Corporation'
    } else { 'Free Software Foundation' }
    [pscustomobject]@{
        Length=0
        VersionInfo=[pscustomobject]@{CompanyName=$company; OriginalFilename='LINK.EXE'}
    }
}
function Join-Path { param($Path, $ChildPath) 'Invoke-TestVswhere' }
function Test-Path {
    param($LiteralPath, $PathType)
    if ($LiteralPath -eq 'Invoke-TestVswhere') {
        return $Case -in @('msvc-vswhere', 'vswhere-missing-linker')
    }
    return $Case -eq 'msvc-vswhere' -and $PathType -eq 'Leaf'
}
${env:ProgramFiles(x86)} = 'C:\Program Files (x86)'
$pythonCases = @(
    'active-store-alias', 'shadowed-python', 'failed-python-alias', 'no-python',
    'python-too-old', 'python-too-new')
if ($Case -eq 'winget-shadowed-python') {
    $pythonExe = Get-PythonCommand
    $bootstrap = $ast.EndBlock.Statements | Where-Object {
        $_ -is [System.Management.Automation.Language.IfStatementAst] -and
        $_.Extent.Text.Contains("Install-WithWinget -WingetId 'Python.Python.3.13'")
    } | Select-Object -First 1
    Invoke-Expression $bootstrap.Extent.Text
    @{selected=$pythonExe; probes=$global:Probes} | ConvertTo-Json -Compress
} elseif ($Case -in $pythonCases) {
    $selected = Get-PythonCommand
    @{selected=$selected; probes=$global:Probes} | ConvertTo-Json -Compress
} else {
    $present = Test-MsvcLinker
    @{present=$present; arguments=$global:VswhereArguments} | ConvertTo-Json -Compress
}
"""


def _run_case(tmp_path: Path, case: str) -> dict:
    script = tmp_path / "prerequisites.ps1"
    script.write_text(_HARNESS)
    result = subprocess.run(
        [
            _POWERSHELL,
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-File",
            str(script),
            "-Installer",
            str(_INSTALLER),
            "-Case",
            case,
        ],
        text=True,
        capture_output=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return json.loads(result.stdout)


def test_installed_store_alias_is_not_rejected_for_zero_file_size(tmp_path):
    result = _run_case(tmp_path, "active-store-alias")
    assert result["selected"] == "Invoke-GoodPython"
    assert result["probes"] == ["good"]


def test_probe_continues_past_a_shadowing_failed_python(tmp_path):
    result = _run_case(tmp_path, "shadowed-python")
    assert result["selected"] == "Invoke-GoodPython"
    assert result["probes"] == ["bad", "good"]


@pytest.mark.parametrize("case", ["python-too-old", "python-too-new"])
def test_supported_python_is_selected_after_an_unsupported_version(tmp_path, case):
    result = _run_case(tmp_path, case)
    assert result["selected"] == "Invoke-GoodPython"
    assert result["probes"] == ["bad", "good"]


def test_probe_falls_back_to_python3_when_python_is_a_store_placeholder(tmp_path):
    result = _run_case(tmp_path, "failed-python-alias")
    assert result["selected"] == "Invoke-GoodPython"
    assert result["probes"] == ["bad", "good"]


def test_no_working_python_returns_none(tmp_path):
    assert _run_case(tmp_path, "no-python")["selected"] is None


def test_python_is_reprobed_after_winget_refreshes_path(tmp_path):
    result = _run_case(tmp_path, "winget-shadowed-python")
    assert result["selected"] == "Invoke-GoodPython"
    assert result["probes"] == ["bad", "good"]


def test_gnu_link_executable_is_not_accepted_as_msvc(tmp_path):
    assert _run_case(tmp_path, "gnu-linker")["present"] is False


def test_microsoft_linker_on_path_is_accepted(tmp_path):
    assert _run_case(tmp_path, "msvc-on-path")["present"] is True


def test_vswhere_must_find_an_actual_linker_file(tmp_path):
    result = _run_case(tmp_path, "msvc-vswhere")
    assert result["present"] is True
    assert "-find" in result["arguments"]
    assert "Microsoft.VisualStudio.Component.VC.Tools.x86.x64" in result["arguments"]
    assert _run_case(tmp_path, "vswhere-missing-linker")["present"] is False
