"""Free, loopback-only Jarvis TTS service.

Uses Piper offline by default. Optionally uses Chatterbox Nano with a user-
supplied, consented reference WAV. Nothing is uploaded to third parties.
"""
from __future__ import annotations

import importlib.util
import io
import json
import os
import tempfile
import threading
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

VOICE_DIR = Path.home() / ".openjarvis" / "voices"
PIPER_MODEL = VOICE_DIR / "en_GB-alan-medium.onnx"
REFERENCE = VOICE_DIR / "jarvis_reference.wav"
ENABLE_CLONE = os.environ.get("OPENJARVIS_ENABLE_VOICE_CLONE") == "1"
_ALLOWED_ORIGINS = {None, "http://localhost:4700", "http://127.0.0.1:4700"}
_LOCK = threading.Lock()
_piper = None
_chatterbox = None
_clone_failed = False


def _make_piper(text: str, target: Path) -> str:
    global _piper
    from piper import PiperVoice
    if _piper is None:
        _piper = PiperVoice.load(str(PIPER_MODEL))
    with wave.open(str(target), "wb") as out:
        _piper.synthesize_wav(text, out)
    return "Piper (British offline)"


def _make_clone(text: str, target: Path) -> str:
    global _chatterbox
    import torch
    import torchaudio as ta
    from chatterbox.tts_turbo import ChatterboxTurboTTS
    if _chatterbox is None:
        device = "cuda" if torch.cuda.is_available() else "cpu"
        _chatterbox = ChatterboxTurboTTS.from_pretrained(device=device, nano=True)
    audio = _chatterbox.generate(text, audio_prompt_path=str(REFERENCE))
    ta.save(str(target), audio.detach().cpu(), _chatterbox.sr)
    return "Chatterbox Nano (local reference-matched)"


def _ready() -> bool:
    return (
        PIPER_MODEL.is_file()
        and PIPER_MODEL.with_suffix(".onnx.json").is_file()
        and importlib.util.find_spec("piper") is not None
    )


def _synthesize(text: str) -> tuple[bytes, str]:
    global _clone_failed
    with _LOCK, tempfile.TemporaryDirectory() as directory:
        wav_path = Path(directory) / "speech.wav"
        if ENABLE_CLONE and REFERENCE.is_file() and not _clone_failed:
            try:
                engine = _make_clone(text, wav_path)
                return wav_path.read_bytes(), engine
            except Exception as exc:
                _clone_failed = True
                print("Local clone unavailable; using Piper:", type(exc).__name__, exc)
        engine = _make_piper(text, wav_path)
        return wav_path.read_bytes(), engine


class VoiceHandler(BaseHTTPRequestHandler):
    def _respond(self, status: int, body: bytes, mime: str = "application/json",
                 engine: str | None = None) -> None:
        self.send_response(status)
        origin = self.headers.get("Origin")
        if origin in _ALLOWED_ORIGINS and origin:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
        self.send_header("Content-Type", mime)
        if engine:
            self.send_header("X-Jarvis-Voice-Backend", engine)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path != "/health":
            return self._respond(404, b'{"error":"not found"}')
        data = {"ready": _ready(), "clone_requested": ENABLE_CLONE,
                "reference_available": REFERENCE.is_file()}
        self._respond(200, json.dumps(data).encode())

    def do_POST(self) -> None:
        if self.path != "/speak":
            return self._respond(404, b'{"error":"not found"}')
        if self.headers.get("Origin") not in _ALLOWED_ORIGINS:
            return self._respond(403, b'{"error":"origin not permitted"}')
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 4096:
                return self._respond(413, b'{"error":"request too large"}')
            data = json.loads(self.rfile.read(length))
            if not isinstance(data, dict):
                raise ValueError("JSON object required")
            text = data.get("text")
            if not isinstance(text, str) or not text.strip() or len(text) > 600:
                raise ValueError("Text must be 1 to 600 characters")
            audio, engine = _synthesize(text.strip())
            self._respond(200, audio, "audio/wav", engine)
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            self._respond(400, json.dumps({"error": str(exc)}).encode())
        except Exception as exc:
            print("Offline voice error:", type(exc).__name__, exc)
            self._respond(503, b'{"error":"local voice synthesis unavailable"}')

    def log_message(self, format: str, *args: object) -> None:
        # Avoid retaining potentially sensitive spoken text in access logs.
        pass


def main() -> None:
    if not _ready():
        raise SystemExit(
            "Piper model missing. Run jarvis_voice_setup\\01_Setup_Offline_Voice.bat"
        )
    server = ThreadingHTTPServer(("127.0.0.1", 4701), VoiceHandler)
    print("Offline Jarvis voice ready: http://127.0.0.1:4701/health")
    print("Voice cloning is", "enabled" if ENABLE_CLONE else "disabled (Piper only)")
    print("Keep this window open when using Jarvis. Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
