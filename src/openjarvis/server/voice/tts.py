"""The local VieNeu voice, as a Pipecat TTS service."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any

from pipecat.frames.frames import Frame, TTSAudioRawFrame
from pipecat.services.settings import TTSSettings
from pipecat.services.tts_service import TTSService


class VieNeuTTSService(TTSService):
    """Speak through the local VieNeu ONNX renderer.

    One voice serves both Vietnamese and English, so the service takes no
    language argument.
    """

    def __init__(self, renderer: Any, *, sample_rate: int, **kwargs: Any) -> None:
        # None, not unset: the artifact fixes the model, and one voice serves
        # both languages, so there is nothing to choose. Left NOT_GIVEN, the
        # base class logs an ERROR for each field on every session.
        kwargs.setdefault(
            "settings", TTSSettings(model=None, voice=None, language=None)
        )
        # push_start_frame/push_stop_frames let the base class open the audio
        # context and bracket the utterance with TTSStartedFrame and
        # TTSStoppedFrame, both stamped with context_id. Emitting them from
        # run_tts instead would leave that stamping wrong.
        super().__init__(
            sample_rate=sample_rate,
            push_start_frame=True,
            push_stop_frames=True,
            **kwargs,
        )
        self._renderer = renderer

    async def run_tts(self, text: str, context_id: str) -> AsyncGenerator[Frame, None]:
        """Yield each rendered chunk as soon as it exists."""
        async for chunk in self._renderer.stream_tts(text):
            # The chunk's own rate, not self.sample_rate: that one is resolved
            # from the pipeline at StartFrame and may differ from what VieNeu
            # actually rendered. Declaring the true rate is what lets the
            # output transport resample instead of playing it at the wrong
            # speed.
            yield TTSAudioRawFrame(
                audio=chunk.audio,
                sample_rate=chunk.sample_rate_hz,
                num_channels=chunk.channels,
            )
