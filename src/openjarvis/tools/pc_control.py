"""Herramientas para que Jarvis actúe en el PC con Windows.

Abrir apps por su nombre, páginas web, música en YouTube, carpetas, controlar
el volumen y la reproducción, bloquear el equipo y preparar mensajes de
WhatsApp. Corren dentro del servidor de Jarvis, que está en el propio PC.

Seguridad: nada aquí ejecuta comandos ni rutas arbitrarias. Las apps salen del
menú Inicio, las carpetas de una lista fija, las webs solo con http(s) y los
mensajes de WhatsApp quedan escritos pero los envía el usuario.
"""

from __future__ import annotations

import difflib
import json
import os
import re
import subprocess
import sys
import time
import unicodedata
import webbrowser
from typing import Any, Dict, List, Optional
from urllib.parse import quote, quote_plus

from openjarvis.core.registry import ToolRegistry
from openjarvis.core.types import ToolResult
from openjarvis.tools._stubs import BaseTool, ToolSpec

# ---------------------------------------------------------------------------
# Acceso al sistema (sustituible en pruebas)
# ---------------------------------------------------------------------------

_KEYEVENTF_KEYUP = 0x0002
# Identificadores estándar de Windows (KNOWNFOLDERID) de las carpetas del usuario.
_KNOWN_FOLDER_GUIDS = {
    "downloads": "{374DE290-123F-4565-9164-39C4925E467B}",
    "documents": "{FDD39AD0-238F-46AF-ADB4-6C85480369C7}",
    "desktop": "{B4BFCC3A-DB2C-424C-B029-7FE99A87C641}",
    "pictures": "{33E28130-4E1E-4676-835A-98395C3BC3BB}",
    "music": "{4BD8D571-6D19-48D3-BE97-422220080E43}",
    "videos": "{18989B1D-99B5-455B-841C-AB7C74E4DDFC}",
}
_FALLBACK_FOLDER_NAMES = {
    "downloads": "Downloads",
    "documents": "Documents",
    "desktop": "Desktop",
    "pictures": "Pictures",
    "music": "Music",
    "videos": "Videos",
}


class _WindowsPlatform:
    """Operaciones reales de Windows."""

    is_windows = sys.platform == "win32"

    def list_start_apps(self) -> List[Dict[str, str]]:
        # Get-StartApps lista todo lo del menú Inicio, apps clásicas y de la Store.
        completed = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                "Get-StartApps | Select-Object Name, AppID | ConvertTo-Json -Compress",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=20,
            check=False,
        )
        data = json.loads(completed.stdout or "[]")
        return data if isinstance(data, list) else [data]

    def launch_app(self, app_id: str) -> None:
        # shell:AppsFolder abre igual una app clásica que una de la Store.
        subprocess.Popen(["explorer.exe", f"shell:AppsFolder\\{app_id}"])

    def open(self, target: str) -> None:
        if self.is_windows:
            os.startfile(target)  # type: ignore[attr-defined]
        else:
            webbrowser.open(target)

    def press_key(self, vk: int, times: int) -> None:
        import ctypes

        for _ in range(times):
            ctypes.windll.user32.keybd_event(vk, 0, 0, 0)  # type: ignore[attr-defined]
            ctypes.windll.user32.keybd_event(vk, 0, _KEYEVENTF_KEYUP, 0)  # type: ignore[attr-defined]
            time.sleep(0.02)

    def lock(self) -> None:
        import ctypes

        ctypes.windll.user32.LockWorkStation()  # type: ignore[attr-defined]

    def known_folder(self, folder_id: str) -> str:
        """Ruta real de la carpeta (respeta OneDrive y carpetas movidas)."""
        try:
            import ctypes
            import uuid
            from ctypes import wintypes

            class _Guid(ctypes.Structure):
                _fields_ = [
                    ("Data1", wintypes.DWORD),
                    ("Data2", wintypes.WORD),
                    ("Data3", wintypes.WORD),
                    ("Data4", wintypes.BYTE * 8),
                ]

            raw = uuid.UUID(_KNOWN_FOLDER_GUIDS[folder_id]).bytes_le
            guid = _Guid.from_buffer_copy(raw)
            path_ptr = ctypes.c_wchar_p()
            shell32 = ctypes.windll.shell32  # type: ignore[attr-defined]
            if (
                shell32.SHGetKnownFolderPath(
                    ctypes.byref(guid), 0, None, ctypes.byref(path_ptr)
                )
                == 0
            ):
                path = path_ptr.value
                ctypes.windll.ole32.CoTaskMemFree(path_ptr)  # type: ignore[attr-defined]
                if path:
                    return path
        except Exception:
            pass
        return os.path.join(os.path.expanduser("~"), _FALLBACK_FOLDER_NAMES[folder_id])

    def fetch(self, url: str) -> str:
        import httpx

        headers = {"User-Agent": "Mozilla/5.0", "Accept-Language": "es-CO,es;q=0.9"}
        return httpx.get(url, headers=headers, timeout=8, follow_redirects=True).text


_platform: Any = _WindowsPlatform()

# ---------------------------------------------------------------------------
# Búsqueda de apps por nombre hablado
# ---------------------------------------------------------------------------

_APP_CACHE_SECONDS = 300
_app_cache: Dict[str, Any] = {"apps": None, "at": 0.0}

# Palabras que acompañan la orden pero no son parte del nombre.
_FILLER = {
    "abre",
    "abrir",
    "abreme",
    "inicia",
    "iniciar",
    "ejecuta",
    "pon",
    "la",
    "el",
    "los",
    "las",
    "app",
    "aplicacion",
    "programa",
    "de",
    "mi",
    "por",
    "favor",
    "open",
}
# Nombres alternativos: cómo se dice → cómo puede llamarse en el menú Inicio.
_ALIASES = {
    "notepad": ["bloc de notas"],
    "bloc de notas": ["notepad"],
    "calculator": ["calculadora"],
    "calculadora": ["calculator"],
    "navegador": ["microsoft edge", "google chrome"],
    "edge": ["microsoft edge"],
    "chrome": ["google chrome"],
    "vs code": ["visual studio code"],
    "vscode": ["visual studio code"],
    "code": ["visual studio code"],
    "configuracion": ["settings", "configuracion"],
    "ajustes": ["configuracion", "settings"],
    "explorador": ["explorador de archivos", "file explorer"],
    "archivos": ["explorador de archivos", "file explorer"],
    "terminal": ["terminal", "windows powershell"],
    "correo": ["outlook", "correo", "mail"],
    "espotifai": ["spotify"],
    "guasap": ["whatsapp"],
    "wasap": ["whatsapp"],
}
_MIN_SCORE = 0.72


def _normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.lower())
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9 ]+", " ", text).strip()


def _strip_filler(text: str) -> str:
    return " ".join(word for word in _normalize(text).split() if word not in _FILLER)


def _score(query: str, name: str) -> float:
    if query == name:
        return 1.0
    if re.search(rf"\b{re.escape(query)}\b", name):
        # "chrome" dentro de "google chrome": coincidencia de palabra completa.
        return 0.95
    return difflib.SequenceMatcher(None, query, name).ratio()


def find_app(spoken: str, apps: List[Dict[str, str]]) -> Optional[Dict[str, str]]:
    """La app del menú Inicio que mejor corresponde a lo dicho, o None."""
    query = _strip_filler(spoken)
    if not query:
        return None
    queries = [query, *_ALIASES.get(query, [])]
    best, best_score = None, 0.0
    for app in apps:
        name = _normalize(app.get("Name", ""))
        for rank, candidate in enumerate(queries):
            # A igual coincidencia gana el alias listado primero ("navegador" → Edge).
            score = _score(candidate, name) - rank * 0.001
            if score > best_score:
                best, best_score = app, score
    return best if best_score >= _MIN_SCORE else None


def _start_apps() -> List[Dict[str, str]]:
    now = time.monotonic()
    if _app_cache["apps"] is None or now - _app_cache["at"] > _APP_CACHE_SECONDS:
        _app_cache["apps"] = _platform.list_start_apps()
        _app_cache["at"] = now
    return _app_cache["apps"]


def _clear_app_cache() -> None:
    _app_cache["apps"] = None
    _app_cache["at"] = 0.0


def _result(tool: str, content: str, success: bool = True) -> ToolResult:
    return ToolResult(tool_name=tool, content=content, success=success)


def _windows_only(tool: str) -> Optional[ToolResult]:
    if _platform.is_windows:
        return None
    return _result(
        tool, "Esta acción solo está disponible cuando Jarvis corre en Windows.", False
    )


# ---------------------------------------------------------------------------
# Herramientas
# ---------------------------------------------------------------------------


@ToolRegistry.register("open_app")
class OpenAppTool(BaseTool):
    """Abre una aplicación instalada buscándola por nombre en el menú Inicio."""

    tool_id = "open_app"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="open_app",
            description=(
                "Open an installed application on the user's Windows PC by its name, "
                "as the user says it (e.g. 'chrome', 'bloc de notas', 'spotify', "
                "'word', 'calculadora'). Use it whenever the user asks to open, "
                "start or launch a program."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "App name as the user said it",
                    },
                },
                "required": ["name"],
            },
            category="pc",
        )

    def execute(self, **params: Any) -> ToolResult:
        if (blocked := _windows_only("open_app")) is not None:
            return blocked
        spoken = str(params.get("name", "")).strip()
        apps = _start_apps()
        app = find_app(spoken, apps)
        if app is None:
            names = [a.get("Name", "") for a in apps]
            close = difflib.get_close_matches(
                _strip_filler(spoken), [_normalize(n) for n in names], n=3, cutoff=0.4
            )
            hint = f" Opciones parecidas: {', '.join(close)}." if close else ""
            return _result(
                "open_app",
                f"No encontré una app llamada '{spoken}' en el menú Inicio.{hint}",
                False,
            )
        _platform.launch_app(app["AppID"])
        return _result("open_app", f"Abrí {app['Name']}.")


@ToolRegistry.register("open_website")
class OpenWebsiteTool(BaseTool):
    """Abre una página web o una búsqueda de Google en el navegador."""

    tool_id = "open_website"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="open_website",
            description=(
                "Open a web page in the user's browser. Pass a URL or domain "
                "(e.g. 'github.com') to open it, or plain words to run a Google search."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "target": {
                        "type": "string",
                        "description": "URL, domain or search words",
                    },
                },
                "required": ["target"],
            },
            category="pc",
        )

    def execute(self, **params: Any) -> ToolResult:
        target = str(params.get("target", "")).strip()
        if not target:
            return _result("open_website", "No indicaste qué abrir.", False)
        if re.match(r"^https?://", target, re.IGNORECASE):
            url = target
        elif re.fullmatch(r"[\w-]+(\.[\w-]+)+(/\S*)?", target):
            url = f"https://{target}"
        else:
            # Cualquier otra cosa (incluido file://) se busca, nunca se abre como ruta.
            url = f"https://www.google.com/search?q={quote_plus(target)}"
        _platform.open(url)
        return _result("open_website", f"Abrí {url} en el navegador.")


@ToolRegistry.register("play_youtube")
class PlayYoutubeTool(BaseTool):
    """Pone en YouTube el primer video que coincide con la búsqueda."""

    tool_id = "play_youtube"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="play_youtube",
            description=(
                "Play music or a video on YouTube: opens the first result for the "
                "query "
                "(e.g. 'lofi para estudiar', 'Shakira Hips Don't Lie')."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "What to play"}
                },
                "required": ["query"],
            },
            category="pc",
        )

    def execute(self, **params: Any) -> ToolResult:
        query = str(params.get("query", "")).strip()
        if not query:
            return _result("play_youtube", "No indicaste qué poner.", False)
        results_url = (
            f"https://www.youtube.com/results?search_query={quote_plus(query)}"
        )
        try:
            match = re.search(r'"videoId":"([\w-]{11})"', _platform.fetch(results_url))
        except Exception:
            match = None
        url = (
            f"https://www.youtube.com/watch?v={match.group(1)}"
            if match
            else results_url
        )
        _platform.open(url)
        return _result("play_youtube", f"Puse '{query}' en YouTube.")


_MEDIA_KEYS = {
    "play_pause": 0xB3,
    "next": 0xB0,
    "previous": 0xB1,
    "volume_up": 0xAF,
    "volume_down": 0xAE,
    "mute": 0xAD,
}


@ToolRegistry.register("media_control")
class MediaControlTool(BaseTool):
    """Controla la reproducción y el volumen con las teclas multimedia."""

    tool_id = "media_control"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="media_control",
            description=(
                "Control media playback and volume on the PC: play_pause, next, "
                "previous, "
                "volume_up, volume_down, mute. Each volume step is about 2%."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": sorted(_MEDIA_KEYS)},
                    "steps": {
                        "type": "integer",
                        "description": (
                            "Volume steps for volume_up/volume_down (default 5)"
                        ),
                    },
                },
                "required": ["action"],
            },
            category="pc",
        )

    def execute(self, **params: Any) -> ToolResult:
        if (blocked := _windows_only("media_control")) is not None:
            return blocked
        action = str(params.get("action", ""))
        if action not in _MEDIA_KEYS:
            return _result("media_control", f"Acción desconocida: {action}.", False)
        times = 1
        if action in ("volume_up", "volume_down"):
            times = max(1, min(50, int(params.get("steps") or 5)))
        _platform.press_key(_MEDIA_KEYS[action], times)
        return _result("media_control", f"Hecho: {action}.")


@ToolRegistry.register("lock_computer")
class LockComputerTool(BaseTool):
    """Bloquea el equipo."""

    tool_id = "lock_computer"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="lock_computer",
            description=(
                "Lock the Windows session (the user needs their PIN to return)."
            ),
            parameters={"type": "object", "properties": {}},
            category="pc",
        )

    def execute(self, **params: Any) -> ToolResult:
        if (blocked := _windows_only("lock_computer")) is not None:
            return blocked
        _platform.lock()
        return _result("lock_computer", "Equipo bloqueado.")


_FOLDER_NAMES = {
    "downloads": "downloads",
    "descargas": "downloads",
    "documents": "documents",
    "documentos": "documents",
    "mis documentos": "documents",
    "desktop": "desktop",
    "escritorio": "desktop",
    "pictures": "pictures",
    "imagenes": "pictures",
    "fotos": "pictures",
    "music": "music",
    "musica": "music",
    "videos": "videos",
}


@ToolRegistry.register("open_folder")
class OpenFolderTool(BaseTool):
    """Abre una carpeta personal en el Explorador de archivos."""

    tool_id = "open_folder"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="open_folder",
            description=(
                "Open one of the user's folders in File Explorer: "
                "descargas, documentos, escritorio, imágenes, música, videos."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Folder name"}
                },
                "required": ["name"],
            },
            category="pc",
        )

    def execute(self, **params: Any) -> ToolResult:
        if (blocked := _windows_only("open_folder")) is not None:
            return blocked
        folder_id = _FOLDER_NAMES.get(_strip_filler(str(params.get("name", ""))))
        if folder_id is None:
            return _result(
                "open_folder",
                "Solo puedo abrir: descargas, documentos, escritorio, imágenes, "
                "música o videos.",
                False,
            )
        path = _platform.known_folder(folder_id)
        _platform.open(path)
        return _result("open_folder", f"Abrí la carpeta {path}.")


@ToolRegistry.register("whatsapp_message")
class WhatsappMessageTool(BaseTool):
    """Deja un mensaje escrito en WhatsApp; el usuario decide si lo envía."""

    tool_id = "whatsapp_message"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="whatsapp_message",
            description=(
                "Prepare a WhatsApp message in the WhatsApp app with the text already "
                "written. It is NOT sent: the user presses Enter. Pass the phone "
                "number with country code if known (e.g. +57 300 123 4567); without "
                "it the user "
                "picks the chat."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "Message text"},
                    "phone": {
                        "type": "string",
                        "description": "Phone with country code",
                    },
                },
                "required": ["text"],
            },
            category="pc",
        )

    def execute(self, **params: Any) -> ToolResult:
        text = str(params.get("text", "")).strip()
        if not text:
            return _result("whatsapp_message", "No indicaste el mensaje.", False)
        digits = re.sub(r"\D", "", str(params.get("phone") or ""))
        query = (
            f"phone={digits}&text={quote_plus(text)}"
            if digits
            else f"text={quote_plus(text)}"
        )
        try:
            _platform.open(f"whatsapp://send?{query}")
        except OSError:
            # Sin la app de escritorio: WhatsApp Web abre el mismo chat.
            _platform.open(f"https://wa.me/{digits}?text={quote(text)}")
        return _result(
            "whatsapp_message",
            "Dejé el mensaje escrito en WhatsApp. Revíselo y pulse Enter para "
            "enviarlo.",
        )


__all__ = [
    "LockComputerTool",
    "MediaControlTool",
    "OpenAppTool",
    "OpenFolderTool",
    "OpenWebsiteTool",
    "PlayYoutubeTool",
    "WhatsappMessageTool",
    "find_app",
]
