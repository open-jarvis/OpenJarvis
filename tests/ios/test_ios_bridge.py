"""Tests for the iPadOS (a-Shell) launcher and HTTP clipboard bridge."""

from __future__ import annotations

import importlib.util
import json
import sys
import threading
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_module(name: str, rel_path: str):
    spec = importlib.util.spec_from_file_location(name, REPO_ROOT / rel_path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


jarvis_ios = _load_module("jarvis_ios", "ios/jarvis_ios.py")
jarvis_server = _load_module("jarvis_server", "ios/jarvis_server.py")


def test_install_ios_mocks_registers_native_stubs(monkeypatch):
    for mod_name in ("zeus_apple_silicon", "apple_fm_sdk", "psutil"):
        monkeypatch.delitem(sys.modules, mod_name, raising=False)

    installed = jarvis_ios.install_ios_mocks(force=True)
    assert set(installed) == {"zeus_apple_silicon", "apple_fm_sdk", "psutil"}

    import apple_fm_sdk
    import psutil
    import zeus_apple_silicon

    mon = zeus_apple_silicon.AppleEnergyMonitor()
    mon.begin_window("test")
    metrics = mon.end_window("test")
    assert metrics.cpu_total_mj == 0.0
    assert apple_fm_sdk.SystemLanguageModel.is_available is False
    assert psutil.wait_procs([]) == ([], [])


def test_clipboard_protocol_roundtrip():
    req = jarvis_server.format_request("CLOUD", "abc-123", "Hello iPad")
    assert req == "JARVIS_REQ||CLOUD||abc-123||Hello iPad"

    assert jarvis_server.parse_response("JARVIS_RES||abc-123||Hi there", "abc-123") == "Hi there"
    assert jarvis_server.parse_response("JARVIS_RES||wrong-id||Hi there", "abc-123") is None
    assert jarvis_server.parse_response("JARVIS_REQ||LOCAL||abc-123||Hi", "abc-123") is None
    assert jarvis_server.resolve_mode("AskAFM") == "LOCAL"
    assert jarvis_server.resolve_mode("AskAFMCloud") == "CLOUD"


def test_http_bridge_endpoints():
    server = ThreadingHTTPServer(("127.0.0.1", 0), jarvis_server.JarvisBridgeHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{port}"

    try:
        with urllib.request.urlopen(f"{base}/") as resp:
            assert resp.status == 200
            assert "OpenJarvis iPadOS" in resp.read().decode("utf-8")

        with urllib.request.urlopen(f"{base}/v1/models") as resp:
            models = json.loads(resp.read().decode("utf-8"))
            ids = {m["id"] for m in models["data"]}
            assert ids == {"AskAFM", "AskAFMCloud"}

        with patch.object(jarvis_server, "ask_afm_via_clipboard", return_value="Mocked AFM reply"):
            req = urllib.request.Request(
                f"{base}/v1/chat/completions",
                data=json.dumps(
                    {"model": "AskAFMCloud", "messages": [{"role": "user", "content": "Hi"}]}
                ).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                assert data["choices"][0]["message"]["content"] == "Mocked AFM reply"

        with patch.object(jarvis_server, "run_cli_ask", return_value="CLI reply"):
            req = urllib.request.Request(
                f"{base}/api/chat",
                data=json.dumps({"model": "AskAFM", "prompt": "Summarize"}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                assert data == {"model": "AskAFM", "response": "CLI reply"}
    finally:
        server.shutdown()
        server.server_close()


def test_static_spa_and_gzip_serving(tmp_path):
    import gzip

    (tmp_path / "index.html").write_text("<html><body>SPA Root</body></html>", encoding="utf-8")
    assets = tmp_path / "assets"
    assets.mkdir()
    js_bytes = b"console.log('openjarvis');"
    (assets / "app.js").write_bytes(js_bytes)
    (assets / "app.js.gz").write_bytes(gzip.compress(js_bytes))

    jarvis_server.JarvisBridgeHandler.static_dir = tmp_path
    server = ThreadingHTTPServer(("127.0.0.1", 0), jarvis_server.JarvisBridgeHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{port}"

    try:
        with urllib.request.urlopen(f"{base}/dashboard/overview") as resp:
            assert resp.status == 200
            assert "SPA Root" in resp.read().decode("utf-8")
            assert resp.headers.get("Access-Control-Allow-Origin") == "*"

        req = urllib.request.Request(
            f"{base}/assets/app.js",
            headers={"Accept-Encoding": "gzip"},
        )
        with urllib.request.urlopen(req) as resp:
            assert resp.status == 200
            assert resp.headers.get("Content-Encoding") == "gzip"
            assert gzip.decompress(resp.read()) == js_bytes
    finally:
        jarvis_server.JarvisBridgeHandler.static_dir = None
        server.shutdown()
        server.server_close()


def test_ashell_detection_and_internal_browser(monkeypatch):
    monkeypatch.setenv("TERM_PROGRAM", "a-Shell")
    assert jarvis_server.is_ashell() is True

    called: list[bytes] = []
    monkeypatch.setattr(jarvis_server, "_get_ios_system", lambda: lambda cmd: called.append(cmd) or 0)
    assert jarvis_server.open_in_internal_browser("http://127.0.0.1:8085/") is True
    assert called == [b"internalbrowser 'http://127.0.0.1:8085/'"]


def test_configure_ios_pythonpath(monkeypatch):
    src_str = str(REPO_ROOT / "src")
    monkeypatch.setenv("OPENJARVIS_REPO_ROOT", str(REPO_ROOT))
    if src_str in sys.path:
        sys.path.remove(src_str)
    resolved = jarvis_ios.configure_ios_pythonpath()
    assert resolved == (REPO_ROOT / "src").resolve()
    assert sys.path[0] == str(resolved)


