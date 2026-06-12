"""Edge TTS backend — free Microsoft neural voices via edge-tts."""

from __future__ import annotations

import asyncio
import concurrent.futures
import queue
import threading
from typing import Iterator, List

from openjarvis.core.registry import TTSRegistry
from openjarvis.speech.tts import TTSBackend, TTSResult

_STREAM_SENTINEL = object()

_DEFAULT_VOICE = "en-US-GuyNeural"

_VOICE_ALIASES = {
    "onyx": "en-US-GuyNeural",
    "nova": "en-US-JennyNeural",
    "alloy": "en-US-ChristopherNeural",
    "echo": "en-US-EricNeural",
    "fable": "en-GB-SoniaNeural",
    "shimmer": "en-US-AriaNeural",
}


@TTSRegistry.register("edge_tts")
class EdgeTTSBackend(TTSBackend):
    """Microsoft Edge TTS — free, no API key, requires network."""

    backend_id = "edge_tts"

    def _resolve_voice(self, voice_id: str) -> str:
        if not voice_id:
            return _DEFAULT_VOICE
        if voice_id in _VOICE_ALIASES:
            return _VOICE_ALIASES[voice_id]
        return voice_id

    def _speed_to_rate(self, speed: float) -> str:
        pct = int(round((speed - 1.0) * 100))
        if pct >= 0:
            return f"+{pct}%"
        return f"{pct}%"

    async def _synthesize_async(
        self,
        text: str,
        *,
        voice: str,
        speed: float,
    ) -> bytes:
        import edge_tts

        communicate = edge_tts.Communicate(
            text,
            voice,
            rate=self._speed_to_rate(speed),
        )
        audio = bytearray()
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                audio.extend(chunk["data"])
        return bytes(audio)

    def _run_async(self, coro) -> bytes:
        """Run async edge-tts code from sync callers (including FastAPI)."""
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(coro)

        def _thread_main() -> bytes:
            loop = asyncio.new_event_loop()
            try:
                asyncio.set_event_loop(loop)
                return loop.run_until_complete(coro)
            finally:
                loop.close()

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(_thread_main).result(timeout=120)

    def synthesize(
        self,
        text: str,
        *,
        voice_id: str = "",
        speed: float = 1.0,
        output_format: str = "mp3",
    ) -> TTSResult:
        voice = self._resolve_voice(voice_id)
        audio = self._run_async(
            self._synthesize_async(text, voice=voice, speed=speed)
        )
        return TTSResult(
            audio=audio,
            format=output_format or "mp3",
            voice_id=voice,
            metadata={"backend": "edge_tts"},
        )

    def synthesize_stream(
        self,
        text: str,
        *,
        voice_id: str = "",
        speed: float = 1.0,
        output_format: str = "mp3",
    ) -> Iterator[bytes]:
        """Stream MP3 chunks as edge-tts produces them.

        edge-tts exposes an async chunk stream. We pump it on a dedicated
        thread with its own event loop (so it works whether or not the caller
        is already inside a running loop) and hand chunks back through a bounded
        queue to a plain synchronous iterator.
        """
        voice = self._resolve_voice(voice_id)
        rate = self._speed_to_rate(speed)
        chunks: "queue.Queue[object]" = queue.Queue(maxsize=64)

        async def _produce() -> None:
            import edge_tts

            communicate = edge_tts.Communicate(text, voice, rate=rate)
            async for chunk in communicate.stream():
                if chunk["type"] == "audio" and chunk.get("data"):
                    chunks.put(bytes(chunk["data"]))

        def _thread_main() -> None:
            loop = asyncio.new_event_loop()
            try:
                asyncio.set_event_loop(loop)
                loop.run_until_complete(_produce())
            except Exception as exc:  # surface to the consumer
                chunks.put(exc)
            finally:
                loop.close()
                chunks.put(_STREAM_SENTINEL)

        worker = threading.Thread(target=_thread_main, daemon=True)
        worker.start()

        while True:
            item = chunks.get()
            if item is _STREAM_SENTINEL:
                break
            if isinstance(item, Exception):
                raise item
            yield item  # type: ignore[misc]

    def available_voices(self) -> List[str]:
        return list(_VOICE_ALIASES.keys()) + [_DEFAULT_VOICE]

    def health(self) -> bool:
        try:
            import edge_tts  # noqa: F401

            return True
        except ImportError:
            return False
