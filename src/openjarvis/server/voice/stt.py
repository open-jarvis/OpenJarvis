"""Gemini Live, used only for the transcription it produces."""

from __future__ import annotations

import asyncio
import os
from typing import Any

from pipecat.frames.frames import (
    Frame,
    LLMFullResponseEndFrame,
    LLMFullResponseStartFrame,
    LLMTextFrame,
    TranscriptionFrame,
    TTSAudioRawFrame,
    TTSStartedFrame,
    TTSStoppedFrame,
    TTSTextFrame,
)
from pipecat.processors.frame_processor import FrameDirection
from pipecat.services.google.gemini_live.llm import (
    GeminiLiveLLMService,
    GeminiModalities,
    GeminiVADParams,
)

from openjarvis.server.voice.gate import (
    DEFAULT_GEMINI_LIVE_MODEL,
    GEMINI_LIVE_MODEL_ENV,
)

# Gemini answers as well as transcribes. The OpenJarvis Agent is the sole
# authority over answers, so everything Gemini generates is dropped here and
# only the transcription continues down the pipeline. Listed explicitly rather
# than allow-listing transcription, so control and system frames — including
# InterruptionFrame, which barge-in depends on — always pass through.
#
# TTSTextFrame is the model's output transcription: the spoken answer Gemini
# generated as audio. It would reach the assistant aggregator and be written
# into history as an assistant turn that the Agent never said.
_GENERATED_BY_GEMINI = (
    LLMTextFrame,
    LLMFullResponseStartFrame,
    LLMFullResponseEndFrame,
    TTSTextFrame,
    TTSAudioRawFrame,
    TTSStartedFrame,
    TTSStoppedFrame,
)

# One utterance reaches us as several TranscriptionFrames: pipecat splits the
# Gemini transcript on every end-of-sentence marker
# (``_handle_msg_input_transcription`` in pipecat's gemini_live/llm.py). The
# realtime pattern it was written for puts the aggregator *before* the service,
# where the pieces rejoin inside one service-driven turn. This cascade puts it
# *after*: the first sentence satisfies ``wait_for_transcript`` and closes the
# user turn, and every later sentence opens a new one — so a two-sentence
# utterance runs the Agent twice, the second run replaying the first answer
# from its own history. Rejoin the pieces before they leave.
#
# Whether more of the utterance is still coming is not a guess: pipecat keeps
# the unterminated remainder in ``_user_transcription_buffer`` and flushes it
# 0.5 s later. An empty buffer means the utterance is whole, so the common
# case — one sentence, nothing held back — is forwarded with no delay at all.
# The window below is only the backstop for a remainder whose flush never
# arrives (a dropped connection), so it has to outlast pipecat's own 0.5 s.
_TRANSCRIPTION_MERGE_WINDOW_S = 0.7

# How long Gemini waits on silence before it calls the user's turn over, and
# how much audio it keeps from before speech started.
#
# Measured on this deployment: turn detection was 1.06s of a 2.35s perceived
# latency, and it is the only part of that a setting can move. Gemini's window
# and the local SpeechTimeoutUserTurnStopStrategy run in parallel, so lowering
# one alone changes nothing — USER_SPEECH_TIMEOUT_S in pipecat_voice_pipeline
# is the other half and moves with this.
#
# Named rather than inlined because this is a felt tradeoff, not an
# implementation detail: too low and it cuts off a speaker who pauses
# mid-sentence, and the only way to know is to listen.
GEMINI_SILENCE_DURATION_MS = 450
GEMINI_PREFIX_PADDING_MS = 100


class GeminiLiveTranscriptionService(GeminiLiveLLMService):
    """Transcribe with Gemini Live; the Silero analyser owns barge-in.

    Gemini's own VAD stays **on**, which is what keeps transcription fast:
    with it disabled pipecat honours the activity-window contract and holds
    every sample back until the local turn strategy declares the turn over, so
    Gemini only starts listening once the user has already stopped — measured
    at 1-3s to a transcript against 0.5-1s streaming continuously.

    Turn detection and barge-in remain local and unaffected: the Silero
    analyser on the user aggregator emits the interruption, independently of
    what Gemini decides about its own turns.
    """

    def __init__(self, *, api_key: str, **kwargs: Any) -> None:
        # The same model resolution the old runtime used, so the env override
        # keeps working: OPENJARVIS_GEMINI_LIVE_MODEL or the repo default.
        # pipecat's own default (a dated preview model) is not the one this
        # deployment is proven against.
        model = (
            os.environ.get(GEMINI_LIVE_MODEL_ENV, "").strip()
            or DEFAULT_GEMINI_LIVE_MODEL
        )
        settings = kwargs.pop("settings", None) or self.Settings(
            model=model,
            # AUDIO, not TEXT: the Live model rejects TEXT modality. Its
            # generated audio never reaches the speaker — the drop list in
            # push_frame sees to that.
            modalities=GeminiModalities.AUDIO,
            # Prefix padding and silence duration match the old runtime's
            # tuning, which is what this deployment's latency was measured on.
            vad=GeminiVADParams(
                prefix_padding_ms=GEMINI_PREFIX_PADDING_MS,
                silence_duration_ms=GEMINI_SILENCE_DURATION_MS,
            ),
        )
        super().__init__(api_key=api_key, settings=settings, **kwargs)
        self._pending_transcription: list[TranscriptionFrame] = []
        self._transcription_merge: asyncio.Task[None] | None = None

    async def _handle_session_ready(self, session: Any) -> None:
        await super()._handle_session_ready(session)
        # pipecat only accepts realtime input once it has received an
        # LLMContextFrame — the realtime pattern feeds the service from an
        # aggregator placed *before* it. Ours sits after it (the cascade order
        # this runtime is built on), so that frame never arrives and the
        # service would wait forever, discarding every activity signal.
        # With an empty context pipecat would mark itself ready immediately,
        # which is the state this pipeline is always in.
        self._ready_for_realtime_input = True

    async def push_frame(
        self, frame: Frame, direction: FrameDirection = FrameDirection.DOWNSTREAM
    ) -> None:
        """Forward everything except what Gemini generated as an answer."""
        if isinstance(frame, _GENERATED_BY_GEMINI):
            return
        if isinstance(frame, TranscriptionFrame):
            await self._merge_transcription(frame)
            return
        await super().push_frame(frame, direction)

    async def _merge_transcription(self, frame: TranscriptionFrame) -> None:
        """Hold a sentence back until the rest of the utterance has landed."""
        self._pending_transcription.append(frame)
        if self._transcription_merge is not None:
            self._transcription_merge.cancel()
            self._transcription_merge = None
        if not self._user_transcription_buffer:
            # Nothing held back upstream: this is the whole utterance, and
            # forwarding it now is what keeps the turn as fast as it was.
            await self._push_transcription()
            return
        self._transcription_merge = asyncio.create_task(self._backstop_flush())

    async def _backstop_flush(self) -> None:
        await asyncio.sleep(_TRANSCRIPTION_MERGE_WINDOW_S)
        await self._push_transcription()

    async def _push_transcription(self) -> None:
        pending = self._pending_transcription
        self._pending_transcription = []
        self._transcription_merge = None
        if not pending:
            return
        merged = pending[0]
        # pipecat slices its buffer contiguously, so the pieces concatenate
        # back into the utterance verbatim — leading spaces included.
        merged.text = "".join(part.text for part in pending)
        # The service pushes the user's transcript upstream, because pipecat's
        # realtime pattern places the aggregator before the service. Ours sits
        # after it — the cascade order the design assumes — so the transcript
        # must flow downstream to reach it. Without this redirect the Agent
        # never sees what was said.
        await super().push_frame(merged, FrameDirection.DOWNSTREAM)
