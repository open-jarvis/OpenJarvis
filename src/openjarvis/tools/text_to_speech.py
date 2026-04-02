"""Text-to-speech tool — synthesize text to audio via configurable TTS backend."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from openjarvis.core.registry import ToolRegistry, TTSRegistry
from openjarvis.core.types import ToolResult
from openjarvis.tools._stubs import BaseTool, ToolSpec


@ToolRegistry.register("text_to_speech")
class TextToSpeechTool(BaseTool):
    """Synthesize text into spoken audio using a TTS backend."""

    tool_id = "text_to_speech"
    is_local = False

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="text_to_speech",
            description=(
                "Convert text to spoken audio. Returns the file path to the "
                "generated audio file."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": "The text to synthesize into speech.",
                    },
                    "voice_id": {
                        "type": "string",
                        "description": "Voice identifier for the TTS backend.",
                    },
                    "backend": {
                        "type": "string",
                        "description": "TTS backend (cartesia, kokoro, openai_tts).",
                    },
                    "output_dir": {
                        "type": "string",
                        "description": "Directory to save the audio file.",
                    },
                },
                "required": ["text"],
            },
            category="audio",
            timeout_seconds=120.0,
        )

    def execute(self, **params: Any) -> ToolResult:
        text = params.get("text", "")
        voice_id = params.get("voice_id", "")
        backend_key = params.get("backend", "cartesia")
        output_dir = params.get("output_dir", "")

        if not text:
            return ToolResult(
                tool_name="text_to_speech",
                content="No text provided.",
                success=False,
            )

        if not TTSRegistry.contains(backend_key):
            return ToolResult(
                tool_name="text_to_speech",
                content=f"TTS backend '{backend_key}' not available.",
                success=False,
            )

        backend_cls = TTSRegistry.get(backend_key)
        backend = backend_cls()

        result = backend.synthesize(text, voice_id=voice_id)

        # Save to file
        if output_dir:
            out_dir = Path(output_dir)
        else:
            out_dir = Path(tempfile.mkdtemp(prefix="jarvis-tts-"))

        out_dir.mkdir(parents=True, exist_ok=True)
        ext = result.format or "mp3"
        audio_path = out_dir / f"digest.{ext}"
        result.save(audio_path)

        return ToolResult(
            tool_name="text_to_speech",
            content=str(audio_path),
            success=True,
            metadata={
                "audio_path": str(audio_path),
                "format": ext,
                "duration_seconds": result.duration_seconds,
                "voice_id": result.voice_id,
                "backend": backend_key,
            },
        )
