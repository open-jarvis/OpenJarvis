"""Native Serena OCR / Live Vision operator tools.

Serena OCR / Live Vision Full Operator v1 foundation:
- status
- engine detection
- camera status
- operation planning
- safety policy
"""

from __future__ import annotations

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


OCR_OUTPUT_ROOT = Path("outputs/ocr")
LIVE_STATE_PATH = OCR_OUTPUT_ROOT / "live" / "session-state.json"


def _timestamp() -> str:
    return time.strftime("%Y%m%d-%H%M%S")


def _safe_slug(value: str) -> str:
    import re

    slug = re.sub(r"[^a-zA-Z0-9]+", "-", str(value or "").strip().lower()).strip("-")
    return slug or "ocr"


def _ocr_root() -> Path:
    OCR_OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    for child in [
        "captures",
        "reports",
        "extracted-text",
        "handoff",
        "live",
        "live/frames",
    ]:
        (OCR_OUTPUT_ROOT / child).mkdir(parents=True, exist_ok=True)
    return OCR_OUTPUT_ROOT


def _save_json(kind: str, name: str, payload: dict[str, Any]) -> Path:
    root = _ocr_root()
    folder = root / kind
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{_timestamp()}-{_safe_slug(name)}.json"
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def _run(cmd: list[str], timeout: int = 30) -> dict[str, Any]:
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


def _module_check(module_name: str) -> dict[str, Any]:
    result = _run(
        [
            sys.executable,
            "-c",
            f"import {module_name}; print('{module_name} ok')",
        ],
        timeout=20,
    )
    return result


def _command_check(command: str, version_args: list[str] | None = None) -> dict[str, Any]:
    resolved = shutil.which(command)
    if not resolved:
        return {
            "command": [command] + (version_args or []),
            "resolved": "",
            "returncode": -1,
            "stdout": "",
            "stderr": "not found",
            "output": "not found",
        }

    args = [resolved] + (version_args or ["--version"])
    result = _run(args, timeout=20)
    result["resolved"] = resolved
    return result


def _env_status() -> dict[str, Any]:
    optional = [
        "HUGGINGFACE_API_KEY",
        "MISTRAL_API_KEY",
        "OPENAI_API_KEY",
        "GOOGLE_CLIENT_ID",
        "GOOGLE_CLIENT_SECRET",
        "GOOGLE_REFRESH_TOKEN",
        "GDRIVE_ROOT_FOLDER_ID",
    ]

    values = []
    for name in optional:
        value = os.getenv(name, "")
        values.append(
            {
                "name": name,
                "present": bool(value.strip()),
                "length": len(value) if value else 0,
                "preview": f"{value[:4]}..." if value else "",
            }
        )

    return {
        "optional": values,
        "secret_values_exposed": False,
    }


def _engine_status() -> dict[str, Any]:
    checks = {
        "python": _run([sys.executable, "--version"], timeout=20),
        "opencv_cv2": _module_check("cv2"),
        "pillow_PIL": _module_check("PIL"),
        "pytesseract_module": _module_check("pytesseract"),
        "pdf2image_module": _module_check("pdf2image"),
        "tesseract_cli": _command_check("tesseract", ["--version"]),
        "ffmpeg_cli": _command_check("ffmpeg", ["-version"]),
    }

    recommendations: list[str] = []

    if checks["opencv_cv2"]["returncode"] != 0:
        recommendations.append("OpenCV is not available yet. Needed for webcam capture and live vision.")
    if checks["pillow_PIL"]["returncode"] != 0:
        recommendations.append("Pillow is not available yet. Needed for image inspection.")
    if checks["pytesseract_module"]["returncode"] != 0:
        recommendations.append("pytesseract is not available yet. Needed for local OCR.")
    if checks["tesseract_cli"]["returncode"] != 0:
        recommendations.append("Tesseract CLI is not available yet. Needed for strongest local OCR.")
    if checks["pdf2image_module"]["returncode"] != 0:
        recommendations.append("pdf2image is not available yet. Needed for PDF/image-page OCR later.")

    return {
        "checks": checks,
        "recommendations": recommendations,
        "local_ocr_ready": (
            checks["pillow_PIL"]["returncode"] == 0
            and checks["pytesseract_module"]["returncode"] == 0
            and checks["tesseract_cli"]["returncode"] == 0
        ),
        "webcam_ready": checks["opencv_cv2"]["returncode"] == 0,
    }


def _load_live_state() -> dict[str, Any]:
    _ocr_root()
    if LIVE_STATE_PATH.exists():
        try:
            return json.loads(LIVE_STATE_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass

    return {
        "active": False,
        "mode": "",
        "camera_index": None,
        "interval_seconds": None,
        "max_minutes": None,
        "started_at": "",
        "stopped_at": "",
        "frames_captured": 0,
        "frames_saved": 0,
        "last_frame": "",
        "stop_requested": False,
        "artifacts": [],
    }


def _save_live_state(state: dict[str, Any]) -> Path:
    _ocr_root()
    LIVE_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    LIVE_STATE_PATH.write_text(json.dumps(state, indent=2), encoding="utf-8")
    return LIVE_STATE_PATH


def _camera_probe(max_indexes: int = 5) -> dict[str, Any]:
    cv2_check = _module_check("cv2")
    if cv2_check["returncode"] != 0:
        return {
            "opencv_available": False,
            "cameras": [],
            "issues": ["OpenCV/cv2 is not available."],
            "recommendations": ["Install OpenCV before testing webcam capture."],
        }

    probe_script = r'''
import cv2
import json

results = []
for index in range(0, MAX_INDEXES):
    cap = cv2.VideoCapture(index, cv2.CAP_DSHOW)
    opened = bool(cap.isOpened())
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
    fps = float(cap.get(cv2.CAP_PROP_FPS) or 0)
    ok = False
    if opened:
        ok, frame = cap.read()
    cap.release()
    results.append({
        "index": index,
        "opened": opened,
        "frame_read": bool(ok),
        "width": width,
        "height": height,
        "fps": fps,
    })
print(json.dumps(results))
'''.replace("MAX_INDEXES", str(max_indexes))

    result = _run([sys.executable, "-c", probe_script], timeout=20)
    cameras: list[dict[str, Any]] = []
    issues: list[str] = []
    recommendations: list[str] = []

    if result["returncode"] == 0 and result["stdout"].strip():
        try:
            cameras = json.loads(result["stdout"])
        except Exception as exc:
            issues.append(f"Could not parse camera probe output: {exc}")
    else:
        issues.append(result["output"] or "Camera probe failed.")

    usable = [cam for cam in cameras if cam.get("opened") and cam.get("frame_read")]
    if not usable:
        recommendations.append("No usable camera frame detected yet. Check webcam connection/privacy permissions.")

    return {
        "opencv_available": True,
        "cameras": cameras,
        "usable_cameras": usable,
        "issues": issues,
        "recommendations": recommendations,
    }


def _safety_policy() -> dict[str, Any]:
    return {
        "allowed": [
            "Capture only on explicit command.",
            "Analyze still images.",
            "Use webcam only during active commanded sessions.",
            "Extract visible text.",
            "Classify visible document/object/scene type.",
            "Save captures and extracted text with reports.",
            "Hand off to Google Docs, Google Drive, Documents, and Files workflows.",
        ],
        "required": [
            "Webcam is off by default.",
            "Live vision must have explicit start command.",
            "Live vision must have stop command.",
            "Live session must have interval and max duration limits.",
            "Live session state must be recorded locally.",
            "Every saved frame/output must be reported.",
        ],
        "blocked": [
            "Silent camera use.",
            "Hidden/background watching.",
            "Always-on camera.",
            "Face identity recognition.",
            "Biometric recognition.",
            "Audio recording.",
            "Uploading captures without reporting.",
            "Deleting captures automatically.",
            "Running live vision after stop command.",
        ],
    }


class _OCRBaseTool(BaseTool):
    def _result(self, content: str, success: bool = True, metadata: dict[str, Any] | None = None) -> ToolResult:
        return ToolResult(
            tool_name=getattr(self, "tool_id", self.__class__.__name__),
            success=success,
            content=content,
            metadata=metadata or {},
        )


@ToolRegistry.register("serena_ocr_status")
class SerenaOCRStatusTool(_OCRBaseTool):
    tool_id = "serena_ocr_status"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Show Serena OCR / Live Vision operator status.",
            parameters={"type": "object", "properties": {}},
            category="serena_ocr",
        )

    def execute(self, **params: Any) -> ToolResult:
        root = _ocr_root()
        state = _load_live_state()
        engines = _engine_status()

        return self._result(
            "Serena OCR / Live Vision status\n\n"
            "- Status: active\n"
            "- Role: OCR, camera capture, controlled live vision, and document handoff operator\n"
            f"- Platform: {platform.platform()}\n"
            f"- Local OCR ready: {'yes' if engines['local_ocr_ready'] else 'no'}\n"
            f"- Webcam ready: {'yes' if engines['webcam_ready'] else 'no'}\n"
            f"- Live vision active: {'yes' if state.get('active') else 'no'}\n"
            "- Webcam default: closed/off\n"
            "- Silent camera use: blocked\n"
            "- Always-on camera: blocked\n"
            "- Face identity/biometric recognition: blocked\n"
            f"- Output root: {root}\n"
            f"- Captures: {root / 'captures'}\n"
            f"- Reports: {root / 'reports'}\n"
            f"- Extracted text: {root / 'extracted-text'}\n"
            f"- Live frames: {root / 'live' / 'frames'}",
            metadata={
                "output_root": str(root),
                "live_state": state,
                "local_ocr_ready": engines["local_ocr_ready"],
                "webcam_ready": engines["webcam_ready"],
            },
        )


@ToolRegistry.register("serena_ocr_engines")
class SerenaOCREnginesTool(_OCRBaseTool):
    tool_id = "serena_ocr_engines"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Inspect OCR, image, and camera engine availability.",
            parameters={"type": "object", "properties": {}},
            category="serena_ocr",
        )

    def execute(self, **params: Any) -> ToolResult:
        engines = _engine_status()
        env = _env_status()

        payload = {
            "report_type": "serena_ocr_engines",
            "created_at": _timestamp(),
            "engines": engines,
            "env": env,
            "changes_made": False,
            "secret_values_exposed": False,
        }
        report_path = _save_json("reports", "engines", payload)

        lines = [
            "Serena OCR / Vision engines",
            "",
            f"- Local OCR ready: {'yes' if engines['local_ocr_ready'] else 'no'}",
            f"- Webcam ready: {'yes' if engines['webcam_ready'] else 'no'}",
            f"- Report: {report_path}",
            "- Changes made: no",
            "- Secret values exposed: no",
            "",
            "Engine checks:",
        ]

        for name, result in engines["checks"].items():
            status = "ok" if result["returncode"] == 0 else "missing/warning"
            output = (result.get("output") or "").replace("\n", " ")[:180]
            lines.append(f"- {name}: {status} | {output}")

        lines.extend(["", "Optional environment integrations:"])
        for item in env["optional"]:
            lines.append(f"- {item['name']} | present={'yes' if item['present'] else 'no'} | length={item['length']}")

        lines.extend(["", "Recommendations:"])
        lines.extend(f"- {item}" for item in engines["recommendations"]) if engines["recommendations"] else lines.append("- No immediate recommendations.")

        return self._result("\n".join(lines), metadata={**payload, "report_path": str(report_path)})


@ToolRegistry.register("serena_ocr_camera_status")
class SerenaOCRCameraStatusTool(_OCRBaseTool):
    tool_id = "serena_ocr_camera_status"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Probe local cameras for explicit-use OCR/live vision workflows.",
            parameters={
                "type": "object",
                "properties": {
                    "max_indexes": {"type": "integer"},
                },
            },
            category="serena_ocr",
        )

    def execute(self, **params: Any) -> ToolResult:
        max_indexes = int(params.get("max_indexes") or 5)
        status = _camera_probe(max_indexes=max_indexes)

        payload = {
            "report_type": "serena_ocr_camera_status",
            "created_at": _timestamp(),
            "camera_status": status,
            "changes_made": False,
            "camera_open_after_check": False,
        }
        report_path = _save_json("reports", "camera-status", payload)

        lines = [
            "Serena OCR camera status",
            "",
            f"- OpenCV available: {'yes' if status['opencv_available'] else 'no'}",
            f"- Usable cameras: {len(status.get('usable_cameras', []))}",
            f"- Report: {report_path}",
            "- Changes made: no",
            "- Camera left open: no",
            "",
            "Cameras:",
        ]

        cameras = status.get("cameras") or []
        if cameras:
            for cam in cameras:
                lines.append(
                    f"- index={cam.get('index')} | opened={cam.get('opened')} | "
                    f"frame_read={cam.get('frame_read')} | "
                    f"{cam.get('width')}x{cam.get('height')} | fps={cam.get('fps')}"
                )
        else:
            lines.append("- none")

        lines.extend(["", "Issues:"])
        lines.extend(f"- {item}" for item in status.get("issues", [])) if status.get("issues") else lines.append("- none")

        lines.extend(["", "Recommendations:"])
        lines.extend(f"- {item}" for item in status.get("recommendations", [])) if status.get("recommendations") else lines.append("- No immediate recommendations.")

        return self._result("\n".join(lines), metadata={**payload, "report_path": str(report_path)})


@ToolRegistry.register("serena_ocr_plan")
class SerenaOCRPlanTool(_OCRBaseTool):
    tool_id = "serena_ocr_plan"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Create an OCR/live vision operation plan without using camera or OCR.",
            parameters={
                "type": "object",
                "properties": {
                    "goal": {"type": "string"},
                    "mode": {"type": "string"},
                    "source": {"type": "string"},
                },
                "required": ["goal"],
            },
            category="serena_ocr",
        )

    def execute(self, **params: Any) -> ToolResult:
        goal = str(params.get("goal") or "").strip()
        mode = str(params.get("mode") or "document").strip()
        source = str(params.get("source") or "").strip()
        engines = _engine_status()
        state = _load_live_state()

        plan = {
            "report_type": "serena_ocr_plan",
            "created_at": _timestamp(),
            "goal": goal,
            "mode": mode,
            "source": source,
            "local_ocr_ready": engines["local_ocr_ready"],
            "webcam_ready": engines["webcam_ready"],
            "live_vision_active": bool(state.get("active")),
            "steps": [
                "Check OCR/camera engine availability.",
                "Confirm explicit capture/live vision command.",
                "Capture or inspect source image/document.",
                "Assess readability and quality.",
                "Extract visible text if available.",
                "Classify document/object/scene type.",
                "Save capture and extracted text artifacts.",
                "Create local report.",
                "Hand off to Google Docs/Drive/Documents/Files only with reporting.",
            ],
            "camera_opened": False,
            "ocr_performed": False,
            "changes_made": False,
            "delete_performed": False,
        }

        plan_path = _save_json("reports", goal or mode or "ocr-plan", plan)

        return self._result(
            "Serena OCR / Live Vision operation plan\n\n"
            f"- Goal: {goal}\n"
            f"- Mode: {mode}\n"
            f"- Source: {source or 'not specified'}\n"
            f"- Local OCR ready: {'yes' if engines['local_ocr_ready'] else 'no'}\n"
            f"- Webcam ready: {'yes' if engines['webcam_ready'] else 'no'}\n"
            f"- Live vision active: {'yes' if state.get('active') else 'no'}\n"
            f"- Plan: {plan_path}\n"
            "- Camera opened: no\n"
            "- OCR performed: no\n"
            "- Changes made: no\n"
            "- Delete performed: no\n\n"
            "Steps:\n"
            + "\n".join(f"- {step}" for step in plan["steps"]),
            metadata={**plan, "plan_path": str(plan_path)},
        )


@ToolRegistry.register("serena_ocr_safety_policy")
class SerenaOCRSafetyPolicyTool(_OCRBaseTool):
    tool_id = "serena_ocr_safety_policy"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Show OCR/live vision webcam safety policy.",
            parameters={"type": "object", "properties": {}},
            category="serena_ocr",
        )

    def execute(self, **params: Any) -> ToolResult:
        policy = _safety_policy()
        payload = {
            "report_type": "serena_ocr_safety_policy",
            "created_at": _timestamp(),
            "policy": policy,
            "changes_made": False,
            "camera_opened": False,
        }
        report_path = _save_json("reports", "safety-policy", payload)

        lines = [
            "Serena OCR / Live Vision safety policy",
            "",
            "- Webcam default: closed/off",
            "- Silent camera use: blocked",
            "- Hidden/background watching: blocked",
            "- Always-on camera: blocked",
            "- Face identity/biometric recognition: blocked",
            "- Audio recording: blocked in OCR v1",
            f"- Report: {report_path}",
            "- Changes made: no",
            "- Camera opened: no",
            "",
            "Allowed:",
        ]

        lines.extend(f"- {item}" for item in policy["allowed"])
        lines.extend(["", "Required:"])
        lines.extend(f"- {item}" for item in policy["required"])
        lines.extend(["", "Blocked:"])
        lines.extend(f"- {item}" for item in policy["blocked"])

        return self._result("\n".join(lines), metadata={**payload, "report_path": str(report_path)})


__all__ = [
    "SerenaOCRStatusTool",
    "SerenaOCREnginesTool",
    "SerenaOCRCameraStatusTool",
    "SerenaOCRPlanTool",
    "SerenaOCRSafetyPolicyTool",
]
