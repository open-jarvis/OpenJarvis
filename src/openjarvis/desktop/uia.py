"""Bounded bridge to the Windows-provided UI Automation framework.

The bridge launches only a fixed, code-owned PowerShell program. Request data
is JSON on stdin, never executable shell text or command-line data. This keeps
modern WPF/WinUI/Chromium accessibility trees available without introducing a
second automation policy path or an additional Python package.
"""

from __future__ import annotations

import base64
import json
import os
import subprocess
import threading
from typing import Any


class UIAutomationError(RuntimeError):
    pass


_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
[Console]::InputEncoding = [System.Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
$request = [Console]::In.ReadToEnd() | ConvertFrom-Json
$root = [System.Windows.Automation.AutomationElement]::FromHandle(
  [IntPtr][Int64]$request.hwnd
)
if ($null -eq $root) { throw 'window unavailable' }

function Runtime-Key($element) {
  return [String]::Join('.', $element.GetRuntimeId())
}

function Find-Requested($root, $runtimeId) {
  $all = $root.FindAll(
    [System.Windows.Automation.TreeScope]::Descendants,
    [System.Windows.Automation.Condition]::TrueCondition
  )
  foreach ($element in $all) {
    try {
      if ((Runtime-Key $element) -eq $runtimeId) { return $element }
    } catch { }
  }
  throw 'semantic element unavailable'
}

if ($request.operation -eq 'inspect') {
  $all = $root.FindAll(
    [System.Windows.Automation.TreeScope]::Descendants,
    [System.Windows.Automation.Condition]::TrueCondition
  )
  $items = [System.Collections.Generic.List[Object]]::new()
  $limit = [Math]::Min($all.Count, 300)
  for ($index = 0; $index -lt $limit; $index++) {
    try {
      $element = $all.Item($index)
      $current = $element.Current
      $rect = $current.BoundingRectangle
      $role = $current.ControlType.ProgrammaticName.Replace('ControlType.', '').ToLowerInvariant()
      $value = ''
      $pattern = $null
      if (-not $current.IsPassword -and $element.TryGetCurrentPattern(
        [System.Windows.Automation.ValuePattern]::Pattern,
        [ref]$pattern
      )) {
        $value = ([System.Windows.Automation.ValuePattern]$pattern).Current.Value
      }
      $items.Add([PSCustomObject]@{
        runtime_id = Runtime-Key $element
        native_handle = [Int64]$current.NativeWindowHandle
        automation_identifier = [String]$current.AutomationId
        role = $role
        name = [String]$current.Name
        value = [String]$value
        is_password = [bool]$current.IsPassword
        bounds = @{
          left = [int][Math]::Round($rect.Left)
          top = [int][Math]::Round($rect.Top)
          right = [int][Math]::Round($rect.Right)
          bottom = [int][Math]::Round($rect.Bottom)
        }
      })
    } catch { }
  }
  @{ success = $true; elements = $items } | ConvertTo-Json -Compress -Depth 6
  exit 0
}

$target = Find-Requested $root ([String]$request.runtime_id)
if ($target.Current.IsPassword) { throw 'protected field' }
if ($request.operation -eq 'set_value') {
  $pattern = $null
  if (-not $target.TryGetCurrentPattern(
    [System.Windows.Automation.ValuePattern]::Pattern,
    [ref]$pattern
  )) { throw 'value pattern unavailable' }
  $typed = [System.Windows.Automation.ValuePattern]$pattern
  $typed.SetValue([String]$request.value)
  $observed = $typed.Current.Value
  @{ success = ($observed -eq [String]$request.value); value = [String]$observed } |
    ConvertTo-Json -Compress -Depth 4
  exit 0
}
if ($request.operation -eq 'invoke') {
  $pattern = $null
  if ($target.TryGetCurrentPattern(
    [System.Windows.Automation.InvokePattern]::Pattern,
    [ref]$pattern
  )) {
    ([System.Windows.Automation.InvokePattern]$pattern).Invoke()
  } elseif ($target.TryGetCurrentPattern(
    [System.Windows.Automation.SelectionItemPattern]::Pattern,
    [ref]$pattern
  )) {
    ([System.Windows.Automation.SelectionItemPattern]$pattern).Select()
  } elseif ($target.TryGetCurrentPattern(
    [System.Windows.Automation.TogglePattern]::Pattern,
    [ref]$pattern
  )) {
    ([System.Windows.Automation.TogglePattern]$pattern).Toggle()
  } elseif ($target.TryGetCurrentPattern(
    [System.Windows.Automation.LegacyIAccessiblePattern]::Pattern,
    [ref]$pattern
  )) {
    ([System.Windows.Automation.LegacyIAccessiblePattern]$pattern).DoDefaultAction()
  } else { throw 'action pattern unavailable' }
  @{ success = $true } | ConvertTo-Json -Compress -Depth 4
  exit 0
}
throw 'unsupported operation'
"""


class WindowsUIAutomationBridge:
    """Run bounded semantic inspection and actions in an interruptible child."""

    def __init__(self, *, timeout_seconds: float = 6.0) -> None:
        if timeout_seconds <= 0 or timeout_seconds > 15:
            raise ValueError("UI Automation timeout must be between 0 and 15 seconds")
        self.timeout_seconds = timeout_seconds
        self._lock = threading.RLock()
        self._active: set[subprocess.Popen[bytes]] = set()
        self._encoded_script = base64.b64encode(
            _SCRIPT.encode("utf-16-le")
        ).decode("ascii")

    def inspect(self, hwnd: int) -> tuple[dict[str, Any], ...]:
        result = self._call({"operation": "inspect", "hwnd": hwnd})
        elements = result.get("elements")
        if not isinstance(elements, list):
            raise UIAutomationError("UI Automation returned an invalid element tree")
        return tuple(item for item in elements if isinstance(item, dict))

    def set_value(self, hwnd: int, runtime_id: str, value: str) -> str:
        result = self._call(
            {
                "operation": "set_value",
                "hwnd": hwnd,
                "runtime_id": runtime_id,
                "value": value,
            }
        )
        observed = result.get("value")
        if result.get("success") is not True or not isinstance(observed, str):
            raise UIAutomationError("UI Automation text verification failed")
        return observed

    def invoke(self, hwnd: int, runtime_id: str) -> None:
        result = self._call(
            {
                "operation": "invoke",
                "hwnd": hwnd,
                "runtime_id": runtime_id,
            }
        )
        if result.get("success") is not True:
            raise UIAutomationError("UI Automation action was not accepted")

    def interrupt(self) -> None:
        with self._lock:
            active = tuple(self._active)
        for process in active:
            try:
                process.terminate()
            except OSError:
                continue

    def _call(self, request: dict[str, Any]) -> dict[str, Any]:
        if os.name != "nt":
            raise UIAutomationError("Windows UI Automation is unavailable")
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        secret_markers = (
            "KEY",
            "TOKEN",
            "SECRET",
            "PASSWORD",
            "CREDENTIAL",
            "AUTH",
        )
        environment = {
            key: value
            for key, value in os.environ.items()
            if not any(marker in key.upper() for marker in secret_markers)
        }
        try:
            process = subprocess.Popen(
                [
                    "powershell.exe",
                    "-NoLogo",
                    "-NoProfile",
                    "-NonInteractive",
                    "-EncodedCommand",
                    self._encoded_script,
                ],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                creationflags=creationflags,
                env=environment,
            )
        except OSError as exc:
            raise UIAutomationError("Windows UI Automation host is unavailable") from exc
        with self._lock:
            self._active.add(process)
        try:
            payload = json.dumps(request, ensure_ascii=False).encode("utf-8")
            try:
                stdout, _stderr = process.communicate(
                    payload,
                    timeout=self.timeout_seconds,
                )
            except subprocess.TimeoutExpired as exc:
                process.kill()
                process.communicate()
                raise UIAutomationError("Windows UI Automation timed out") from exc
        finally:
            with self._lock:
                self._active.discard(process)
        if process.returncode != 0 or len(stdout) > 1_000_000:
            raise UIAutomationError("Windows UI Automation operation failed")
        try:
            value = json.loads(stdout.decode("utf-8-sig"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise UIAutomationError("Windows UI Automation returned invalid data") from exc
        if not isinstance(value, dict):
            raise UIAutomationError("Windows UI Automation returned invalid data")
        return value


__all__ = ["UIAutomationError", "WindowsUIAutomationBridge"]
