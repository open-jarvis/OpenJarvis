"""Screen capture for vision input (``jarvis ask --screen``).

Captures the primary monitor to a temporary PNG so it can be handed to a
vision-capable model. On Windows this uses the built-in .NET
``System.Drawing`` stack (no third-party dependency). Other platforms fall
back to ``mss`` or ``Pillow`` if installed.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile

# PowerShell: capture the PRIMARY monitor (more legible for a vision model
# than a downscaled multi-monitor grab). {path} is filled in with forward
# slashes, which .NET accepts on Windows and which avoids backslash escaping.
_PS_CAPTURE = """
Add-Type -AssemblyName System.Windows.Forms, System.Drawing
$b = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds
$bmp = New-Object System.Drawing.Bitmap($b.Width, $b.Height)
$g = [System.Drawing.Graphics]::FromImage($bmp)
$g.CopyFromScreen($b.X, $b.Y, 0, 0, $bmp.Size)
$bmp.Save("{path}", [System.Drawing.Imaging.ImageFormat]::Png)
$g.Dispose(); $bmp.Dispose()
"""


def capture_screen_to_temp() -> str:
    """Capture the screen to a temp PNG and return its absolute path.

    Raises ``RuntimeError`` with actionable guidance if capture fails or the
    platform has no available backend.
    """
    fd, path = tempfile.mkstemp(prefix="jarvis_screen_", suffix=".png")
    os.close(fd)

    if sys.platform.startswith("win"):
        script = _PS_CAPTURE.replace("{path}", path.replace("\\", "/"))
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if (
            proc.returncode != 0
            or not os.path.exists(path)
            or not os.path.getsize(path)
        ):
            raise RuntimeError(
                "screen capture failed: "
                + (proc.stderr.strip() or "empty image written")
            )
        return path

    # Non-Windows: optional backends.
    try:
        import mss  # type: ignore

        with mss.mss() as sct:
            sct.shot(mon=-1, output=path)
        return path
    except ImportError:
        pass
    try:
        from PIL import ImageGrab  # type: ignore

        ImageGrab.grab().save(path)
        return path
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(
            "screen capture on this platform needs 'mss' or 'Pillow' "
            "(try: pip install mss)"
        ) from exc


__all__ = ["capture_screen_to_temp"]
