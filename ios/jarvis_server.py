"""HTTP Bridge Server for OpenJarvis on iPadOS (a-Shell).

Listens on ``127.0.0.1:8085`` and bridges OpenJarvis requests to Apple
Intelligence Foundation Models via the ``AskAFM`` Apple Shortcut using a
clipboard protocol (``pbcopy`` / ``pbpaste``):

- Request:  ``JARVIS_REQ||<MODE>||<UUID>||<PROMPT>``  (MODE = LOCAL | CLOUD)
- Response: ``JARVIS_RES||<UUID>||<RESPONSE>``

Endpoints:
- ``GET /``: Mobile-first Web UI with Local/Cloud model toggles.
- ``GET /v1/models``: OpenAI-compatible model listing.
- ``POST /api/chat``: Executes ``jarvis_ios.py ask --model <model> <prompt>``.
- ``POST /v1/chat/completions``: OpenAI-compatible chat completions bridged to
  ``shortcuts://run-shortcut?name=AskAFM``.
- ``GET /shutdown``: Clean server termination.
"""

from __future__ import annotations

import json
import os
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
SHORTCUT_NAME = os.environ.get("JARVIS_ASKAFM_SHORTCUT", "AskAFM")
BRIDGE_TIMEOUT_SECONDS = float(os.environ.get("JARVIS_IOS_TIMEOUT", "90.0"))
POLL_INTERVAL_SECONDS = 0.25

REQ_PREFIX = "JARVIS_REQ||"
RES_PREFIX = "JARVIS_RES||"

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


def run_cli_ask(model: str, prompt: str) -> str:
    """Execute ``jarvis_ios.py ask --model <model> <prompt>`` and return output."""
    launcher = Path(__file__).resolve().with_name("jarvis_ios.py")
    cmd = [sys.executable, str(launcher), "ask", "--model", model, prompt]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        detail = proc.stderr.strip() or proc.stdout.strip() or f"exit code {proc.returncode}"
        raise RuntimeError(f"jarvis_ios.py failed: {detail}")
    return proc.stdout.strip()


class JarvisBridgeHandler(BaseHTTPRequestHandler):
    """HTTP request handler for the OpenJarvis iPadOS bridge."""

    server_version = "OpenJarvis-iOS-Bridge/1.0"

    def _send_json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, status: int, html: str) -> None:
        body = html.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json_body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length) if length > 0 else b"{}"
        return json.loads(raw.decode("utf-8"))

    def do_GET(self) -> None:  # noqa: N802
        if self.path in ("/", "/index.html"):
            self._send_html(HTTPStatus.OK, _MOBILE_UI_HTML)
        elif self.path == "/v1/models":
            self._send_json(
                HTTPStatus.OK,
                {
                    "object": "list",
                    "data": [
                        {"id": "AskAFM", "object": "model", "owned_by": "apple-on-device"},
                        {"id": "AskAFMCloud", "object": "model", "owned_by": "apple-pcc"},
                    ],
                },
            )
        elif self.path == "/shutdown":
            self._send_json(HTTPStatus.OK, {"status": "shutting_down"})
            threading.Thread(target=self.server.shutdown, daemon=True).start()
        else:
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "Not found"})

    def do_POST(self) -> None:  # noqa: N802
        try:
            body = self._read_json_body()
        except json.JSONDecodeError as exc:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": f"Invalid JSON: {exc}"})
            return

        if self.path == "/api/chat":
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

        if self.path == "/v1/chat/completions":
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

            completion_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"
            created = int(time.time())

            if body.get("stream"):
                chunk = {
                    "id": completion_id,
                    "object": "chat.completion.chunk",
                    "created": created,
                    "model": model,
                    "choices": [{"index": 0, "delta": {"role": "assistant", "content": text}, "finish_reason": "stop"}],
                }
                sse = f"data: {json.dumps(chunk)}\n\ndata: [DONE]\n\n".encode("utf-8")
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "text/event-stream; charset=utf-8")
                self.send_header("Content-Length", str(len(sse)))
                self.end_headers()
                self.wfile.write(sse)
                return

            self._send_json(
                HTTPStatus.OK,
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
                },
            )
            return

        self._send_json(HTTPStatus.NOT_FOUND, {"error": "Not found"})

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        sys.stderr.write(f"[jarvis_server] {format % args}\n")


def serve(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> None:
    """Start the iPadOS HTTP bridge server."""
    server = ThreadingHTTPServer((host, port), JarvisBridgeHandler)
    print(f"OpenJarvis iOS bridge listening on http://{host}:{port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    serve()
