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


def _resolve_executable(command: str) -> str | None:
    resolved = shutil.which(command)
    if resolved:
        return resolved

    common_paths = {
        "tesseract": [
            r"C:\Program Files\Tesseract-OCR\tesseract.exe",
            r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
            r"C:\Users\Kyle\AppData\Local\Programs\Tesseract-OCR\tesseract.exe",
        ],
        "ffmpeg": [
            r"C:\ffmpeg\bin\ffmpeg.exe",
            r"C:\Program Files\ffmpeg\bin\ffmpeg.exe",
            r"C:\Program Files\Gyan\FFmpeg\bin\ffmpeg.exe",
        ],
    }

    for candidate in common_paths.get(command.lower(), []):
        if Path(candidate).exists():
            return candidate

    return None


def _command_check(command: str, version_args: list[str] | None = None) -> dict[str, Any]:
    resolved = _resolve_executable(command)
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
        "camera_engine_ready": checks["opencv_cv2"]["returncode"] == 0,
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
            "usable_cameras": [],
            "issues": ["OpenCV/cv2 is not available."],
            "recommendations": ["Install OpenCV before testing webcam capture."],
        }

    probe_script = """
import cv2
import json

backends = [
    ("DSHOW", cv2.CAP_DSHOW),
    ("MSMF", cv2.CAP_MSMF),
    ("ANY", cv2.CAP_ANY),
]

results = []
for index in range(0, MAX_INDEXES):
    best = {
        "index": index,
        "backend": "",
        "opened": False,
        "frame_read": False,
        "width": 0,
        "height": 0,
        "fps": 0.0,
    }

    for backend_name, backend in backends:
        cap = cv2.VideoCapture(index, backend)
        opened = bool(cap.isOpened())
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
        fps = float(cap.get(cv2.CAP_PROP_FPS) or 0)
        ok = False

        if opened:
            ok, frame = cap.read()

        cap.release()

        candidate = {
            "index": index,
            "backend": backend_name,
            "opened": opened,
            "frame_read": bool(ok),
            "width": width,
            "height": height,
            "fps": fps,
        }

        if candidate["opened"] or candidate["frame_read"]:
            best = candidate

        if candidate["opened"] and candidate["frame_read"]:
            best = candidate
            break

    results.append(best)

print(json.dumps(results))
""".replace("MAX_INDEXES", str(max_indexes))

    result = _run([sys.executable, "-c", probe_script], timeout=30)
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
        recommendations.append("No usable camera frame detected yet. On Dr Piet's PC, plug in the webcam and allow Windows camera permissions.")
        recommendations.append("For plug-and-play setup, run: serena ocr camera-status --max-indexes 8 after connecting the webcam.")

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
            f"- Camera engine ready: {'yes' if engines.get('camera_engine_ready') else 'no'}\n"
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
                "camera_engine_ready": engines.get("camera_engine_ready"),
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
            f"- Camera engine ready: {'yes' if engines.get('camera_engine_ready') else 'no'}",
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
            "camera_engine_ready": engines.get("camera_engine_ready"),
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
            f"- Camera engine ready: {'yes' if engines.get('camera_engine_ready') else 'no'}\n"
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


def _safe_image_path(path_value: str) -> Path:
    path = Path(str(path_value or "")).expanduser()

    if not path.exists():
        raise RuntimeError(f"Image/PDF path does not exist: {path}")
    if not path.is_file():
        raise RuntimeError(f"Path is not a file: {path}")

    lowered = str(path).lower()
    blocked = [".env", "secret", "secrets", "credential", "credentials", "password", "token"]
    if any(item in lowered for item in blocked):
        raise RuntimeError(f"Refusing sensitive-looking path: {path}")

    allowed_suffixes = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff", ".pdf"}
    if path.suffix.lower() not in allowed_suffixes:
        raise RuntimeError(f"Unsupported OCR input type: {path.suffix}")

    return path


def _load_image_stats(path: Path) -> dict[str, Any]:
    from PIL import Image, ImageStat

    with Image.open(path) as img:
        image = img.convert("RGB")
        width, height = image.size
        gray = image.convert("L")
        stat = ImageStat.Stat(gray)
        mean_brightness = float(stat.mean[0])
        contrast = float(stat.stddev[0])

    megapixels = round((width * height) / 1_000_000, 3)

    readability_score = 0
    notes: list[str] = []

    long_edge = max(width, height)
    short_edge = min(width, height)

    if long_edge >= 1200 and short_edge >= 500:
        readability_score += 35
    elif long_edge >= 900 and short_edge >= 400:
        readability_score += 25
    elif long_edge >= 600 and short_edge >= 300:
        readability_score += 15
    else:
        notes.append("Image resolution may be low for OCR.")

    # Bright white paper backgrounds are expected for documents.
    if 70 <= mean_brightness <= 250:
        readability_score += 25
    elif mean_brightness > 250:
        readability_score += 15
        notes.append("Image is very bright; ensure text is dark and not washed out.")
    else:
        notes.append("Image may be too dark for OCR.")

    if contrast >= 30:
        readability_score += 30
    elif contrast >= 12:
        readability_score += 20
        notes.append("Contrast is usable but could be improved with darker/larger text.")
    elif contrast >= 6:
        readability_score += 10
        notes.append("Contrast is low; OCR may make mistakes.")
    else:
        notes.append("Contrast may be too low for reliable OCR.")

    if megapixels >= 0.5:
        readability_score += 10
    else:
        notes.append("Image is small; move closer or use a higher-resolution capture.")

    readability_score = min(readability_score, 100)

    if readability_score >= 80:
        label = "good"
    elif readability_score >= 55:
        label = "usable"
    else:
        label = "poor"

    return {
        "width": width,
        "height": height,
        "megapixels": megapixels,
        "mean_brightness": round(mean_brightness, 2),
        "contrast": round(contrast, 2),
        "readability_score": readability_score,
        "readability": label,
        "notes": notes,
    }


def _tesseract_cmd_path() -> str | None:
    return _resolve_executable("tesseract")


def _ocr_image_text(path: Path) -> dict[str, Any]:
    from PIL import Image, ImageFilter, ImageOps
    import pytesseract

    cmd = _tesseract_cmd_path()
    if cmd:
        pytesseract.pytesseract.tesseract_cmd = cmd

    with Image.open(path) as img:
        gray = ImageOps.grayscale(img)

        # Upscale smaller captures before OCR. This helps webcam/document photos and small test images.
        width, height = gray.size
        scale = 2 if max(width, height) < 2200 else 1
        if scale > 1:
            gray = gray.resize((width * scale, height * scale))

        # Light preprocessing: sharpen and binarize for dark text on light paper.
        gray = gray.filter(ImageFilter.SHARPEN)
        bw = gray.point(lambda pixel: 255 if pixel > 180 else 0)

        config = "--oem 3 --psm 6"
        text = pytesseract.image_to_string(bw, config=config)

    return {
        "text": text.strip(),
        "text_length": len(text.strip()),
        "engine": "pytesseract+tesseract+preprocess",
        "tesseract_cmd": cmd or "PATH",
    }


def _write_extracted_text(name: str, text: str) -> Path:
    folder = _ocr_root() / "extracted-text"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{_timestamp()}-{_safe_slug(name)}.txt"
    path.write_text(text or "", encoding="utf-8")
    return path


@ToolRegistry.register("serena_ocr_inspect_image")
class SerenaOCRInspectImageTool(_OCRBaseTool):
    tool_id = "serena_ocr_inspect_image"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Inspect an image/PDF input for OCR suitability.",
            parameters={
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
            category="serena_ocr",
        )

    def execute(self, **params: Any) -> ToolResult:
        try:
            path = _safe_image_path(str(params.get("path") or ""))

            if path.suffix.lower() == ".pdf":
                info = {
                    "path": str(path),
                    "suffix": path.suffix.lower(),
                    "size_bytes": path.stat().st_size,
                    "type": "pdf",
                    "readability": "requires page extraction",
                    "notes": ["Use extract-pdf for PDF OCR."],
                }
            else:
                stats = _load_image_stats(path)
                info = {
                    "path": str(path),
                    "suffix": path.suffix.lower(),
                    "size_bytes": path.stat().st_size,
                    "type": "image",
                    **stats,
                }

            payload = {
                "report_type": "serena_ocr_inspect_image",
                "created_at": _timestamp(),
                "input": info,
                "changes_made": False,
                "ocr_performed": False,
                "delete_performed": False,
            }
            report_path = _save_json("reports", f"inspect-{path.name}", payload)

            lines = [
                "Serena OCR input inspection",
                "",
                f"- Path: {path}",
                f"- Type: {info['type']}",
                f"- Size bytes: {info['size_bytes']}",
                f"- Report: {report_path}",
                "- OCR performed: no",
                "- Changes made: no",
                "- Delete performed: no",
            ]

            if info["type"] == "image":
                lines.extend([
                    f"- Dimensions: {info['width']}x{info['height']}",
                    f"- Brightness: {info['mean_brightness']}",
                    f"- Contrast: {info['contrast']}",
                    f"- Readability: {info['readability']} ({info['readability_score']}/100)",
                    "",
                    "Notes:",
                ])
                lines.extend(f"- {item}" for item in info["notes"]) if info["notes"] else lines.append("- No immediate readability warnings.")
            else:
                lines.extend(["", "Notes:"])
                lines.extend(f"- {item}" for item in info["notes"])

            return self._result("\n".join(lines), metadata={**payload, "report_path": str(report_path)})
        except Exception as exc:
            return self._result(f"Failed to inspect OCR input: {exc}", success=False)


@ToolRegistry.register("serena_ocr_readability")
class SerenaOCRReadabilityTool(_OCRBaseTool):
    tool_id = "serena_ocr_readability"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Assess image readability for OCR.",
            parameters={
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
            category="serena_ocr",
        )

    def execute(self, **params: Any) -> ToolResult:
        try:
            path = _safe_image_path(str(params.get("path") or ""))
            if path.suffix.lower() == ".pdf":
                return self._result("Readability currently expects an image file. Use extract-pdf for PDFs.", success=False)

            stats = _load_image_stats(path)

            payload = {
                "report_type": "serena_ocr_readability",
                "created_at": _timestamp(),
                "path": str(path),
                "stats": stats,
                "changes_made": False,
                "delete_performed": False,
            }
            report_path = _save_json("reports", f"readability-{path.name}", payload)

            return self._result(
                "Serena OCR readability\n\n"
                f"- Path: {path}\n"
                f"- Dimensions: {stats['width']}x{stats['height']}\n"
                f"- Brightness: {stats['mean_brightness']}\n"
                f"- Contrast: {stats['contrast']}\n"
                f"- Readability: {stats['readability']} ({stats['readability_score']}/100)\n"
                f"- Report: {report_path}\n"
                "- Changes made: no\n"
                "- Delete performed: no\n\n"
                "Recommendations:\n"
                + ("\n".join(f"- {item}" for item in stats["notes"]) if stats["notes"] else "- Image appears suitable for OCR."),
                metadata={**payload, "report_path": str(report_path)},
            )
        except Exception as exc:
            return self._result(f"Failed to assess OCR readability: {exc}", success=False)


@ToolRegistry.register("serena_ocr_extract_image")
class SerenaOCRExtractImageTool(_OCRBaseTool):
    tool_id = "serena_ocr_extract_image"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Extract visible text from an image using local OCR.",
            parameters={
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
            category="serena_ocr",
        )

    def execute(self, **params: Any) -> ToolResult:
        try:
            path = _safe_image_path(str(params.get("path") or ""))
            if path.suffix.lower() == ".pdf":
                return self._result("extract-image expects an image file. Use extract-pdf for PDFs.", success=False)

            stats = _load_image_stats(path)
            ocr = _ocr_image_text(path)
            text_path = _write_extracted_text(path.stem, ocr["text"])

            payload = {
                "report_type": "serena_ocr_extract_image",
                "created_at": _timestamp(),
                "path": str(path),
                "readability": stats,
                "ocr": {
                    "text_length": ocr["text_length"],
                    "engine": ocr["engine"],
                    "tesseract_cmd_present": bool(ocr["tesseract_cmd"]),
                },
                "text_path": str(text_path),
                "changes_made": True,
                "ocr_performed": True,
                "delete_performed": False,
            }
            report_path = _save_json("reports", f"extract-image-{path.name}", payload)

            preview = ocr["text"][:2000] if ocr["text"] else ""

            return self._result(
                "Serena OCR image extraction complete\n\n"
                f"- Path: {path}\n"
                f"- Readability: {stats['readability']} ({stats['readability_score']}/100)\n"
                f"- Text length: {ocr['text_length']}\n"
                f"- Extracted text file: {text_path}\n"
                f"- Report: {report_path}\n"
                "- OCR performed: yes\n"
                "- Changes made: yes\n"
                "- Delete performed: no\n\n"
                "Preview:\n"
                f"{preview or '[no text detected]'}",
                metadata={**payload, "report_path": str(report_path), "preview": preview},
            )
        except Exception as exc:
            return self._result(f"Failed to extract OCR text from image: {exc}", success=False)


@ToolRegistry.register("serena_ocr_extract_pdf")
class SerenaOCRExtractPDFTool(_OCRBaseTool):
    tool_id = "serena_ocr_extract_pdf"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Extract text from a PDF using PyMuPDF text extraction first, with OCR page rendering later.",
            parameters={
                "type": "object",
                "properties": {"path": {"type": "string"}, "max_pages": {"type": "integer"}},
                "required": ["path"],
            },
            category="serena_ocr",
        )

    def execute(self, **params: Any) -> ToolResult:
        try:
            import fitz

            path = _safe_image_path(str(params.get("path") or ""))
            max_pages = int(params.get("max_pages") or 10)

            if path.suffix.lower() != ".pdf":
                return self._result("extract-pdf expects a PDF file.", success=False)

            doc = fitz.open(str(path))
            pages = min(len(doc), max_pages)
            text_parts: list[str] = []

            for i in range(pages):
                page = doc[i]
                text_parts.append(f"\n\n--- Page {i + 1} ---\n")
                text_parts.append(page.get_text("text") or "")

            doc.close()

            text = "".join(text_parts).strip()
            text_path = _write_extracted_text(path.stem, text)

            payload = {
                "report_type": "serena_ocr_extract_pdf",
                "created_at": _timestamp(),
                "path": str(path),
                "pages_total": len(doc) if False else pages,
                "pages_processed": pages,
                "text_length": len(text),
                "text_path": str(text_path),
                "engine": "pymupdf_text_extraction",
                "changes_made": True,
                "ocr_performed": False,
                "pdf_text_extraction_performed": True,
                "delete_performed": False,
            }
            report_path = _save_json("reports", f"extract-pdf-{path.name}", payload)

            preview = text[:2000] if text else ""

            return self._result(
                "Serena PDF text extraction complete\n\n"
                f"- Path: {path}\n"
                f"- Pages processed: {pages}\n"
                f"- Text length: {len(text)}\n"
                f"- Extracted text file: {text_path}\n"
                f"- Report: {report_path}\n"
                "- PDF text extraction performed: yes\n"
                "- Image OCR performed: no\n"
                "- Changes made: yes\n"
                "- Delete performed: no\n\n"
                "Preview:\n"
                f"{preview or '[no embedded text detected]'}",
                metadata={**payload, "report_path": str(report_path), "preview": preview},
            )
        except Exception as exc:
            return self._result(f"Failed to extract text from PDF: {exc}", success=False)


def _capture_frame(camera_index: int = 0, name: str = "capture", warmup_frames: int = 5) -> dict[str, Any]:
    cv2_check = _module_check("cv2")
    if cv2_check["returncode"] != 0:
        raise RuntimeError("OpenCV/cv2 is not available. Cannot capture webcam frame.")

    output_path = _ocr_root() / "captures" / f"{_timestamp()}-{_safe_slug(name)}.jpg"

    probe_code = (
        "import cv2\n"
        "import json\n"
        "import sys\n"
        "from pathlib import Path\n"
        f"camera_index = {int(camera_index)}\n"
        f"output_path = {str(output_path)!r}\n"
        f"warmup_frames = {int(warmup_frames)}\n"
        "backends = [('DSHOW', cv2.CAP_DSHOW), ('MSMF', cv2.CAP_MSMF), ('ANY', cv2.CAP_ANY)]\n"
        "last_error = ''\n"
        "for backend_name, backend in backends:\n"
        "    cap = cv2.VideoCapture(camera_index, backend)\n"
        "    opened = bool(cap.isOpened())\n"
        "    if not opened:\n"
        "        cap.release()\n"
        "        last_error = f'camera {camera_index} could not open with backend {backend_name}'\n"
        "        continue\n"
        "    frame = None\n"
        "    ok = False\n"
        "    for _ in range(max(warmup_frames, 1)):\n"
        "        ok, frame = cap.read()\n"
        "    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)\n"
        "    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)\n"
        "    fps = float(cap.get(cv2.CAP_PROP_FPS) or 0)\n"
        "    cap.release()\n"
        "    if ok and frame is not None:\n"
        "        Path(output_path).parent.mkdir(parents=True, exist_ok=True)\n"
        "        saved = cv2.imwrite(output_path, frame)\n"
        "        print(json.dumps({'success': bool(saved), 'camera_index': camera_index, 'backend': backend_name, 'output_path': output_path, 'width': width, 'height': height, 'fps': fps, 'camera_released': True}))\n"
        "        sys.exit(0)\n"
        "    last_error = f'camera {camera_index} opened with {backend_name}, but no frame was read'\n"
        "print(json.dumps({'success': False, 'camera_index': camera_index, 'output_path': output_path, 'error': last_error or 'No usable camera frame detected.', 'camera_released': True}))\n"
        "sys.exit(2)\n"
    )

    result = _run([sys.executable, "-c", probe_code], timeout=30)

    try:
        parsed = json.loads((result.get("stdout") or "").strip())
    except Exception:
        parsed = {
            "success": False,
            "camera_index": camera_index,
            "output_path": str(output_path),
            "error": result.get("output") or "Camera capture failed.",
            "camera_released": True,
        }

    if not parsed.get("success"):
        raise RuntimeError(parsed.get("error") or "Camera capture failed.")

    return parsed


def _describe_capture(path: Path) -> dict[str, Any]:
    stats = _load_image_stats(path)
    description_parts: list[str] = []

    if stats["readability"] == "good":
        description_parts.append("The capture appears suitable for OCR.")
    elif stats["readability"] == "usable":
        description_parts.append("The capture may be usable for OCR, but quality could improve.")
    else:
        description_parts.append("The capture quality may be poor for OCR.")

    if stats["mean_brightness"] > 250:
        description_parts.append("The frame is very bright; check for glare or washed-out text.")
    elif stats["mean_brightness"] < 70:
        description_parts.append("The frame may be too dark.")

    if stats["contrast"] < 12:
        description_parts.append("The frame has low contrast; darker text or better lighting may help.")

    if max(stats["width"], stats["height"]) < 900:
        description_parts.append("The frame resolution is low; move closer or use a higher camera resolution.")

    return {
        "path": str(path),
        "stats": stats,
        "description": " ".join(description_parts),
    }


@ToolRegistry.register("serena_ocr_cameras")
class SerenaOCRCamerasTool(_OCRBaseTool):
    tool_id = "serena_ocr_cameras"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="List usable cameras for OCR/live vision.",
            parameters={
                "type": "object",
                "properties": {
                    "max_indexes": {"type": "integer"},
                },
            },
            category="serena_ocr",
        )

    def execute(self, **params: Any) -> ToolResult:
        max_indexes = int(params.get("max_indexes") or 8)
        status = _camera_probe(max_indexes=max_indexes)

        payload = {
            "report_type": "serena_ocr_cameras",
            "created_at": _timestamp(),
            "camera_status": status,
            "changes_made": False,
            "camera_left_open": False,
        }
        report_path = _save_json("reports", "cameras", payload)

        lines = [
            "Serena OCR cameras",
            "",
            f"- OpenCV available: {'yes' if status.get('opencv_available') else 'no'}",
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
                    f"- index={cam.get('index')} | backend={cam.get('backend', '')} | "
                    f"opened={cam.get('opened')} | frame_read={cam.get('frame_read')} | "
                    f"{cam.get('width')}x{cam.get('height')} | fps={cam.get('fps')}"
                )
        else:
            lines.append("- none")

        lines.extend(["", "Recommendations:"])
        lines.extend(f"- {item}" for item in status.get("recommendations", [])) if status.get("recommendations") else lines.append("- No immediate recommendations.")

        return self._result("\n".join(lines), metadata={**payload, "report_path": str(report_path)})


@ToolRegistry.register("serena_ocr_capture")
class SerenaOCRCaptureTool(_OCRBaseTool):
    tool_id = "serena_ocr_capture"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Capture one explicit webcam frame and save it locally.",
            parameters={
                "type": "object",
                "properties": {
                    "camera_index": {"type": "integer"},
                    "name": {"type": "string"},
                },
            },
            category="serena_ocr",
        )

    def execute(self, **params: Any) -> ToolResult:
        camera_index = int(params.get("camera_index") or 0)
        name = str(params.get("name") or "webcam-capture").strip()

        try:
            capture = _capture_frame(camera_index=camera_index, name=name)
            path = Path(capture["output_path"])
            desc = _describe_capture(path)

            payload = {
                "report_type": "serena_ocr_capture",
                "created_at": _timestamp(),
                "capture": capture,
                "description": desc,
                "camera_opened_by_command": True,
                "camera_released": True,
                "changes_made": True,
                "delete_performed": False,
            }
            report_path = _save_json("reports", f"capture-{name}", payload)

            return self._result(
                "Serena OCR webcam capture complete\n\n"
                f"- Camera index: {camera_index}\n"
                f"- Backend: {capture.get('backend')}\n"
                f"- Capture file: {path}\n"
                f"- Dimensions: {desc['stats']['width']}x{desc['stats']['height']}\n"
                f"- Readability: {desc['stats']['readability']} ({desc['stats']['readability_score']}/100)\n"
                f"- Report: {report_path}\n"
                "- Camera opened by explicit command: yes\n"
                "- Camera released: yes\n"
                "- Changes made: yes\n"
                "- Delete performed: no\n\n"
                "Description:\n"
                f"{desc['description']}",
                metadata={**payload, "report_path": str(report_path)},
            )
        except Exception as exc:
            payload = {
                "report_type": "serena_ocr_capture_failed",
                "created_at": _timestamp(),
                "camera_index": camera_index,
                "error": str(exc),
                "camera_released": True,
                "changes_made": False,
                "delete_performed": False,
            }
            report_path = _save_json("reports", f"capture-failed-{name}", payload)

            return self._result(
                "Serena OCR webcam capture failed safely\n\n"
                f"- Camera index: {camera_index}\n"
                f"- Error: {exc}\n"
                f"- Report: {report_path}\n"
                "- Camera released: yes\n"
                "- Changes made: no\n"
                "- Delete performed: no\n\n"
                "Plug-and-play note:\n"
                "- On Dr Piet's PC, plug in the webcam, allow Windows camera permissions, then run `serena ocr cameras --max-indexes 8`.",
                success=False,
                metadata={**payload, "report_path": str(report_path)},
            )


@ToolRegistry.register("serena_ocr_capture_doc")
class SerenaOCRCaptureDocTool(_OCRBaseTool):
    tool_id = "serena_ocr_capture_doc"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Capture one webcam frame intended as a document and attempt OCR extraction.",
            parameters={
                "type": "object",
                "properties": {
                    "camera_index": {"type": "integer"},
                    "name": {"type": "string"},
                },
            },
            category="serena_ocr",
        )

    def execute(self, **params: Any) -> ToolResult:
        camera_index = int(params.get("camera_index") or 0)
        name = str(params.get("name") or "webcam-document").strip()

        try:
            capture = _capture_frame(camera_index=camera_index, name=name)
            path = Path(capture["output_path"])
            desc = _describe_capture(path)
            ocr = _ocr_image_text(path)
            text_path = _write_extracted_text(path.stem, ocr["text"])

            payload = {
                "report_type": "serena_ocr_capture_doc",
                "created_at": _timestamp(),
                "capture": capture,
                "description": desc,
                "ocr": {
                    "text_length": ocr["text_length"],
                    "engine": ocr["engine"],
                },
                "text_path": str(text_path),
                "camera_opened_by_command": True,
                "camera_released": True,
                "ocr_performed": True,
                "changes_made": True,
                "delete_performed": False,
            }
            report_path = _save_json("reports", f"capture-doc-{name}", payload)

            preview = ocr["text"][:2000] if ocr["text"] else ""

            return self._result(
                "Serena OCR document capture complete\n\n"
                f"- Camera index: {camera_index}\n"
                f"- Backend: {capture.get('backend')}\n"
                f"- Capture file: {path}\n"
                f"- Readability: {desc['stats']['readability']} ({desc['stats']['readability_score']}/100)\n"
                f"- Text length: {ocr['text_length']}\n"
                f"- Extracted text file: {text_path}\n"
                f"- Report: {report_path}\n"
                "- Camera opened by explicit command: yes\n"
                "- Camera released: yes\n"
                "- OCR performed: yes\n"
                "- Changes made: yes\n"
                "- Delete performed: no\n\n"
                "Preview:\n"
                f"{preview or '[no text detected]'}",
                metadata={**payload, "report_path": str(report_path), "preview": preview},
            )
        except Exception as exc:
            payload = {
                "report_type": "serena_ocr_capture_doc_failed",
                "created_at": _timestamp(),
                "camera_index": camera_index,
                "error": str(exc),
                "camera_released": True,
                "ocr_performed": False,
                "changes_made": False,
                "delete_performed": False,
            }
            report_path = _save_json("reports", f"capture-doc-failed-{name}", payload)

            return self._result(
                "Serena OCR document capture failed safely\n\n"
                f"- Camera index: {camera_index}\n"
                f"- Error: {exc}\n"
                f"- Report: {report_path}\n"
                "- Camera released: yes\n"
                "- OCR performed: no\n"
                "- Changes made: no\n"
                "- Delete performed: no\n\n"
                "Plug-and-play note:\n"
                "- On Dr Piet's PC, plug in the webcam, allow Windows camera permissions, then run `serena ocr capture-doc --camera-index 0`.",
                success=False,
                metadata={**payload, "report_path": str(report_path)},
            )


@ToolRegistry.register("serena_ocr_describe_capture")
class SerenaOCRDescribeCaptureTool(_OCRBaseTool):
    tool_id = "serena_ocr_describe_capture"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Describe a saved capture/image for OCR suitability.",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                },
                "required": ["path"],
            },
            category="serena_ocr",
        )

    def execute(self, **params: Any) -> ToolResult:
        try:
            path = _safe_image_path(str(params.get("path") or ""))
            if path.suffix.lower() == ".pdf":
                return self._result("describe-capture expects an image file, not a PDF.", success=False)

            desc = _describe_capture(path)

            payload = {
                "report_type": "serena_ocr_describe_capture",
                "created_at": _timestamp(),
                "path": str(path),
                "description": desc,
                "changes_made": False,
                "delete_performed": False,
            }
            report_path = _save_json("reports", f"describe-capture-{path.name}", payload)

            stats = desc["stats"]

            return self._result(
                "Serena OCR capture description\n\n"
                f"- Path: {path}\n"
                f"- Dimensions: {stats['width']}x{stats['height']}\n"
                f"- Brightness: {stats['mean_brightness']}\n"
                f"- Contrast: {stats['contrast']}\n"
                f"- Readability: {stats['readability']} ({stats['readability_score']}/100)\n"
                f"- Report: {report_path}\n"
                "- Changes made: no\n"
                "- Delete performed: no\n\n"
                "Description:\n"
                f"{desc['description']}",
                metadata={**payload, "report_path": str(report_path)},
            )
        except Exception as exc:
            return self._result(f"Failed to describe capture: {exc}", success=False)


def _live_session_expired(state: dict[str, Any]) -> bool:
    if not state.get("active"):
        return False

    started_at_epoch = float(state.get("started_at_epoch") or 0)
    max_minutes = float(state.get("max_minutes") or 0)

    if started_at_epoch <= 0 or max_minutes <= 0:
        return False

    return (time.time() - started_at_epoch) >= (max_minutes * 60)


def _normalize_live_mode(mode: str) -> str:
    mode = str(mode or "assist").strip().lower()
    allowed = {"document", "text", "scene", "object", "assist"}
    if mode not in allowed:
        raise RuntimeError(f"Unsupported live vision mode: {mode}. Allowed: {', '.join(sorted(allowed))}")
    return mode


def _active_live_state_or_error() -> dict[str, Any]:
    state = _load_live_state()
    if not state.get("active"):
        raise RuntimeError("No active OCR live vision session. Start one with `serena ocr live-start`.")

    if _live_session_expired(state):
        state["active"] = False
        state["stop_requested"] = True
        state["stopped_at"] = _timestamp()
        state["stop_reason"] = "auto-stop: max duration reached"
        _save_live_state(state)
        raise RuntimeError("Live vision session has expired and was auto-stopped.")

    return state


def _live_summary(state: dict[str, Any]) -> str:
    artifacts = state.get("artifacts") or []
    return (
        f"mode={state.get('mode')}, "
        f"camera_index={state.get('camera_index')}, "
        f"active={state.get('active')}, "
        f"frames_captured={state.get('frames_captured', 0)}, "
        f"frames_saved={state.get('frames_saved', 0)}, "
        f"artifacts={len(artifacts)}"
    )


@ToolRegistry.register("serena_ocr_live_start")
class SerenaOCRLiveStartTool(_OCRBaseTool):
    tool_id = "serena_ocr_live_start"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Start a controlled OCR/live vision session. Does not continuously watch in background.",
            parameters={
                "type": "object",
                "properties": {
                    "mode": {"type": "string"},
                    "camera_index": {"type": "integer"},
                    "interval_seconds": {"type": "integer"},
                    "max_minutes": {"type": "integer"},
                    "approved": {"type": "boolean"},
                },
            },
            category="serena_ocr",
        )

    def execute(self, **params: Any) -> ToolResult:
        try:
            approved = bool(params.get("approved") or False)
            if not approved:
                return self._result(
                    "OCR live vision start blocked\n\n"
                    "- Reason: explicit approval flag is required.\n"
                    "- Required: --approved\n"
                    "- Camera opened: no\n"
                    "- Live vision active: no\n"
                    "- Changes made: no\n\n"
                    "Safety rule:\n"
                    "- Live vision can only start from an explicit approved command.",
                    success=False,
                )

            mode = _normalize_live_mode(str(params.get("mode") or "assist"))
            camera_index = int(params.get("camera_index") or 0)
            interval_seconds = int(params.get("interval_seconds") or 5)
            max_minutes = int(params.get("max_minutes") or 10)

            if interval_seconds < 2:
                return self._result("Live vision interval must be at least 2 seconds.", success=False)
            if max_minutes < 1 or max_minutes > 60:
                return self._result("Live vision max_minutes must be between 1 and 60.", success=False)

            existing = _load_live_state()
            if existing.get("active") and not _live_session_expired(existing):
                return self._result(
                    "OCR live vision session already active\n\n"
                    f"- Current session: {_live_summary(existing)}\n"
                    "- Camera opened: no\n"
                    "- Changes made: no\n\n"
                    "Use `serena ocr live-status` or `serena ocr live-stop`.",
                    success=False,
                    metadata={"live_state": existing},
                )

            state = {
                "active": True,
                "mode": mode,
                "camera_index": camera_index,
                "interval_seconds": interval_seconds,
                "max_minutes": max_minutes,
                "started_at": _timestamp(),
                "started_at_epoch": time.time(),
                "stopped_at": "",
                "stop_requested": False,
                "stop_reason": "",
                "frames_captured": 0,
                "frames_saved": 0,
                "last_frame": "",
                "last_snapshot_report": "",
                "artifacts": [],
                "policy": {
                    "explicit_command": True,
                    "approved": True,
                    "silent_camera_use": False,
                    "always_on_camera": False,
                    "audio_recording": False,
                    "face_identity_recognition": False,
                    "biometric_recognition": False,
                },
            }

            state_path = _save_live_state(state)

            payload = {
                "report_type": "serena_ocr_live_start",
                "created_at": _timestamp(),
                "state": state,
                "state_path": str(state_path),
                "camera_opened": False,
                "background_watch_started": False,
                "changes_made": True,
                "delete_performed": False,
            }
            report_path = _save_json("reports", "live-start", payload)

            return self._result(
                "Serena OCR live vision session started\n\n"
                f"- Mode: {mode}\n"
                f"- Camera index: {camera_index}\n"
                f"- Interval seconds: {interval_seconds}\n"
                f"- Max minutes: {max_minutes}\n"
                f"- State: {state_path}\n"
                f"- Report: {report_path}\n"
                "- Explicit approval: yes\n"
                "- Camera opened now: no\n"
                "- Background watch started: no\n"
                "- Live vision active: yes\n"
                "- Changes made: yes\n"
                "- Delete performed: no\n\n"
                "Important:\n"
                "- v1 live-start creates controlled session state.\n"
                "- Frames are captured only when `live-snapshot` or future watch commands run.",
                metadata={**payload, "report_path": str(report_path)},
            )
        except Exception as exc:
            return self._result(f"Failed to start OCR live vision session: {exc}", success=False)


@ToolRegistry.register("serena_ocr_live_status")
class SerenaOCRLiveStatusTool(_OCRBaseTool):
    tool_id = "serena_ocr_live_status"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Show OCR/live vision session status.",
            parameters={"type": "object", "properties": {}},
            category="serena_ocr",
        )

    def execute(self, **params: Any) -> ToolResult:
        state = _load_live_state()

        if state.get("active") and _live_session_expired(state):
            state["active"] = False
            state["stop_requested"] = True
            state["stopped_at"] = _timestamp()
            state["stop_reason"] = "auto-stop: max duration reached"
            _save_live_state(state)

        payload = {
            "report_type": "serena_ocr_live_status",
            "created_at": _timestamp(),
            "state": state,
            "changes_made": False,
            "camera_opened": False,
            "delete_performed": False,
        }
        report_path = _save_json("reports", "live-status", payload)

        return self._result(
            "Serena OCR live vision status\n\n"
            f"- Active: {'yes' if state.get('active') else 'no'}\n"
            f"- Mode: {state.get('mode') or 'none'}\n"
            f"- Camera index: {state.get('camera_index')}\n"
            f"- Interval seconds: {state.get('interval_seconds')}\n"
            f"- Max minutes: {state.get('max_minutes')}\n"
            f"- Started at: {state.get('started_at') or 'not started'}\n"
            f"- Stopped at: {state.get('stopped_at') or 'not stopped'}\n"
            f"- Stop reason: {state.get('stop_reason') or 'none'}\n"
            f"- Frames captured: {state.get('frames_captured', 0)}\n"
            f"- Frames saved: {state.get('frames_saved', 0)}\n"
            f"- Last frame: {state.get('last_frame') or 'none'}\n"
            f"- Report: {report_path}\n"
            "- Camera opened by status: no\n"
            "- Changes made: no\n"
            "- Delete performed: no",
            metadata={**payload, "report_path": str(report_path)},
        )


@ToolRegistry.register("serena_ocr_live_stop")
class SerenaOCRLiveStopTool(_OCRBaseTool):
    tool_id = "serena_ocr_live_stop"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Stop a controlled OCR/live vision session.",
            parameters={
                "type": "object",
                "properties": {
                    "reason": {"type": "string"},
                },
            },
            category="serena_ocr",
        )

    def execute(self, **params: Any) -> ToolResult:
        reason = str(params.get("reason") or "Stopped by explicit command.").strip()
        state = _load_live_state()
        was_active = bool(state.get("active"))

        state["active"] = False
        state["stop_requested"] = True
        state["stopped_at"] = _timestamp()
        state["stop_reason"] = reason
        state_path = _save_live_state(state)

        payload = {
            "report_type": "serena_ocr_live_stop",
            "created_at": _timestamp(),
            "was_active": was_active,
            "state": state,
            "state_path": str(state_path),
            "camera_released": True,
            "changes_made": True,
            "delete_performed": False,
        }
        report_path = _save_json("reports", "live-stop", payload)

        return self._result(
            "Serena OCR live vision session stopped\n\n"
            f"- Was active: {'yes' if was_active else 'no'}\n"
            f"- Reason: {reason}\n"
            f"- Frames captured: {state.get('frames_captured', 0)}\n"
            f"- Frames saved: {state.get('frames_saved', 0)}\n"
            f"- State: {state_path}\n"
            f"- Report: {report_path}\n"
            "- Camera released: yes\n"
            "- Live vision active: no\n"
            "- Changes made: yes\n"
            "- Delete performed: no",
            metadata={**payload, "report_path": str(report_path)},
        )


@ToolRegistry.register("serena_ocr_live_snapshot")
class SerenaOCRLiveSnapshotTool(_OCRBaseTool):
    tool_id = "serena_ocr_live_snapshot"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Capture one frame during an active OCR/live vision session.",
            parameters={
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "extract_text": {"type": "boolean"},
                },
            },
            category="serena_ocr",
        )

    def execute(self, **params: Any) -> ToolResult:
        try:
            state = _active_live_state_or_error()
            name = str(params.get("name") or f"live-{state.get('mode')}-snapshot").strip()
            extract_text = bool(params.get("extract_text") or False)

            capture = _capture_frame(camera_index=int(state.get("camera_index") or 0), name=name)
            path = Path(capture["output_path"])
            desc = _describe_capture(path)

            artifact: dict[str, Any] = {
                "type": "live_snapshot",
                "path": str(path),
                "created_at": _timestamp(),
                "camera_index": state.get("camera_index"),
                "mode": state.get("mode"),
                "readability": desc["stats"]["readability"],
                "readability_score": desc["stats"]["readability_score"],
            }

            preview = ""
            text_path = ""
            if extract_text:
                ocr = _ocr_image_text(path)
                text_path_obj = _write_extracted_text(path.stem, ocr["text"])
                text_path = str(text_path_obj)
                preview = ocr["text"][:2000] if ocr["text"] else ""
                artifact["ocr"] = {
                    "performed": True,
                    "text_length": ocr["text_length"],
                    "text_path": text_path,
                }
            else:
                artifact["ocr"] = {"performed": False}

            state["frames_captured"] = int(state.get("frames_captured") or 0) + 1
            state["frames_saved"] = int(state.get("frames_saved") or 0) + 1
            state["last_frame"] = str(path)
            state.setdefault("artifacts", []).append(artifact)
            state_path = _save_live_state(state)

            payload = {
                "report_type": "serena_ocr_live_snapshot",
                "created_at": _timestamp(),
                "state": state,
                "capture": capture,
                "description": desc,
                "artifact": artifact,
                "text_path": text_path,
                "camera_opened_by_command": True,
                "camera_released": True,
                "changes_made": True,
                "delete_performed": False,
            }
            report_path = _save_json("reports", f"live-snapshot-{name}", payload)

            state["last_snapshot_report"] = str(report_path)
            _save_live_state(state)

            return self._result(
                "Serena OCR live snapshot complete\n\n"
                f"- Mode: {state.get('mode')}\n"
                f"- Camera index: {state.get('camera_index')}\n"
                f"- Capture file: {path}\n"
                f"- Readability: {desc['stats']['readability']} ({desc['stats']['readability_score']}/100)\n"
                f"- Extract text: {'yes' if extract_text else 'no'}\n"
                f"- Extracted text file: {text_path or 'none'}\n"
                f"- State: {state_path}\n"
                f"- Report: {report_path}\n"
                "- Camera opened by explicit command: yes\n"
                "- Camera released: yes\n"
                "- Changes made: yes\n"
                "- Delete performed: no\n\n"
                "Preview:\n"
                f"{preview or '[no text extracted]'}",
                metadata={**payload, "report_path": str(report_path), "preview": preview},
            )
        except Exception as exc:
            payload = {
                "report_type": "serena_ocr_live_snapshot_failed",
                "created_at": _timestamp(),
                "error": str(exc),
                "camera_released": True,
                "changes_made": False,
                "delete_performed": False,
            }
            report_path = _save_json("reports", "live-snapshot-failed", payload)
            return self._result(
                "Serena OCR live snapshot failed safely\n\n"
                f"- Error: {exc}\n"
                f"- Report: {report_path}\n"
                "- Camera released: yes\n"
                "- Changes made: no\n"
                "- Delete performed: no",
                success=False,
                metadata={**payload, "report_path": str(report_path)},
            )


@ToolRegistry.register("serena_ocr_live_report")
class SerenaOCRLiveReportTool(_OCRBaseTool):
    tool_id = "serena_ocr_live_report"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Create a report for the current or most recent OCR/live vision session.",
            parameters={"type": "object", "properties": {}},
            category="serena_ocr",
        )

    def execute(self, **params: Any) -> ToolResult:
        state = _load_live_state()

        payload = {
            "report_type": "serena_ocr_live_report",
            "created_at": _timestamp(),
            "state": state,
            "summary": _live_summary(state),
            "changes_made": False,
            "camera_opened": False,
            "delete_performed": False,
        }
        report_path = _save_json("reports", "live-report", payload)

        artifacts = state.get("artifacts") or []

        lines = [
            "Serena OCR live vision report",
            "",
            f"- Active: {'yes' if state.get('active') else 'no'}",
            f"- Mode: {state.get('mode') or 'none'}",
            f"- Camera index: {state.get('camera_index')}",
            f"- Started at: {state.get('started_at') or 'not started'}",
            f"- Stopped at: {state.get('stopped_at') or 'not stopped'}",
            f"- Stop reason: {state.get('stop_reason') or 'none'}",
            f"- Frames captured: {state.get('frames_captured', 0)}",
            f"- Frames saved: {state.get('frames_saved', 0)}",
            f"- Artifacts: {len(artifacts)}",
            f"- Report: {report_path}",
            "- Camera opened by report: no",
            "- Changes made: no",
            "- Delete performed: no",
            "",
            "Artifacts:",
        ]

        if artifacts:
            for artifact in artifacts[-20:]:
                lines.append(
                    f"- {artifact.get('type')} | path={artifact.get('path')} | "
                    f"readability={artifact.get('readability')} ({artifact.get('readability_score')})"
                )
        else:
            lines.append("- none")

        return self._result("\n".join(lines), metadata={**payload, "report_path": str(report_path)})


__all__ = [
    "SerenaOCRStatusTool",
    "SerenaOCREnginesTool",
    "SerenaOCRCameraStatusTool",
    "SerenaOCRPlanTool",
    "SerenaOCRSafetyPolicyTool",
    "SerenaOCRExtractPDFTool",
    "SerenaOCRDescribeCaptureTool",
    "SerenaOCRLiveReportTool",
    "SerenaOCRLiveSnapshotTool",
    "SerenaOCRLiveStopTool",
    "SerenaOCRLiveStatusTool",
    "SerenaOCRLiveStartTool",
    "SerenaOCRCaptureDocTool",
    "SerenaOCRCaptureTool",
    "SerenaOCRCamerasTool",
    "SerenaOCRExtractImageTool",
    "SerenaOCRReadabilityTool",
    "SerenaOCRInspectImageTool",
]
