"""HTTP Bridge Server for OpenJarvis on iPadOS (a-Shell).

Aligned with ``comic_tools``'s a-Shell HTTP server architecture:
- Async ``aiohttp`` server (with ``tcp_keepalive`` iOS socket patch) when
  ``aiohttp`` is available, plus a stdlib ``ThreadingHTTPServer`` fallback for
  ``--no-deps`` environments.
- Port-retry binding (``DEFAULT_PORT`` + up to 3 trials).
- Serialized ``ctypes.CDLL(None).ios_system`` bridge for ``internalbrowser``
  auto-launch on a-Shell.
- Static website / SPA serving with path-traversal protection, ``.gz``
  pre-compressed asset support, and fallback to the built-in mobile UI.
- Graceful ``shutdown_event`` lifecycle with iOS-safe signal/TTY handling.

Listens on ``127.0.0.1:8085`` by default and bridges OpenJarvis requests to
Apple Intelligence Foundation Models via the ``AskAFM`` Apple Shortcut using
a clipboard protocol (``pbcopy`` / ``pbpaste``):

- Request:  ``JARVIS_REQ||<MODE>||<UUID>||<PROMPT>``  (MODE = LOCAL | CLOUD)
- Response: ``JARVIS_RES||<UUID>||<RESPONSE>``

Endpoints:
- ``GET /``: Built static SPA (if present) or mobile-first Web UI.
- ``GET /v1/models``: OpenAI-compatible model listing.
- ``POST /api/chat``: Executes ``jarvis_ios.py ask --model <model> <prompt>``.
- ``POST /v1/chat/completions``: OpenAI-compatible chat completions bridged to
  ``shortcuts://run-shortcut?name=AskAFM``.
- ``GET /shutdown`` & ``GET /api/v1/system/shutdown``: Clean server termination.
"""

from __future__ import annotations

import asyncio
import ctypes
import json
import logging
import mimetypes
import os
import signal
import subprocess
import sys
import threading
import time
import uuid
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

DEFAULT_HOST = os.environ.get("JARVIS_IOS_HOST", "127.0.0.1")
DEFAULT_PORT = int(os.environ.get("JARVIS_IOS_PORT", "8085"))
PORT_BIND_TRIALS = 3
SHORTCUT_NAME = os.environ.get("JARVIS_ASKAFM_SHORTCUT", "AskAFM")
BRIDGE_TIMEOUT_SECONDS = float(os.environ.get("JARVIS_IOS_TIMEOUT", "90.0"))
POLL_INTERVAL_SECONDS = 0.25

REQ_PREFIX = "JARVIS_REQ||"
RES_PREFIX = "JARVIS_RES||"

_IOS_SYSTEM_LOCK = threading.Lock()
_CACHED_IOS_SYSTEM: Any = None
_IOS_SYSTEM_INITIALIZED = False


def is_ashell() -> bool:
    """Return True when running inside iOS a-Shell / a-Shell mini."""
    return os.environ.get("TERM_PROGRAM", "").strip().lower() == "a-shell"


def _get_ios_system() -> Any:
    """Lazily load ``ios_system`` from the host a-Shell binary."""
    global _CACHED_IOS_SYSTEM, _IOS_SYSTEM_INITIALIZED
    if _IOS_SYSTEM_INITIALIZED:
        return _CACHED_IOS_SYSTEM
    _IOS_SYSTEM_INITIALIZED = True
    if not is_ashell():
        return None
    try:
        fn = ctypes.CDLL(None).ios_system
        fn.argtypes = [ctypes.c_char_p]
        fn.restype = ctypes.c_int
        _CACHED_IOS_SYSTEM = fn
    except Exception:
        _CACHED_IOS_SYSTEM = None
    return _CACHED_IOS_SYSTEM


def _escape_shell_arg(arg: str) -> str:
    """Escape single quotes for a-Shell ``ios_system`` commands."""
    return "'" + arg.replace("'", "'\\''") + "'"


def open_in_internal_browser(url: str) -> bool:
    """Open ``url`` in a-Shell's ``internalbrowser`` using serialized ``ios_system``."""
    ios_system = _get_ios_system()
    if ios_system is None:
        return False
    cmd = f"internalbrowser {_escape_shell_arg(url)}".encode("utf-8")
    with _IOS_SYSTEM_LOCK:
        return int(ios_system(cmd)) == 0


def resolve_static_dir(static_dir: Path | str | None = None) -> Path | None:
    """Locate a built static frontend directory if one exists."""
    if static_dir is not None:
        candidate = Path(static_dir)
        return candidate if candidate.is_dir() else None

    env_dir = os.environ.get("JARVIS_IOS_STATIC_DIR")
    if env_dir:
        candidate = Path(env_dir).expanduser()
        if candidate.is_dir():
            return candidate

    roots: list[Path] = []
    env_root = os.environ.get("OPENJARVIS_REPO_ROOT")
    if env_root:
        roots.append(Path(env_root).expanduser())
    marker = Path(__file__).resolve().with_name("repo_root.txt")
    if marker.is_file():
        saved = marker.read_text(encoding="utf-8").strip()
        if saved:
            roots.append(Path(saved).expanduser())
    roots.append(Path(__file__).resolve().parents[1])

    for repo_root in roots:
        for candidate in (
            repo_root / "src" / "openjarvis" / "server" / "static",
            repo_root / "frontend" / "dist",
            repo_root / "dist",
        ):
            if candidate.is_dir() and (candidate / "index.html").is_file():
                return candidate
    return None


def _patch_aiohttp_tcp_keepalive() -> None:
    """Mirror comic_tools iOS fix: ignore tcp_keepalive errors on a-Shell sockets."""
    try:
        import aiohttp.tcp_helpers

        original = aiohttp.tcp_helpers.tcp_keepalive

        def _patched_tcp_keepalive(transport: Any) -> None:
            try:
                original(transport)
            except (AttributeError, TypeError):
                pass

        aiohttp.tcp_helpers.tcp_keepalive = _patched_tcp_keepalive
    except Exception:
        pass


_MOBILE_UI_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1" />
  <title>OpenJarvis iPadOS</title>
  <style>
    :root { color-scheme: dark light; --bg: #0f1117; --card: #181c26; --text: #eef1f7; --muted: #98a2b3; --accent: #3b82f6; --border: #2a3040; }
    @media (prefers-color-scheme: light) {
      :root { --bg: #f5f7fb; --card: #ffffff; --text: #111827; --muted: #6b7280; --accent: #2563eb; --border: #e5e7eb; }
    }
    * { box-sizing: border-box; }
    body { margin: 0; font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text", sans-serif; background: var(--bg); color: var(--text); display: flex; flex-direction: column; height: 100dvh; }
    header { padding: 12px 16px; border-bottom: 1px solid var(--border); display: flex; align-items: center; justify-content: space-between; gap: 8px; background: var(--card); }
    header h1 { font-size: 1rem; margin: 0; font-weight: 600; }
    .controls { display: flex; gap: 6px; align-items: center; }
    .toggle { border: 1px solid var(--border); background: transparent; color: var(--text); padding: 6px 10px; border-radius: 999px; font-size: 0.8rem; cursor: pointer; }
    .toggle.active { background: var(--accent); border-color: var(--accent); color: #fff; }
    .shutdown { border: 1px solid #ef4444; color: #ef4444; background: transparent; padding: 6px 10px; border-radius: 999px; font-size: 0.8rem; cursor: pointer; }
    main { flex: 1; overflow-y: auto; padding: 16px; display: flex; flex-direction: column; gap: 12px; }
    .msg { max-width: 85%; padding: 10px 14px; border-radius: 14px; line-height: 1.45; white-space: pre-wrap; word-break: break-word; }
    .msg.user { align-self: flex-end; background: var(--accent); color: #fff; }
    .msg.assistant { align-self: flex-start; background: var(--card); border: 1px solid var(--border); }
    form { display: flex; gap: 8px; padding: 12px 16px; border-top: 1px solid var(--border); background: var(--card); }
    textarea { flex: 1; resize: none; border: 1px solid var(--border); border-radius: 12px; padding: 10px 12px; font: inherit; background: var(--bg); color: var(--text); min-height: 44px; max-height: 140px; }
    button[type="submit"] { background: var(--accent); color: #fff; border: none; border-radius: 12px; padding: 0 18px; font-weight: 600; cursor: pointer; }
    button:disabled { opacity: 0.55; }
  </style>
</head>
<body>
  <header>
    <h1>OpenJarvis iPadOS</h1>
    <div class="controls">
      <button id="btn-local" class="toggle active" type="button">Local (AFM)</button>
      <button id="btn-cloud" class="toggle" type="button">Cloud (PCC)</button>
      <button id="btn-stop" class="shutdown" type="button">Stop</button>
    </div>
  </header>
  <main id="chat"></main>
  <form id="composer">
    <textarea id="prompt" rows="1" placeholder="Ask OpenJarvis..." required></textarea>
    <button id="send" type="submit">Send</button>
  </form>
  <script>
    let selectedModel = "AskAFM";
    const chat = document.getElementById("chat");
    const promptEl = document.getElementById("prompt");
    const sendBtn = document.getElementById("send");
    const btnLocal = document.getElementById("btn-local");
    const btnCloud = document.getElementById("btn-cloud");

    function setModel(model) {
      selectedModel = model;
      btnLocal.classList.toggle("active", model === "AskAFM");
      btnCloud.classList.toggle("active", model === "AskAFMCloud");
    }
    btnLocal.onclick = () => setModel("AskAFM");
    btnCloud.onclick = () => setModel("AskAFMCloud");
    document.getElementById("btn-stop").onclick = async () => {
      await fetch("/shutdown");
      addMsg("Server shutting down.", "assistant");
    };

    function addMsg(text, role) {
      const div = document.createElement("div");
      div.className = "msg " + role;
      div.textContent = text;
      chat.appendChild(div);
      chat.scrollTop = chat.scrollHeight;
      return div;
    }

    document.getElementById("composer").onsubmit = async (e) => {
      e.preventDefault();
      const text = promptEl.value.trim();
      if (!text) return;
      promptEl.value = "";
      addMsg(text, "user");
      const pending = addMsg("Thinking (" + selectedModel + ")...", "assistant");
      sendBtn.disabled = true;
      try {
        const res = await fetch("/api/chat", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ model: selectedModel, prompt: text })
        });
        const data = await res.json();
        pending.textContent = data.response || data.error || JSON.stringify(data);
      } catch (err) {
        pending.textContent = "Error: " + err;
      } finally {
        sendBtn.disabled = false;
      }
    };
  </script>
</body>
</html>
"""


def resolve_mode(model: str | None) -> str:
    """Return ``CLOUD`` for cloud model names, otherwise ``LOCAL``."""
    if model and "cloud" in model.lower():
        return "CLOUD"
    return "LOCAL"


def format_request(mode: str, req_id: str, prompt: str) -> str:
    """Encode an AskAFM clipboard request payload."""
    normalized_mode = "CLOUD" if mode.upper() == "CLOUD" else "LOCAL"
    return f"{REQ_PREFIX}{normalized_mode}||{req_id}||{prompt}"


def parse_response(raw: str, expected_id: str) -> str | None:
    """Decode ``JARVIS_RES||<UUID>||<RESPONSE>`` if it matches ``expected_id``."""
    if not raw.startswith(RES_PREFIX):
        return None
    body = raw[len(RES_PREFIX):]
    parts = body.split("||", 1)
    if len(parts) != 2:
        return None
    res_id, response_text = parts
    if res_id.strip() != expected_id:
        return None
    return response_text


def _messages_to_prompt(messages: list[dict[str, Any]]) -> str:
    """Flatten OpenAI chat messages into a single prompt string for AskAFM."""
    lines: list[str] = []
    for msg in messages:
        role = str(msg.get("role", "user")).strip().upper()
        content = msg.get("content", "")
        if isinstance(content, list):
            text_parts = [
                str(part.get("text", ""))
                for part in content
                if isinstance(part, dict) and part.get("type") == "text"
            ]
            content_str = "\n".join(text_parts)
        else:
            content_str = str(content)
        if content_str:
            lines.append(f"{role}: {content_str}")
    return "\n\n".join(lines)


def _pbcopy(text: str) -> None:
    subprocess.run(["pbcopy"], input=text, text=True, check=True)


def _pbpaste() -> str:
    proc = subprocess.run(["pbpaste"], capture_output=True, text=True, check=True)
    return proc.stdout


def _trigger_shortcut(shortcut_name: str = SHORTCUT_NAME) -> None:
    url = f"shortcuts://run-shortcut?name={shortcut_name}"
    subprocess.run(["open", url], check=True)


def ask_afm_via_clipboard(
    prompt: str,
    *,
    mode: str = "LOCAL",
    timeout: float = BRIDGE_TIMEOUT_SECONDS,
) -> str:
    """Send ``prompt`` to Apple Intelligence via the AskAFM Shortcut bridge."""
    req_id = str(uuid.uuid4())
    payload = format_request(mode, req_id, prompt)
    _pbcopy(payload)
    _trigger_shortcut()

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        raw = _pbpaste()
        parsed = parse_response(raw, req_id)
        if parsed is not None:
            return parsed
        time.sleep(POLL_INTERVAL_SECONDS)

    raise TimeoutError(
        f"Timed out after {timeout:.0f}s waiting for {SHORTCUT_NAME} clipboard response."
    )


def run_cli_ask(model: str, prompt: str, *, engine: str | None = None) -> str:
    """Execute ``jarvis_ios.py ask --engine <engine> --model <model> <prompt>`` and return output."""
    launcher = Path(__file__).resolve().with_name("jarvis_ios.py")
    selected_engine = engine or ("apple_fm" if "askafm" in model.lower() else None)
    cmd = [sys.executable, str(launcher), "ask"]
    if selected_engine:
        cmd.extend(["--engine", selected_engine])
    cmd.extend(["--model", model, prompt])
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        detail = proc.stderr.strip() or proc.stdout.strip() or f"exit code {proc.returncode}"
        raise RuntimeError(f"jarvis_ios.py failed: {detail}")
    return proc.stdout.strip()


def _models_payload() -> dict[str, Any]:
    return {
        "object": "list",
        "data": [
            {"id": "AskAFM", "object": "model", "owned_by": "apple-on-device"},
            {"id": "AskAFMCloud", "object": "model", "owned_by": "apple-pcc"},
        ],
    }


def _completion_payload(model: str, text: str, stream: bool = False) -> tuple[str, bytes]:
    completion_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"
    created = int(time.time())
    if stream:
        chunk = {
            "id": completion_id,
            "object": "chat.completion.chunk",
            "created": created,
            "model": model,
            "choices": [
                {"index": 0, "delta": {"role": "assistant", "content": text}, "finish_reason": "stop"}
            ],
        }
        sse = f"data: {json.dumps(chunk)}\n\ndata: [DONE]\n\n".encode("utf-8")
        return "text/event-stream; charset=utf-8", sse
    body = json.dumps(
        {
            "id": completion_id,
            "object": "chat.completion",
            "created": created,
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": text},
                    "finish_reason": "stop",
                }
            ],
        }
    ).encode("utf-8")
    return "application/json; charset=utf-8", body


def _resolve_static_asset(
    static_root: Path | None,
    request_path: str,
    accept_encoding: str = "",
) -> tuple[Path, dict[str, str]] | None:
    """Resolve a static file or SPA ``index.html`` with ``.gz`` & traversal checks."""
    if static_root is None:
        return None
    clean_rel = request_path.lstrip("/").split("?", 1)[0]
    resolved_root = static_root.resolve()

    if clean_rel:
        candidate = (static_root / clean_rel).resolve()
        if candidate.is_relative_to(resolved_root):
            gz_candidate = candidate.with_name(candidate.name + ".gz")
            is_data = clean_rel.startswith("data/") or clean_rel.endswith(".json")
            headers = {
                "Cache-Control": (
                    "no-cache, must-revalidate" if is_data else "public, max-age=31536000, immutable"
                )
            }
            if "gzip" in accept_encoding.lower() and gz_candidate.is_file():
                mime, _ = mimetypes.guess_type(str(candidate))
                headers["Content-Encoding"] = "gzip"
                headers["Content-Type"] = mime or "application/octet-stream"
                return gz_candidate, headers
            if candidate.is_file():
                mime, _ = mimetypes.guess_type(str(candidate))
                if mime:
                    headers["Content-Type"] = mime
                return candidate, headers

    # Strict SPA fallback: do not serve index.html for /api/* or missing file extensions
    last_segment = clean_rel.split("/")[-1] if clean_rel else ""
    if clean_rel.startswith("api/") or ("." in last_segment and last_segment != "index.html"):
        return None

    index_file = static_root / "index.html"
    if index_file.is_file():
        return index_file, {
            "Content-Type": "text/html; charset=utf-8",
            "Cache-Control": "no-cache",
        }
    return None


class JarvisBridgeHandler(BaseHTTPRequestHandler):
    """HTTP request handler for the OpenJarvis iPadOS bridge (stdlib fallback)."""

    server_version = "OpenJarvis-iOS-Bridge/2.0"
    static_dir: Path | None = None

    def _send_cors_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "*")

    def _send_bytes(
        self,
        status: int,
        content_type: str,
        body: bytes,
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self._send_cors_headers()
        if extra_headers:
            for k, v in extra_headers.items():
                if k.lower() not in ("content-type", "content-length"):
                    self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload).encode("utf-8")
        self._send_bytes(status, "application/json; charset=utf-8", body)

    def _send_html(self, status: int, html: str) -> None:
        self._send_bytes(status, "text/html; charset=utf-8", html.encode("utf-8"))

    def _read_json_body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length) if length > 0 else b"{}"
        return json.loads(raw.decode("utf-8"))

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(HTTPStatus.NO_CONTENT)
        self._send_cors_headers()
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0]
        if path == "/v1/models":
            self._send_json(HTTPStatus.OK, _models_payload())
            return
        if path in ("/shutdown", "/api/v1/system/shutdown"):
            self._send_json(HTTPStatus.OK, {"status": "shutting_down"})
            threading.Thread(target=self.server.shutdown, daemon=True).start()
            return

        static_root = self.static_dir if self.static_dir is not None else resolve_static_dir()
        resolved = _resolve_static_asset(
            static_root, path, self.headers.get("Accept-Encoding", "")
        )
        if resolved is not None:
            file_path, headers = resolved
            content_type = headers.get("Content-Type", "application/octet-stream")
            self._send_bytes(HTTPStatus.OK, content_type, file_path.read_bytes(), headers)
            return

        if path in ("/", "/index.html"):
            self._send_html(HTTPStatus.OK, _MOBILE_UI_HTML)
        else:
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "Not found"})

    def do_POST(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0]
        try:
            body = self._read_json_body()
        except json.JSONDecodeError as exc:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": f"Invalid JSON: {exc}"})
            return

        if path == "/api/chat":
            model = str(body.get("model") or "AskAFM")
            prompt = str(body.get("prompt") or "").strip()
            if not prompt:
                self._send_json(HTTPStatus.BAD_REQUEST, {"error": "Missing 'prompt'"})
                return
            try:
                answer = run_cli_ask(model, prompt)
                self._send_json(HTTPStatus.OK, {"model": model, "response": answer})
            except Exception as exc:
                self._send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": str(exc)})
            return

        if path == "/v1/chat/completions":
            model = str(body.get("model") or "AskAFM")
            messages = body.get("messages")
            if not isinstance(messages, list) or not messages:
                self._send_json(HTTPStatus.BAD_REQUEST, {"error": "Missing 'messages' list"})
                return
            prompt = _messages_to_prompt(messages)
            mode = resolve_mode(model)
            try:
                text = ask_afm_via_clipboard(prompt, mode=mode)
            except TimeoutError as exc:
                self._send_json(HTTPStatus.GATEWAY_TIMEOUT, {"error": str(exc)})
                return
            except Exception as exc:
                self._send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": str(exc)})
                return

            content_type, payload = _completion_payload(
                model, text, stream=bool(body.get("stream"))
            )
            self._send_bytes(HTTPStatus.OK, content_type, payload)
            return

        self._send_json(HTTPStatus.NOT_FOUND, {"error": "Not found"})

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        sys.stderr.write(f"[jarvis_server] {format % args}\n")


async def _auto_launch_browser_async(host: str, port: int) -> None:
    """Wait 1s and launch a-Shell's ``internalbrowser`` pointing at the server."""
    await asyncio.sleep(1.0)
    if os.environ.get("JARVIS_IOS_AUTO_LAUNCH", "1") == "0":
        return
    url = f"http://{host}:{port}/"
    if is_ashell():
        await asyncio.to_thread(open_in_internal_browser, url)


async def start_backend_server_async(
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    *,
    static_dir: Path | str | None = None,
    auto_launch: bool = True,
) -> None:
    """Start the ``aiohttp`` iPadOS HTTP server (mirroring ``comic_tools``)."""
    from aiohttp import web

    _patch_aiohttp_tcp_keepalive()

    ios = is_ashell()
    if ios and not os.environ.get("JARVIS_IOS_DEBUG"):
        logging.getLogger("aiohttp.access").setLevel(logging.WARNING)
        access_log = None
    else:
        access_log = logging.getLogger("aiohttp.access")

    static_root = resolve_static_dir(static_dir)
    shutdown_event = asyncio.Event()

    @web.middleware
    async def cors_middleware(request: web.Request, handler: Any) -> web.StreamResponse:
        if request.method == "OPTIONS":
            resp: web.StreamResponse = web.Response(status=204)
        else:
            resp = await handler(request)
        resp.headers["Access-Control-Allow-Origin"] = "*"
        resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        resp.headers["Access-Control-Allow-Headers"] = "*"
        return resp

    async def handle_models(_request: web.Request) -> web.Response:
        return web.json_response(_models_payload())

    async def handle_shutdown(_request: web.Request) -> web.Response:
        asyncio.get_running_loop().call_later(0.1, shutdown_event.set)
        return web.json_response({"status": "shutting_down"})

    async def handle_api_chat(request: web.Request) -> web.Response:
        try:
            body = await request.json()
        except Exception as exc:
            return web.json_response({"error": f"Invalid JSON: {exc}"}, status=400)
        model = str(body.get("model") or "AskAFM")
        prompt = str(body.get("prompt") or "").strip()
        if not prompt:
            return web.json_response({"error": "Missing 'prompt'"}, status=400)
        try:
            os.environ["OPENJARVIS_APPLE_FM_HOST"] = f"http://{host}:{bound_port}"
            answer = await asyncio.to_thread(run_cli_ask, model, prompt)
            return web.json_response({"model": model, "response": answer})
        except Exception as exc:
            return web.json_response({"error": str(exc)}, status=500)

    async def handle_chat_completions(request: web.Request) -> web.Response:
        try:
            body = await request.json()
        except Exception as exc:
            return web.json_response({"error": f"Invalid JSON: {exc}"}, status=400)
        model = str(body.get("model") or "AskAFM")
        messages = body.get("messages")
        if not isinstance(messages, list) or not messages:
            return web.json_response({"error": "Missing 'messages' list"}, status=400)
        prompt = _messages_to_prompt(messages)
        mode = resolve_mode(model)
        try:
            text = await asyncio.to_thread(ask_afm_via_clipboard, prompt, mode=mode)
        except TimeoutError as exc:
            return web.json_response({"error": str(exc)}, status=504)
        except Exception as exc:
            return web.json_response({"error": str(exc)}, status=500)

        content_type, payload = _completion_payload(
            model, text, stream=bool(body.get("stream"))
        )
        return web.Response(body=payload, content_type=content_type.split(";")[0])

    async def handle_spa_or_ui(request: web.Request) -> web.StreamResponse:
        resolved = _resolve_static_asset(
            static_root, request.path, request.headers.get("Accept-Encoding", "")
        )
        if resolved is not None:
            file_path, headers = resolved
            return web.FileResponse(file_path, headers=headers)
        if request.path in ("/", "/index.html"):
            return web.Response(text=_MOBILE_UI_HTML, content_type="text/html")
        return web.json_response({"error": "Not found"}, status=404)

    app = web.Application(middlewares=[cors_middleware])
    app.router.add_get("/v1/models", handle_models)
    app.router.add_get("/shutdown", handle_shutdown)
    app.router.add_get("/api/v1/system/shutdown", handle_shutdown)
    app.router.add_post("/api/chat", handle_api_chat)
    app.router.add_post("/v1/chat/completions", handle_chat_completions)
    app.router.add_get("/{tail:.*}", handle_spa_or_ui)

    runner = web.AppRunner(app, access_log=access_log)
    await runner.setup()

    bound_port = port
    trials = PORT_BIND_TRIALS
    while trials > 0:
        try:
            site = web.TCPSite(runner, host, bound_port)
            await site.start()
            break
        except OSError:
            sys.stderr.write(
                f"[jarvis_server] port {bound_port} already used, trying {bound_port + 1}\n"
            )
            trials -= 1
            if trials == 0:
                await runner.cleanup()
                raise
            bound_port += 1

    print(f"OpenJarvis iOS bridge listening on http://{host}:{bound_port}", flush=True)

    background_tasks: set[asyncio.Task[Any]] = set()
    if auto_launch:
        launch_task = asyncio.create_task(_auto_launch_browser_async(host, bound_port))
        background_tasks.add(launch_task)
        launch_task.add_done_callback(background_tasks.discard)

    loop = asyncio.get_running_loop()
    cli_task: asyncio.Task[Any] | None = None

    async def _listen_cli_shutdown() -> None:
        try:
            reader = asyncio.StreamReader()
            protocol = asyncio.StreamReaderProtocol(reader)
            await loop.connect_read_pipe(lambda: protocol, sys.stdin)
            while not shutdown_event.is_set():
                line = await reader.readline()
                if not line:
                    break
                if line.decode(errors="ignore").strip().lower() in ("q", "quit", "\x03"):
                    shutdown_event.set()
                    break
        except (asyncio.CancelledError, OSError, ValueError):
            pass

    if not ios and sys.stdin.isatty():
        cli_task = asyncio.create_task(_listen_cli_shutdown())
        background_tasks.add(cli_task)

    if not ios:
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, shutdown_event.set)
            except (NotImplementedError, ValueError):
                pass

    try:
        await shutdown_event.wait()
    finally:
        if cli_task is not None:
            cli_task.cancel()
        for task in list(background_tasks):
            if not task.done():
                task.cancel()
        if background_tasks:
            await asyncio.gather(*background_tasks, return_exceptions=True)
        await runner.cleanup()


def _serve_stdlib(
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    *,
    static_dir: Path | str | None = None,
    auto_launch: bool = True,
) -> None:
    """Start the stdlib ``ThreadingHTTPServer`` fallback with port-retry."""
    JarvisBridgeHandler.static_dir = resolve_static_dir(static_dir)
    server: ThreadingHTTPServer | None = None
    bound_port = port
    for trial in range(PORT_BIND_TRIALS):
        try:
            server = ThreadingHTTPServer((host, bound_port), JarvisBridgeHandler)
            break
        except OSError:
            sys.stderr.write(
                f"[jarvis_server] port {bound_port} already used, trying {bound_port + 1}\n"
            )
            if trial == PORT_BIND_TRIALS - 1:
                raise
            bound_port += 1

    assert server is not None
    print(f"OpenJarvis iOS bridge listening on http://{host}:{bound_port}", flush=True)

    if auto_launch and is_ashell() and os.environ.get("JARVIS_IOS_AUTO_LAUNCH", "1") != "0":
        def _delayed_open() -> None:
            time.sleep(1.0)
            open_in_internal_browser(f"http://{host}:{bound_port}/")

        threading.Thread(target=_delayed_open, daemon=True).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def serve(
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    *,
    static_dir: Path | str | None = None,
    auto_launch: bool = True,
) -> None:
    """Start the iPadOS HTTP bridge server (``aiohttp`` when installed, else stdlib)."""
    try:
        import aiohttp  # noqa: F401
    except ImportError:
        _serve_stdlib(host=host, port=port, static_dir=static_dir, auto_launch=auto_launch)
        return

    try:
        asyncio.run(
            start_backend_server_async(
                host=host, port=port, static_dir=static_dir, auto_launch=auto_launch
            )
        )
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    serve()
