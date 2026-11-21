"""Deterministic creative layout (HTML) and PNG export with headless Chrome.

Text, logo and contact details are placed by fixed layout code — never by an
image model — so package labels, headlines and numbers stay exact. The page
runs a small fitting script that only reduces font sizes within fixed bounds,
then reports any text that is clipped or leaves the canvas; export fails
visibly instead of producing a clipped image.
"""

from __future__ import annotations

import base64
import html
import json
import os
import re
import shutil
import struct
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional

SIZE = 1080
_MIME = {".png": "png", ".jpg": "jpeg", ".jpeg": "jpeg", ".webp": "webp"}
_CHROME_CANDIDATES = (
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
)


class RenderError(RuntimeError):
    """Arabic message safe to show the operator."""


def data_uri(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix not in _MIME:
        raise RenderError("استخدم صورة PNG أو JPEG أو WebP.")
    if path.stat().st_size > 20_000_000:
        raise RenderError("الصورة أكبر من الحد المسموح (20 ميجابايت).")
    encoded = base64.b64encode(path.read_bytes()).decode()
    return f"data:image/{_MIME[suffix]};base64,{encoded}"


def build_html(
    *,
    product: Path,
    logo: Path,
    headline: str,
    contact: str,
    language: str = "ar",
    accent: str = "#153d30",
) -> str:
    headline, contact = headline.strip(), contact.strip()
    if not headline or len(headline) > 85:
        raise RenderError("العنوان مطلوب وبحد أقصى 85 حرفًا.")
    if not contact or len(contact) > 160:
        raise RenderError("بيانات التواصل المعتمدة مطلوبة وبحد أقصى 160 حرفًا.")
    if language not in {"ar", "en"}:
        raise RenderError("اللغة يجب أن تكون ar أو en.")
    if not re.fullmatch(r"#[0-9a-fA-F]{6}", accent):
        raise RenderError("لون الهوية يجب أن يكون بصيغة #RRGGBB.")
    direction = "rtl" if language == "ar" else "ltr"
    return f"""<!doctype html>
<html lang="{language}" dir="{direction}">
<head>
<meta charset="utf-8">
<meta http-equiv="Content-Security-Policy"
 content="default-src 'none'; img-src data:; style-src 'unsafe-inline';
 script-src 'unsafe-inline'">
<title>مسودة إعلان</title>
<style>
*{{box-sizing:border-box;margin:0}}
html,body{{width:{SIZE}px;height:{SIZE}px;overflow:hidden;background:#faf7ed}}
body{{font-family:"SF Arabic","Geeza Pro","Noto Naskh Arabic","Noto Sans Arabic",
 "Tahoma",sans-serif;color:{accent}}}
main{{position:relative;width:{SIZE}px;height:{SIZE}px;padding:56px 64px;
 display:grid;grid-template-rows:110px 210px 1fr 120px;gap:24px}}
header{{display:flex;justify-content:flex-start;align-items:center;min-height:0}}
header img{{max-height:110px;max-width:300px;object-fit:contain}}
h1{{font-size:64px;line-height:1.35;font-weight:700;overflow:hidden;
 display:flex;align-items:center;text-align:start}}
.product{{width:100%;height:100%;min-height:0;object-fit:contain}}
footer{{font-size:32px;line-height:1.45;overflow:hidden;white-space:pre-wrap;
 border-top:4px solid {accent};padding-top:14px;unicode-bidi:plaintext}}
</style>
</head>
<body>
<main>
<header><img alt="الشعار" src="{data_uri(logo)}"></header>
<h1 data-fit="64,38">{html.escape(headline)}</h1>
<img class="product" alt="المنتج" src="{data_uri(product)}">
<footer data-fit="32,22">{html.escape(contact)}</footer>
</main>
<script>
(function () {{
  var issues = [];
  var main = document.querySelector('main').getBoundingClientRect();
  document.querySelectorAll('[data-fit]').forEach(function (el) {{
    var bounds = el.dataset.fit.split(',').map(Number), size = bounds[0];
    function overflowing() {{
      return el.scrollHeight > el.clientHeight + 1 ||
             el.scrollWidth > el.clientWidth + 1;
    }}
    el.style.fontSize = size + 'px';
    while (overflowing() && size > bounds[1]) {{
      size -= 2; el.style.fontSize = size + 'px';
    }}
    var r = el.getBoundingClientRect();
    if (overflowing()) issues.push(el.tagName.toLowerCase() + ':clipped');
    if (r.left < main.left || r.right > main.right ||
        r.top < main.top || r.bottom > main.bottom)
      issues.push(el.tagName.toLowerCase() + ':outside');
    el.dataset.size = size;
  }});
  document.querySelectorAll('img').forEach(function (img) {{
    if (!img.complete || !img.naturalWidth) issues.push('img:not_loaded');
  }});
  document.body.setAttribute('data-fit-result', JSON.stringify({{
    ok: issues.length === 0, issues: issues,
    headline_px: Number(document.querySelector('h1').dataset.size),
    contact_px: Number(document.querySelector('footer').dataset.size)
  }}));
}})();
</script>
</body>
</html>"""


def find_chrome() -> str:
    configured = os.environ.get("OPENJARVIS_CHROME", "")
    for candidate in (configured, *_CHROME_CANDIDATES):
        if candidate and Path(candidate).is_file():
            return candidate
    for name in ("google-chrome", "chromium", "chromium-browser", "chrome"):
        found = shutil.which(name)
        if found:
            return found
    raise RenderError(
        "لم يُعثر على متصفح Chrome/Chromium لتصدير PNG. ثبّته أو حدّد مساره في "
        "OPENJARVIS_CHROME."
    )


def _chrome(args: list[str], *, timeout: float) -> subprocess.CompletedProcess:
    with tempfile.TemporaryDirectory(prefix="oj-render-") as profile:
        command = [
            find_chrome(),
            "--headless=new",
            "--disable-gpu",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-extensions",
            "--disable-background-networking",
            "--hide-scrollbars",
            "--force-device-scale-factor=1",
            f"--user-data-dir={profile}",
            f"--window-size={SIZE},{SIZE}",
            "--virtual-time-budget=5000",
            *args,
        ]
        try:
            return subprocess.run(
                command, capture_output=True, timeout=timeout, check=False
            )
        except subprocess.TimeoutExpired:
            raise RenderError("انتهت مهلة تصدير الصورة.") from None


def png_size(path: Path) -> tuple[int, int]:
    with path.open("rb") as handle:
        header = handle.read(24)
    if (
        len(header) < 24
        or header[:8] != b"\x89PNG\r\n\x1a\n"
        or header[12:16] != b"IHDR"
    ):
        raise RenderError("الملف الناتج ليس صورة PNG صالحة.")
    return struct.unpack(">II", header[16:24])


def render_png(html_path: Path, png_path: Path, *, timeout: float = 60.0) -> Dict:
    """Check layout fit, then export exactly SIZE×SIZE PNG. Raises RenderError."""
    url = html_path.resolve().as_uri()
    dom = _chrome(["--dump-dom", url], timeout=timeout)
    match = re.search(rb'data-fit-result="([^"]*)"', dom.stdout)
    if dom.returncode != 0 or not match:
        raise RenderError("تعذّر فحص تخطيط التصميم في المتصفح.")
    fit: Dict[str, Any] = json.loads(html.unescape(match.group(1).decode()))
    if not fit.get("ok"):
        labels = {
            "h1:clipped": "العنوان أطول من مساحته حتى بأصغر خط مسموح",
            "footer:clipped": "بيانات التواصل أطول من مساحتها",
            "h1:outside": "العنوان يخرج من حدود التصميم",
            "footer:outside": "بيانات التواصل تخرج من حدود التصميم",
            "img:not_loaded": "تعذّر تحميل صورة المنتج أو الشعار",
        }
        raise RenderError(
            "التصميم غير صالح للنشر: "
            + "، ".join(labels.get(i, i) for i in fit.get("issues", []))
            + ". اختصر النص أو عدّله."
        )
    png_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = png_path.with_suffix(".tmp.png")
    shot = _chrome([f"--screenshot={tmp}", url], timeout=timeout)
    if shot.returncode != 0 or not tmp.is_file():
        tmp.unlink(missing_ok=True)
        raise RenderError("فشل تصدير الصورة إلى PNG.")
    if png_size(tmp) != (SIZE, SIZE):
        tmp.unlink(missing_ok=True)
        raise RenderError(f"مقاس الصورة الناتجة ليس {SIZE}×{SIZE}.")
    os.replace(tmp, png_path)
    return fit


def sha256(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def sidecar(path: Path) -> Optional[Dict[str, Any]]:
    meta = path.with_name(path.name + ".json")
    if not meta.is_file():
        return None
    try:
        return json.loads(meta.read_text(encoding="utf-8"))
    except ValueError:
        return None


__all__ = [
    "RenderError",
    "build_html",
    "find_chrome",
    "png_size",
    "render_png",
    "sha256",
    "sidecar",
]
