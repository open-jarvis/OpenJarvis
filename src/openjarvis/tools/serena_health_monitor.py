"""Native Serena Health Monitor tools.

Serena Health Monitor Full Operator v1:
- inspect local system/Python/uv health
- inspect Serena project files
- inspect outputs
- inspect conversion registry
- inspect skill docs
- inspect Git state
- create final operator health report
"""

from __future__ import annotations

import importlib
import json
import os
import platform
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from openjarvis.core.registry import ToolRegistry
from openjarvis.tools._stubs import BaseTool, ToolResult, ToolSpec


HEALTH_OUTPUT_ROOT = Path("outputs/health-monitor")


def _timestamp() -> str:
    return time.strftime("%Y%m%d-%H%M%S")


def _health_root() -> Path:
    HEALTH_OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    for child in ["reports", "snapshots"]:
        (HEALTH_OUTPUT_ROOT / child).mkdir(parents=True, exist_ok=True)
    return HEALTH_OUTPUT_ROOT


def _safe_slug(value: str) -> str:
    import re

    slug = re.sub(r"[^a-zA-Z0-9]+", "-", str(value or "").strip().lower()).strip("-")
    return slug or "health"


def _save_report(name: str, payload: dict[str, Any]) -> Path:
    root = _health_root()
    path = root / "reports" / f"{_timestamp()}-{_safe_slug(name)}.json"
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def _run(cmd: list[str], timeout: int = 60) -> dict[str, Any]:
    try:
        result = subprocess.run(
            cmd,
            cwd=str(Path.cwd()),
            capture_output=True,
            text=True,
            timeout=timeout,
            shell=False,
        )
        output = (result.stdout or "") + ("\n" + result.stderr if result.stderr else "")
        return {
            "command": cmd,
            "returncode": result.returncode,
            "stdout": result.stdout or "",
            "stderr": result.stderr or "",
            "output": output.strip(),
        }
    except Exception as exc:
        return {
            "command": cmd,
            "returncode": -1,
            "stdout": "",
            "stderr": str(exc),
            "output": str(exc),
        }


def _path_info(path: Path) -> dict[str, Any]:
    exists = path.exists()
    info: dict[str, Any] = {
        "path": str(path),
        "exists": exists,
        "is_file": path.is_file() if exists else False,
        "is_dir": path.is_dir() if exists else False,
    }

    if exists:
        try:
            info["size_bytes"] = path.stat().st_size
        except Exception:
            info["size_bytes"] = None

        if path.is_dir():
            try:
                entries = list(path.iterdir())
                info["immediate_files"] = sum(1 for item in entries if item.is_file())
                info["immediate_dirs"] = sum(1 for item in entries if item.is_dir())
            except Exception:
                info["immediate_files"] = None
                info["immediate_dirs"] = None

    return info


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _conversion_registry_path() -> Path:
    return Path("src/openjarvis/serena_capabilities/conversion_registry.json")


def _skill_docs_root() -> Path:
    return Path("src/openjarvis/skills/serena")


def _important_tool_modules() -> list[str]:
    return [
        "openjarvis.tools.serena_wordpress",
        "openjarvis.tools.serena_documents",
        "openjarvis.tools.serena_files",
        "openjarvis.tools.serena_vscode",
        "openjarvis.tools.serena_vscode_builder",
        "openjarvis.tools.serena_github",
        "openjarvis.tools.serena_health_monitor",
    ]


def _collect_registry_health() -> dict[str, Any]:
    path = _conversion_registry_path()
    health: dict[str, Any] = {
        "path": str(path),
        "exists": path.exists(),
        "total_batch_1": 0,
        "complete_batch_1": 0,
        "remaining_batch_1": 0,
        "completed": [],
        "remaining": [],
        "issues": [],
    }

    if not path.exists():
        health["issues"].append("conversion_registry.json not found")
        return health

    try:
        registry = _load_json(path)
        batch = registry.get("batches", {}).get("batch-1-foundation", {})
        skills = batch.get("skills", [])
        health["total_batch_1"] = len(skills)

        complete_statuses = {"complete_v1", "tested", "complete", "done"}
        for item in skills:
            is_complete = item.get("status") in complete_statuses or item.get("native_tool_complete") is True
            entry = {
                "legacy_file": item.get("legacy_file"),
                "status": item.get("status"),
                "completion_level": item.get("completion_level", ""),
            }
            if is_complete:
                health["completed"].append(entry)
            else:
                health["remaining"].append(entry)

        health["complete_batch_1"] = len(health["completed"])
        health["remaining_batch_1"] = len(health["remaining"])
    except Exception as exc:
        health["issues"].append(f"Failed to read conversion registry: {exc}")

    return health


def _collect_skill_docs_health() -> dict[str, Any]:
    root = _skill_docs_root()
    expected = [
        "wordpress",
        "documents",
        "files",
        "vscode",
        "vscode-builder",
        "github",
        "health-monitor",
    ]

    docs = []
    missing = []

    for name in expected:
        path = root / name / "skill.md"
        item = _path_info(path)
        item["skill"] = name
        docs.append(item)
        if not item["exists"]:
            missing.append(name)

    return {
        "root": str(root),
        "expected": expected,
        "docs": docs,
        "missing": missing,
    }


def _collect_outputs_health() -> dict[str, Any]:
    expected = [
        "wordpress",
        "documents",
        "files",
        "vscode",
        "vscode-builder",
        "github",
        "health-monitor",
    ]

    outputs = []
    for name in expected:
        outputs.append({"name": name, **_path_info(Path("outputs") / name)})

    return {
        "root": str(Path("outputs")),
        "outputs": outputs,
        "missing": [item["name"] for item in outputs if not item["exists"]],
    }


def _collect_git_health() -> dict[str, Any]:
    commands = {
        "inside_work_tree": ["git", "rev-parse", "--is-inside-work-tree"],
        "branch": ["git", "branch", "--show-current"],
        "status": ["git", "status", "--short", "--branch"],
        "recent_commits": ["git", "log", "--oneline", "-n", "8"],
        "remotes": ["git", "remote", "-v"],
    }

    results = {name: _run(cmd) for name, cmd in commands.items()}
    status = results["status"]["output"]

    issues = []
    recommendations = []

    if results["inside_work_tree"]["returncode"] != 0:
        issues.append("Current folder is not inside a Git work tree.")
    if "??" in status:
        recommendations.append("Untracked files detected. Review before finalizing.")
    if " M" in status or "M " in status:
        recommendations.append("Modified files detected. Review before finalizing.")

    return {
        "results": results,
        "issues": issues,
        "recommendations": recommendations,
    }


def _collect_import_health() -> dict[str, Any]:
    modules = _important_tool_modules()
    results = []

    for module in modules:
        try:
            importlib.import_module(module)
            results.append({"module": module, "success": True, "error": ""})
        except Exception as exc:
            results.append({"module": module, "success": False, "error": str(exc)})

    return {
        "modules": results,
        "failed": [item for item in results if not item["success"]],
    }


def _collect_system_health() -> dict[str, Any]:
    disk = shutil.disk_usage(Path.cwd())

    return {
        "platform": platform.platform(),
        "system": platform.system(),
        "release": platform.release(),
        "machine": platform.machine(),
        "python_executable": sys.executable,
        "python_version": sys.version,
        "cwd": str(Path.cwd()),
        "uv_available": shutil.which("uv") is not None,
        "git_available": shutil.which("git") is not None,
        "code_available": shutil.which("code") is not None or shutil.which("code.cmd") is not None,
        "disk_total_bytes": disk.total,
        "disk_used_bytes": disk.used,
        "disk_free_bytes": disk.free,
    }


class _HealthBaseTool(BaseTool):
    def _result(self, content: str, success: bool = True, metadata: dict[str, Any] | None = None) -> ToolResult:
        return ToolResult(
            tool_name=getattr(self, "tool_id", self.__class__.__name__),
            success=success,
            content=content,
            metadata=metadata or {},
        )


@ToolRegistry.register("serena_health_monitor_status")
class SerenaHealthMonitorStatusTool(_HealthBaseTool):
    tool_id = "serena_health_monitor_status"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Show Serena Health Monitor status.",
            parameters={"type": "object", "properties": {}},
            category="serena_health_monitor",
        )

    def execute(self, **params: Any) -> ToolResult:
        root = _health_root()
        return self._result(
            "Serena Health Monitor status\n\n"
            "- Status: active\n"
            "- Role: local Serena operator/project health dashboard\n"
            "- Checks: system, project, outputs, registry, skills, git, imports, final-report\n"
            f"- Output root: {root}\n"
            f"- Reports: {root / 'reports'}\n"
            f"- Snapshots: {root / 'snapshots'}",
            metadata={"output_root": str(root)},
        )


@ToolRegistry.register("serena_health_monitor_system")
class SerenaHealthMonitorSystemTool(_HealthBaseTool):
    tool_id = "serena_health_monitor_system"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Inspect system, Python, uv, git, code, and disk health.",
            parameters={"type": "object", "properties": {}},
            category="serena_health_monitor",
        )

    def execute(self, **params: Any) -> ToolResult:
        health = _collect_system_health()
        report_path = _save_report("system", {"report_type": "system", "created_at": _timestamp(), **health})

        free_gb = health["disk_free_bytes"] / (1024 ** 3)
        total_gb = health["disk_total_bytes"] / (1024 ** 3)

        return self._result(
            "Serena system health\n\n"
            f"- Platform: {health['platform']}\n"
            f"- Python: {health['python_executable']}\n"
            f"- uv available: {'yes' if health['uv_available'] else 'no'}\n"
            f"- git available: {'yes' if health['git_available'] else 'no'}\n"
            f"- VS Code CLI available: {'yes' if health['code_available'] else 'no'}\n"
            f"- Disk free: {free_gb:.2f} GB / {total_gb:.2f} GB\n"
            f"- Report: {report_path}",
            metadata={**health, "report_path": str(report_path)},
        )


@ToolRegistry.register("serena_health_monitor_project")
class SerenaHealthMonitorProjectTool(_HealthBaseTool):
    tool_id = "serena_health_monitor_project"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Inspect core Serena project files and folders.",
            parameters={"type": "object", "properties": {}},
            category="serena_health_monitor",
        )

    def execute(self, **params: Any) -> ToolResult:
        paths = [
            "pyproject.toml",
            "uv.lock",
            "src/openjarvis",
            "src/openjarvis/cli",
            "src/openjarvis/tools",
            "src/openjarvis/skills/serena",
            "src/openjarvis/serena_identity.py",
            "src/openjarvis/serena_capabilities/conversion_registry.json",
            "config/serena_file_roots.json",
            "conversion-workspace",
            "outputs",
        ]

        infos = [_path_info(Path(item)) for item in paths]
        missing = [item["path"] for item in infos if not item["exists"]]

        payload = {
            "report_type": "project",
            "created_at": _timestamp(),
            "paths": infos,
            "missing": missing,
        }
        report_path = _save_report("project", payload)

        return self._result(
            "Serena project health\n\n"
            f"- Checked paths: {len(paths)}\n"
            f"- Missing paths: {len(missing)}\n"
            f"- Report: {report_path}\n\n"
            "Missing:\n"
            + ("\n".join(f"- {item}" for item in missing) if missing else "- none"),
            metadata={**payload, "report_path": str(report_path)},
        )


@ToolRegistry.register("serena_health_monitor_outputs")
class SerenaHealthMonitorOutputsTool(_HealthBaseTool):
    tool_id = "serena_health_monitor_outputs"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Inspect Serena output folders.",
            parameters={"type": "object", "properties": {}},
            category="serena_health_monitor",
        )

    def execute(self, **params: Any) -> ToolResult:
        health = _collect_outputs_health()
        payload = {"report_type": "outputs", "created_at": _timestamp(), **health}
        report_path = _save_report("outputs", payload)

        lines = [
            "Serena outputs health",
            "",
            f"- Output root: {health['root']}",
            f"- Missing output folders: {len(health['missing'])}",
            f"- Report: {report_path}",
            "",
            "Output folders:",
        ]

        for item in health["outputs"]:
            lines.append(
                f"- {item['name']} | exists={'yes' if item['exists'] else 'no'} | "
                f"files={item.get('immediate_files', 0)} | folders={item.get('immediate_dirs', 0)}"
            )

        return self._result("\n".join(lines), metadata={**payload, "report_path": str(report_path)})


@ToolRegistry.register("serena_health_monitor_registry")
class SerenaHealthMonitorRegistryTool(_HealthBaseTool):
    tool_id = "serena_health_monitor_registry"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Inspect Serena conversion registry health.",
            parameters={"type": "object", "properties": {}},
            category="serena_health_monitor",
        )

    def execute(self, **params: Any) -> ToolResult:
        health = _collect_registry_health()
        payload = {"report_type": "registry", "created_at": _timestamp(), **health}
        report_path = _save_report("registry", payload)

        lines = [
            "Serena conversion registry health",
            "",
            f"- Registry exists: {'yes' if health['exists'] else 'no'}",
            f"- Batch 1 total: {health['total_batch_1']}",
            f"- Batch 1 complete: {health['complete_batch_1']}",
            f"- Batch 1 remaining: {health['remaining_batch_1']}",
            f"- Report: {report_path}",
            "",
            "Completed:",
        ]
        lines.extend(f"- {item['legacy_file']} | {item['status']} | {item['completion_level']}" for item in health["completed"]) if health["completed"] else lines.append("- none")
        lines.extend(["", "Remaining:"])
        lines.extend(f"- {item['legacy_file']} | {item['status']}" for item in health["remaining"]) if health["remaining"] else lines.append("- none")

        return self._result("\n".join(lines), metadata={**payload, "report_path": str(report_path)})


@ToolRegistry.register("serena_health_monitor_skills")
class SerenaHealthMonitorSkillsTool(_HealthBaseTool):
    tool_id = "serena_health_monitor_skills"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Inspect Serena skill documentation and native tool imports.",
            parameters={"type": "object", "properties": {}},
            category="serena_health_monitor",
        )

    def execute(self, **params: Any) -> ToolResult:
        docs = _collect_skill_docs_health()
        imports = _collect_import_health()

        payload = {
            "report_type": "skills",
            "created_at": _timestamp(),
            "docs": docs,
            "imports": imports,
        }
        report_path = _save_report("skills", payload)

        lines = [
            "Serena skills health",
            "",
            f"- Expected skill docs: {len(docs['expected'])}",
            f"- Missing skill docs: {len(docs['missing'])}",
            f"- Tool import failures: {len(imports['failed'])}",
            f"- Report: {report_path}",
            "",
            "Skill docs:",
        ]

        for item in docs["docs"]:
            lines.append(f"- {item['skill']} | exists={'yes' if item['exists'] else 'no'} | {item['path']}")

        lines.extend(["", "Tool imports:"])
        for item in imports["modules"]:
            lines.append(f"- {item['module']} | success={'yes' if item['success'] else 'no'}")

        return self._result("\n".join(lines), metadata={**payload, "report_path": str(report_path)})


@ToolRegistry.register("serena_health_monitor_git")
class SerenaHealthMonitorGitTool(_HealthBaseTool):
    tool_id = "serena_health_monitor_git"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Inspect Git health.",
            parameters={"type": "object", "properties": {}},
            category="serena_health_monitor",
        )

    def execute(self, **params: Any) -> ToolResult:
        health = _collect_git_health()
        payload = {"report_type": "git", "created_at": _timestamp(), **health}
        report_path = _save_report("git", payload)

        branch = health["results"]["branch"]["output"]
        status = health["results"]["status"]["output"]

        lines = [
            "Serena Git health",
            "",
            f"- Branch: {branch or 'unknown'}",
            f"- Report: {report_path}",
            "",
            "Status:",
            status or "clean",
            "",
            "Issues:",
        ]
        lines.extend(f"- {item}" for item in health["issues"]) if health["issues"] else lines.append("- none")
        lines.extend(["", "Recommendations:"])
        lines.extend(f"- {item}" for item in health["recommendations"]) if health["recommendations"] else lines.append("- No immediate recommendations.")

        return self._result("\n".join(lines), metadata={**payload, "report_path": str(report_path)})


@ToolRegistry.register("serena_health_monitor_final_report")
class SerenaHealthMonitorFinalReportTool(_HealthBaseTool):
    tool_id = "serena_health_monitor_final_report"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Create a full Serena operator health report.",
            parameters={"type": "object", "properties": {}},
            category="serena_health_monitor",
        )

    def execute(self, **params: Any) -> ToolResult:
        system = _collect_system_health()
        project_paths = SerenaHealthMonitorProjectTool().execute()
        outputs = _collect_outputs_health()
        registry = _collect_registry_health()
        skills = _collect_skill_docs_health()
        imports = _collect_import_health()
        git = _collect_git_health()

        issues: list[str] = []
        recommendations: list[str] = []

        if not system["uv_available"]:
            issues.append("uv is not available.")
        if not system["git_available"]:
            issues.append("git is not available.")
        if registry["remaining_batch_1"] > 0:
            recommendations.append(f"Batch 1 has {registry['remaining_batch_1']} remaining skill(s).")
        if skills["missing"]:
            issues.append(f"Missing skill docs: {', '.join(skills['missing'])}")
        if imports["failed"]:
            issues.append(f"Tool import failures: {len(imports['failed'])}")
        issues.extend(git["issues"])
        recommendations.extend(git["recommendations"])

        overall_status = "healthy" if not issues else "needs_attention"

        payload = {
            "report_type": "serena_health_monitor_final_report",
            "created_at": _timestamp(),
            "overall_status": overall_status,
            "system": system,
            "outputs": outputs,
            "registry": registry,
            "skills": skills,
            "imports": imports,
            "git": git,
            "issues": issues,
            "recommendations": recommendations,
        }
        report_path = _save_report("final-report", payload)

        return self._result(
            "Serena Health Monitor final report\n\n"
            f"- Overall status: {overall_status}\n"
            f"- Batch 1 complete: {registry['complete_batch_1']} / {registry['total_batch_1']}\n"
            f"- Batch 1 remaining: {registry['remaining_batch_1']}\n"
            f"- Missing skill docs: {len(skills['missing'])}\n"
            f"- Tool import failures: {len(imports['failed'])}\n"
            f"- Report: {report_path}\n\n"
            "Issues:\n"
            + ("\n".join(f"- {item}" for item in issues) if issues else "- none")
            + "\n\nRecommendations:\n"
            + ("\n".join(f"- {item}" for item in recommendations) if recommendations else "- No immediate recommendations."),
            metadata={**payload, "report_path": str(report_path)},
        )


def _run_powershell(command: str, timeout: int = 30) -> dict[str, Any]:
    ps = shutil.which("powershell") or shutil.which("pwsh")
    if not ps:
        return {
            "command": command,
            "returncode": -1,
            "stdout": "",
            "stderr": "PowerShell not found",
            "output": "PowerShell not found",
        }

    try:
        result = subprocess.run(
            [ps, "-NoProfile", "-Command", command],
            cwd=str(Path.cwd()),
            capture_output=True,
            text=True,
            timeout=timeout,
            shell=False,
        )
        output = (result.stdout or "") + ("\n" + result.stderr if result.stderr else "")
        return {
            "command": command,
            "returncode": result.returncode,
            "stdout": result.stdout or "",
            "stderr": result.stderr or "",
            "output": output.strip(),
        }
    except Exception as exc:
        return {
            "command": command,
            "returncode": -1,
            "stdout": "",
            "stderr": str(exc),
            "output": str(exc),
        }


def _collect_hardware_health() -> dict[str, Any]:
    disk = shutil.disk_usage(Path.cwd())

    checks = {
        "computer_system": "Get-CimInstance Win32_ComputerSystem | Select-Object Manufacturer,Model,TotalPhysicalMemory | ConvertTo-Json -Compress",
        "processor": "Get-CimInstance Win32_Processor | Select-Object Name,NumberOfCores,NumberOfLogicalProcessors,MaxClockSpeed | ConvertTo-Json -Compress",
        "bios": "Get-CimInstance Win32_BIOS | Select-Object Manufacturer,SMBIOSBIOSVersion,ReleaseDate | ConvertTo-Json -Compress",
        "gpu": "Get-CimInstance Win32_VideoController | Select-Object Name,AdapterRAM,DriverVersion | ConvertTo-Json -Compress",
        "physical_memory": "Get-CimInstance Win32_PhysicalMemory | Select-Object Manufacturer,Capacity,Speed,PartNumber | ConvertTo-Json -Compress",
        "logical_disks": "Get-CimInstance Win32_LogicalDisk | Select-Object DeviceID,DriveType,Size,FreeSpace,VolumeName | ConvertTo-Json -Compress",
        "battery": "Get-CimInstance Win32_Battery | Select-Object Name,EstimatedChargeRemaining,BatteryStatus | ConvertTo-Json -Compress",
        "cameras": "Get-CimInstance Win32_PnPEntity | Where-Object { $_.Name -match 'camera|webcam|video' } | Select-Object Name,Status,Manufacturer | ConvertTo-Json -Compress",
        "audio": "Get-CimInstance Win32_SoundDevice | Select-Object Name,Status,Manufacturer | ConvertTo-Json -Compress",
    }

    results = {name: _run_powershell(cmd) for name, cmd in checks.items()}

    issues: list[str] = []
    recommendations: list[str] = []

    free_gb = disk.free / (1024 ** 3)
    total_gb = disk.total / (1024 ** 3)

    if free_gb < 20:
        recommendations.append("Disk free space is below 20 GB. Consider cleanup or backup before heavy builds.")
    if results["processor"]["returncode"] != 0:
        recommendations.append("Could not read CPU details through PowerShell/CIM.")
    if results["gpu"]["returncode"] != 0:
        recommendations.append("Could not read GPU details through PowerShell/CIM.")
    if results["cameras"]["returncode"] != 0:
        recommendations.append("Could not read camera/webcam device details.")
    if results["audio"]["returncode"] != 0:
        recommendations.append("Could not read audio device details.")

    return {
        "platform": platform.platform(),
        "machine": platform.machine(),
        "disk_total_bytes": disk.total,
        "disk_used_bytes": disk.used,
        "disk_free_bytes": disk.free,
        "disk_total_gb": round(total_gb, 2),
        "disk_free_gb": round(free_gb, 2),
        "powershell_checks": results,
        "issues": issues,
        "recommendations": recommendations,
    }


def _resolve_command(candidates: list[str]) -> str | None:
    for candidate in candidates:
        found = shutil.which(candidate)
        if found:
            return found
    return None


def _run_tool_version(name: str, candidates: list[str], args: list[str]) -> dict[str, Any]:
    resolved = _resolve_command(candidates)
    if not resolved:
        return {
            "command": candidates + args,
            "resolved_command": "",
            "returncode": -1,
            "stdout": "",
            "stderr": "not found",
            "output": "not found",
        }

    result = _run([resolved] + args, timeout=30)
    result["resolved_command"] = resolved
    return result


def _collect_software_health() -> dict[str, Any]:
    results = {
        "python": _run([sys.executable, "--version"], timeout=30),
        "uv": _run_tool_version("uv", ["uv", "uv.exe"], ["--version"]),
        "git": _run_tool_version("git", ["git", "git.exe"], ["--version"]),
        "code": _run_tool_version("code", ["code", "code.cmd", "code.exe"], ["--version"]),
        "node": _run_tool_version("node", ["node", "node.exe"], ["--version"]),
        "npm": _run_tool_version("npm", ["npm", "npm.cmd", "npm.exe"], ["--version"]),
        "pnpm": _run_tool_version("pnpm", ["pnpm", "pnpm.cmd", "pnpm.exe"], ["--version"]),
    }

    powershell_version = _run_powershell("$PSVersionTable.PSVersion.ToString()", timeout=15)
    windows_version = _run_powershell("(Get-CimInstance Win32_OperatingSystem | Select-Object Caption,Version,BuildNumber,OSArchitecture) | ConvertTo-Json -Compress", timeout=15)

    required = ["python", "uv", "git", "code"]
    optional = ["node", "npm", "pnpm"]

    issues: list[str] = []
    recommendations: list[str] = []

    for item in required:
        if results[item]["returncode"] != 0:
            issues.append(f"Required developer tool unavailable or failing: {item}")

    for item in optional:
        if results[item]["returncode"] != 0:
            recommendations.append(f"Optional frontend tool not available: {item}")

    if powershell_version["returncode"] != 0:
        recommendations.append("Could not determine PowerShell version.")

    return {
        "tool_results": results,
        "powershell_version": powershell_version,
        "windows_version": windows_version,
        "issues": issues,
        "recommendations": recommendations,
    }


@ToolRegistry.register("serena_health_monitor_hardware")
class SerenaHealthMonitorHardwareTool(_HealthBaseTool):
    tool_id = "serena_health_monitor_hardware"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Inspect local PC hardware health using safe read-only checks.",
            parameters={"type": "object", "properties": {}},
            category="serena_health_monitor",
        )

    def execute(self, **params: Any) -> ToolResult:
        health = _collect_hardware_health()
        payload = {"report_type": "hardware", "created_at": _timestamp(), **health}
        report_path = _save_report("hardware", payload)

        lines = [
            "Serena hardware health",
            "",
            f"- Platform: {health['platform']}",
            f"- Machine: {health['machine']}",
            f"- Disk free: {health['disk_free_gb']} GB / {health['disk_total_gb']} GB",
            f"- Report: {report_path}",
            "",
            "Hardware checks:",
        ]

        for name, result in health["powershell_checks"].items():
            status = "ok" if result["returncode"] == 0 else "warning"
            preview = (result["output"] or "").replace("\n", " ")[:300]
            lines.append(f"- {name}: {status} | {preview or 'no output'}")

        lines.extend(["", "Issues:"])
        lines.extend(f"- {item}" for item in health["issues"]) if health["issues"] else lines.append("- none")

        lines.extend(["", "Recommendations:"])
        lines.extend(f"- {item}" for item in health["recommendations"]) if health["recommendations"] else lines.append("- No immediate recommendations.")

        return self._result("\n".join(lines), metadata={**payload, "report_path": str(report_path)})


@ToolRegistry.register("serena_health_monitor_software")
class SerenaHealthMonitorSoftwareTool(_HealthBaseTool):
    tool_id = "serena_health_monitor_software"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Inspect local software/developer tool health using safe read-only checks.",
            parameters={"type": "object", "properties": {}},
            category="serena_health_monitor",
        )

    def execute(self, **params: Any) -> ToolResult:
        health = _collect_software_health()
        payload = {"report_type": "software", "created_at": _timestamp(), **health}
        report_path = _save_report("software", payload)

        lines = [
            "Serena software health",
            "",
            f"- Report: {report_path}",
            "",
            "Tool checks:",
        ]

        for name, result in health["tool_results"].items():
            status = "ok" if result["returncode"] == 0 else "missing/warning"
            output = (result["output"] or "").replace("\n", " ")[:250]
            lines.append(f"- {name}: {status} | {output}")

        ps_status = "ok" if health["powershell_version"]["returncode"] == 0 else "warning"
        win_status = "ok" if health["windows_version"]["returncode"] == 0 else "warning"

        lines.extend([
            f"- powershell: {ps_status} | {(health['powershell_version']['output'] or '')[:250]}",
            f"- windows: {win_status} | {(health['windows_version']['output'] or '')[:250]}",
            "",
            "Issues:",
        ])

        lines.extend(f"- {item}" for item in health["issues"]) if health["issues"] else lines.append("- none")

        lines.extend(["", "Recommendations:"])
        lines.extend(f"- {item}" for item in health["recommendations"]) if health["recommendations"] else lines.append("- No immediate recommendations.")

        return self._result("\n".join(lines), metadata={**payload, "report_path": str(report_path)})


@ToolRegistry.register("serena_health_monitor_device_report")
class SerenaHealthMonitorDeviceReportTool(_HealthBaseTool):
    tool_id = "serena_health_monitor_device_report"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Create a combined PC hardware/software and Serena operator health report.",
            parameters={"type": "object", "properties": {}},
            category="serena_health_monitor",
        )

    def execute(self, **params: Any) -> ToolResult:
        hardware = _collect_hardware_health()
        software = _collect_software_health()
        system = _collect_system_health()
        registry = _collect_registry_health()
        skills = _collect_skill_docs_health()
        imports = _collect_import_health()
        git = _collect_git_health()

        issues: list[str] = []
        recommendations: list[str] = []

        issues.extend(hardware["issues"])
        issues.extend(software["issues"])
        if skills["missing"]:
            issues.append(f"Missing skill docs: {', '.join(skills['missing'])}")
        if imports["failed"]:
            issues.append(f"Tool import failures: {len(imports['failed'])}")
        issues.extend(git["issues"])

        recommendations.extend(hardware["recommendations"])
        recommendations.extend(software["recommendations"])
        recommendations.extend(git["recommendations"])

        if registry["remaining_batch_1"] > 0:
            recommendations.append(f"Batch 1 has {registry['remaining_batch_1']} remaining skill(s).")

        overall_status = "healthy" if not issues else "needs_attention"

        payload = {
            "report_type": "serena_health_monitor_device_report",
            "created_at": _timestamp(),
            "overall_status": overall_status,
            "hardware": hardware,
            "software": software,
            "system": system,
            "registry": registry,
            "skills": skills,
            "imports": imports,
            "git": git,
            "issues": issues,
            "recommendations": recommendations,
            "read_only": True,
            "changes_made": False,
        }
        report_path = _save_report("device-report", payload)

        return self._result(
            "Serena device health report\n\n"
            f"- Overall status: {overall_status}\n"
            f"- Disk free: {hardware['disk_free_gb']} GB / {hardware['disk_total_gb']} GB\n"
            f"- Batch 1 complete: {registry['complete_batch_1']} / {registry['total_batch_1']}\n"
            f"- Missing skill docs: {len(skills['missing'])}\n"
            f"- Tool import failures: {len(imports['failed'])}\n"
            f"- Report: {report_path}\n"
            "- Read-only scan: yes\n"
            "- Changes made: no\n\n"
            "Issues:\n"
            + ("\n".join(f"- {item}" for item in issues) if issues else "- none")
            + "\n\nRecommendations:\n"
            + ("\n".join(f"- {item}" for item in recommendations) if recommendations else "- No immediate recommendations."),
            metadata={**payload, "report_path": str(report_path)},
        )


__all__ = [
    "SerenaHealthMonitorStatusTool",
    "SerenaHealthMonitorSystemTool",
    "SerenaHealthMonitorProjectTool",
    "SerenaHealthMonitorOutputsTool",
    "SerenaHealthMonitorRegistryTool",
    "SerenaHealthMonitorSkillsTool",
    "SerenaHealthMonitorGitTool",
    "SerenaHealthMonitorFinalReportTool",
    "SerenaHealthMonitorDeviceReportTool",
    "SerenaHealthMonitorSoftwareTool",
    "SerenaHealthMonitorHardwareTool",
]
