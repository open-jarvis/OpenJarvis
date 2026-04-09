"""Screen capture tool -- capture the screen and optionally extract text via OCR.

Real Jarvis sees the displays in the lab.  This tool lets agents do the same:
capture a screenshot (full screen or a region), optionally OCR it, and return
the image as a base64-encoded PNG so multimodal LLMs can analyse it.

Dependencies (optional extras):
  pip install openjarvis[screen]          # mss + Pillow
  pip install openjarvis[screen-ocr]      # + pytesseract
"""

from __future__ import annotations

import base64
import io
import tempfile
from pathlib import Path
from typing import Any

from openjarvis.core.registry import ToolRegistry
from openjarvis.core.types import ToolResult
from openjarvis.tools._stubs import BaseTool, ToolSpec


@ToolRegistry.register("screen_capture")
class ScreenCaptureTool(BaseTool):
    """Capture the screen and optionally extract text via OCR.

    The image is returned as a base64-encoded PNG string.  Multimodal
    models (GPT-4o, Claude 3, Gemini 1.5 ...) can consume it directly.
    """

    tool_id = "screen_capture"
    is_local = True

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="screen_capture",
            description=(
                "Capture a screenshot of the screen or a specific region. "
                "Returns the image as a base64-encoded PNG and, optionally, "
                "extracted text via OCR.  Use this to let the agent see what is "
                "currently on the user's display."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "region": {
                        "type": "object",
                        "description": (
                            "Optional capture region: {left, top, width, height} "
                            "in pixels.  Omit for full screen."
                        ),
                        "properties": {
                            "left":   {"type": "integer"},
                            "top":    {"type": "integer"},
                            "width":  {"type": "integer"},
                            "height": {"type": "integer"},
                        },
                        "required": ["left", "top", "width", "height"],
                    },
                    "monitor": {
                        "type": "integer",
                        "description": (
                            "Monitor index (1-based).  0 = all monitors combined. "
                            "Default 1 (primary)."
                        ),
                    },
                    "ocr": {
                        "type": "boolean",
                        "description": (
                            "Extract text from the screenshot via OCR.  "
                            "Requires pytesseract or easyocr.  Default false."
                        ),
                    },
                    "output_path": {
                        "type": "string",
                        "description": "Optional file path to save the PNG to.",
                    },
                    "max_width": {
                        "type": "integer",
                        "description": (
                            "Resize the image to at most this width (pixels) before "
                            "encoding.  Useful to stay within token limits.  "
                            "Default 1280."
                        ),
                    },
                },
                "required": [],
            },
            category="media",
        )

    def execute(self, **params: Any) -> ToolResult:
        region     = params.get("region")
        monitor    = params.get("monitor", 1)
        want_ocr   = params.get("ocr", False)
        output_path = params.get("output_path")
        max_width  = params.get("max_width", 1280)

        # ------------------------------------------------------------------ #
        # 1. Capture                                                           #
        # ------------------------------------------------------------------ #
        img_bytes, width, height = self._capture(region, monitor)
        if img_bytes is None:
            return ToolResult(
                tool_name="screen_capture",
                success=False,
                content=(
                    "Screen capture failed: neither mss nor Pillow.ImageGrab is "
                    "available.\n"
                    "Install with: pip install openjarvis[screen]"
                ),
            )

        # ------------------------------------------------------------------ #
        # 2. Resize (keep aspect ratio)                                        #
        # ------------------------------------------------------------------ #
        img_bytes = self._maybe_resize(img_bytes, max_width)

        # ------------------------------------------------------------------ #
        # 3. Save to file (optional)                                           #
        # ------------------------------------------------------------------ #
        if output_path:
            try:
                Path(output_path).expanduser().write_bytes(img_bytes)
            except Exception as exc:
                return ToolResult(
                    tool_name="screen_capture",
                    success=False,
                    content=f"Captured but could not save to {output_path}: {exc}",
                )

        # ------------------------------------------------------------------ #
        # 4. OCR (optional)                                                    #
        # ------------------------------------------------------------------ #
        ocr_text = ""
        if want_ocr:
            ocr_text = self._ocr(img_bytes)

        # ------------------------------------------------------------------ #
        # 5. Base64-encode for multimodal LLMs                                 #
        # ------------------------------------------------------------------ #
        b64 = base64.b64encode(img_bytes).decode("ascii")
        content_parts = [f"data:image/png;base64,{b64}"]
        if ocr_text:
            content_parts.append(f"\n\n[OCR TEXT]\n{ocr_text}")

        return ToolResult(
            tool_name="screen_capture",
            success=True,
            content="\n".join(content_parts),
            metadata={
                "width": width,
                "height": height,
                "ocr_available": bool(ocr_text),
                "saved_to": output_path or "",
            },
        )

    # ---------------------------------------------------------------------- #
    # Private helpers                                                          #
    # ---------------------------------------------------------------------- #

    def _capture(
        self, region: dict | None, monitor: int
    ) -> tuple[bytes | None, int, int]:
        """Return raw PNG bytes + (width, height).  Try mss first, PIL fallback."""

        # --- mss (preferred: fast, multi-monitor, cross-platform) ---------- #
        try:
            import mss
            import mss.tools

            with mss.mss() as sct:
                if region:
                    bbox = {
                        "left":   int(region["left"]),
                        "top":    int(region["top"]),
                        "width":  int(region["width"]),
                        "height": int(region["height"]),
                    }
                else:
                    monitors = sct.monitors  # index 0 = all, 1+ = individual
                    idx = min(monitor, len(monitors) - 1)
                    bbox = sct.monitors[idx]

                raw = sct.grab(bbox)
                png_bytes = mss.tools.to_png(raw.rgb, raw.size)
                return png_bytes, raw.width, raw.height

        except ImportError:
            pass
        except Exception:
            pass

        # --- Pillow ImageGrab (fallback, Windows/macOS only) ---------------- #
        try:
            from PIL import ImageGrab, Image  # type: ignore[import]

            if region:
                box = (
                    int(region["left"]),
                    int(region["top"]),
                    int(region["left"]) + int(region["width"]),
                    int(region["top"]) + int(region["height"]),
                )
                img = ImageGrab.grab(bbox=box)
            else:
                img = ImageGrab.grab()

            buf = io.BytesIO()
            img.save(buf, format="PNG")
            return buf.getvalue(), img.width, img.height

        except ImportError:
            pass
        except Exception:
            pass

        return None, 0, 0

    def _maybe_resize(self, png_bytes: bytes, max_width: int) -> bytes:
        """Downscale the image if wider than max_width."""
        try:
            from PIL import Image  # type: ignore[import]

            img = Image.open(io.BytesIO(png_bytes))
            if img.width <= max_width:
                return png_bytes

            ratio  = max_width / img.width
            new_h  = int(img.height * ratio)
            img    = img.resize((max_width, new_h), Image.LANCZOS)
            buf    = io.BytesIO()
            img.save(buf, format="PNG", optimize=True)
            return buf.getvalue()

        except ImportError:
            # Pillow not installed -- skip resize
            return png_bytes
        except Exception:
            return png_bytes

    def _ocr(self, png_bytes: bytes) -> str:
        """Extract text from image.  Try pytesseract first, then easyocr."""

        # --- pytesseract --------------------------------------------------- #
        try:
            import pytesseract  # type: ignore[import]
            from PIL import Image  # type: ignore[import]

            img  = Image.open(io.BytesIO(png_bytes))
            text = pytesseract.image_to_string(img)
            return text.strip()

        except ImportError:
            pass
        except Exception:
            pass

        # --- easyocr ------------------------------------------------------- #
        try:
            import easyocr  # type: ignore[import]
            import numpy as np  # type: ignore[import]
            from PIL import Image  # type: ignore[import]

            img    = Image.open(io.BytesIO(png_bytes))
            arr    = np.array(img)
            reader = easyocr.Reader(["en"], gpu=False, verbose=False)
            results = reader.readtext(arr, detail=0)
            return "\n".join(results).strip()

        except ImportError:
            return "(OCR not available: install pytesseract or easyocr)"
        except Exception as exc:
            return f"(OCR error: {exc})"


__all__ = ["ScreenCaptureTool"]
