"""Focused, server-free tests for final Windows launcher PID ownership."""

from __future__ import annotations

import base64
import json
import os
import subprocess
from pathlib import Path

import pytest

REPOSITORY = Path(__file__).resolve().parents[2]
LAUNCHER = REPOSITORY / "scripts" / "windows" / "openjarvis-final.ps1"


def _run_ownership_case(case: dict[str, object]) -> dict[str, object]:
    harness = r"""
$ErrorActionPreference = 'Stop'
$tokens = $null
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile(
    $env:OPENJARVIS_LAUNCHER_UNDER_TEST,
    [ref]$tokens,
    [ref]$parseErrors
)
if ($parseErrors.Count -ne 0) { throw 'Launcher did not parse.' }
$definition = $ast.Find({
    param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -eq 'Get-LaunchedRuntimeProcess'
}, $true)
if ($null -eq $definition) { throw 'Ownership function is missing.' }
Invoke-Expression $definition.Extent.Text

$case = $env:OPENJARVIS_PID_TEST_CASE | ConvertFrom-Json
$script:Owner = [int]$case.owner
$script:Parents = @{}
foreach ($property in $case.parents.PSObject.Properties) {
    $script:Parents[[int]$property.Name] = [int]$property.Value
}

function Get-PortOwner { return $script:Owner }
function Get-CimInstance {
    param([string]$ClassName, [string]$Filter)
    if ($ClassName -ne 'Win32_Process' -or $Filter -notmatch '^ProcessId = (\d+)$') {
        throw 'Unexpected process inventory request.'
    }
    $processId = [int]$Matches[1]
    if (-not $script:Parents.ContainsKey($processId)) { return $null }
    return [pscustomobject]@{ ParentProcessId = $script:Parents[$processId] }
}
function Get-Process {
    param([int]$Id, [object]$ErrorAction)
    $process = [pscustomobject]@{
        Id = $Id
        Path = "C:\runtime\python.exe"
        HasExited = $false
    }
    $process | Add-Member -MemberType ScriptMethod -Name Refresh -Value { }
    return $process
}

$health = if ($case.health_kind -eq 'missing') {
    [pscustomobject]@{}
} else {
    [pscustomobject]@{ pid = $case.health_pid }
}
$result = $null
$failure = $null
try {
    $launched = Get-Process -Id 100
    $result = Get-LaunchedRuntimeProcess $launched $health
} catch {
    $failure = $_.Exception.Message
}
[pscustomobject]@{
    process_id = if ($null -ne $result) { $result.Id } else { $null }
    error = $failure
} | ConvertTo-Json -Compress
"""
    environment = os.environ.copy()
    environment["OPENJARVIS_LAUNCHER_UNDER_TEST"] = str(LAUNCHER)
    environment["OPENJARVIS_PID_TEST_CASE"] = json.dumps(case)
    encoded = base64.b64encode(harness.encode("utf-16-le")).decode("ascii")
    completed = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-EncodedCommand",
            encoded,
        ],
        cwd=REPOSITORY,
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr or completed.stdout
    return json.loads(completed.stdout.strip())


@pytest.mark.parametrize(
    ("case", "expected_pid", "expected_error"),
    [
        pytest.param(
            {"health_kind": "value", "health_pid": 100, "owner": 100, "parents": {}},
            100,
            None,
            id="launched-process-is-listener",
        ),
        pytest.param(
            {
                "health_kind": "value",
                "health_pid": 200,
                "owner": 200,
                "parents": {"200": 100},
            },
            200,
            None,
            id="direct-child-is-listener",
        ),
        pytest.param(
            {
                "health_kind": "value",
                "health_pid": 300,
                "owner": 300,
                "parents": {"300": 200, "200": 100},
            },
            300,
            None,
            id="indirect-child-is-listener",
        ),
        pytest.param(
            {
                "health_kind": "value",
                "health_pid": 200,
                "owner": 201,
                "parents": {"200": 100},
            },
            None,
            "Final health PID and listener ownership do not match.",
            id="listener-health-mismatch-fails-closed",
        ),
        pytest.param(
            {
                "health_kind": "value",
                "health_pid": 400,
                "owner": 400,
                "parents": {"400": 999},
            },
            None,
            (
                "Final health/listener process is not a descendant "
                "of the launched process."
            ),
            id="foreign-listener-fails-closed",
        ),
        pytest.param(
            {"health_kind": "missing", "health_pid": None, "owner": 100, "parents": {}},
            None,
            "Final health response did not provide a numeric process ID.",
            id="missing-health-pid-fails-closed",
        ),
        pytest.param(
            {
                "health_kind": "value",
                "health_pid": "not-a-pid",
                "owner": 100,
                "parents": {},
            },
            None,
            "Final health response did not provide a numeric process ID.",
            id="nonnumeric-health-pid-fails-closed",
        ),
    ],
)
def test_runtime_process_ownership_is_fail_closed(
    case: dict[str, object], expected_pid: int | None, expected_error: str | None
) -> None:
    result = _run_ownership_case(case)
    assert result["process_id"] == expected_pid, result
    assert result["error"] == expected_error, result


def _function_source(name: str) -> str:
    content = LAUNCHER.read_text(encoding="utf-8").replace("\r\n", "\n")
    start = content.index(f"function {name}")
    end = content.find("\nfunction ", start + 1)
    if end < 0:
        end = content.index("\nswitch (", start + 1)
    return content[start:end]


def test_start_persists_the_actual_runtime_process_identity() -> None:
    start = _function_source("Start-FinalRuntime")
    assert "$managedServer = Get-LaunchedRuntimeProcess $server $health" in start
    assert "$managedServer.StartTime.ToUniversalTime()" in start
    assert "$serverExecutable = $managedServer.Path" in start
    assert "server_pid = $managedServer.Id" in start
    assert "executable = $serverExecutable" in start
    assert "server_pid = $server.Id" not in start


def test_status_stop_restart_and_cleanup_use_the_canonical_runtime_pid() -> None:
    status = _function_source("Show-Status")
    start = _function_source("Start-FinalRuntime")
    stop = _function_source("Stop-FinalRuntime")
    launcher = LAUNCHER.read_text(encoding="utf-8")

    for function in (status, stop):
        assert "([int]$state.server_pid)" in function
        assert "([string]$state.started_at_utc)" in function
        assert "([string]$state.executable)" in function
    assert "Stop-Process -Id $managedServer.Id" in start
    assert "Get-Process -Id ([int]$state.server_pid)" in stop
    assert "$verifiedServer = Get-OwnedServer" in stop
    assert "Stop-Process -Id $verifiedServer.Id -Force" in stop
    assert "$verifiedUi = Get-OwnedUi" in stop
    assert "Stop-Process -Id $verifiedUi.Id -Force" in stop
    assert "Desktop ownership changed during shutdown recovery" in stop
    assert "A foreign process acquired the final runtime port" in stop
    assert "'Restart' { Stop-FinalRuntime; Start-FinalRuntime }" in launcher
    assert "Stop-Process -Name" not in launcher
    assert "taskkill" not in launcher.lower()
