"""General purpose utilities."""

from __future__ import annotations

import platform
import shutil
import subprocess
import webbrowser


def get_python_executable() -> str:
    """Return 'python3' if available, falling back to 'python'."""
    return shutil.which("python3") or shutil.which("python") or "python3"


def open_browser(url: str) -> None:
    """Open a URL in the browser, with Windows support via cmd /c start."""
    if platform.system() == "Windows":
        # 'cmd /c start "" "URL"' is the safest way to open a URL on Windows
        # check=False because we don't want to crash if browser fails to open.
        try:
            subprocess.run(["cmd", "/c", "start", "", url], check=False)
        except Exception:
            # Fallback to webbrowser if subprocess fails
            webbrowser.open(url)
    else:
        webbrowser.open(url)
