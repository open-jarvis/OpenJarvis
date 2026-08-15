"""Compose one Pipecat pipeline for a Voice session."""

from __future__ import annotations

from typing import Any

# What VieNeu renders. The pipeline is told the same rate, and the output
# transport resamples from there if the peer negotiated something else.
VIENEU_SAMPLE_RATE_HZ = 48_000

# How long the local analyser waits on silence before it calls the turn over.
#
# Half of turn detection; the other half is GEMINI_SILENCE_DURATION_MS in
# pipecat_gemini_stt, and the two run in parallel, so they move together or
# not at all. Measured at 0.6s: turn detection took 1.06s of a 2.35s perceived
# latency. Lower is snappier and clips a speaker who pauses mid-sentence; the
# only way to tell which side of that line a value is on is to listen.
USER_SPEECH_TIMEOUT_S = 0.4


class VoiceLeaseBusy(RuntimeError):
    """Raised when a Voice session is already running."""

    def __init__(self, status: str, fallback: str | None = None) -> None:
        super().__init__(status)
        self.status = status
        self.fallback = fallback


def claim_voice_lease(
    sessions: Any, *, chat_thread_id: str, execution_binding: Any
) -> Any:
    """Take the single Voice lease, or refuse so the caller falls back to text."""
    result = sessions.start_session(
        chat_thread_id=chat_thread_id, execution_binding=execution_binding
    )
    if result.session is None:
        raise VoiceLeaseBusy(result.status, getattr(result, "fallback", None))
    return result.session


def build_voice_pipeline(
    *,
    connection: Any,
    binding: Any,
    renderer: Any,
    stt: Any,
    recall: tuple[Any, Any] | None = None,
) -> Any:
    """Wire transport, VAD, STT, Agent, and voice into one runnable worker.

    Returns the worker and the shared context, which the caller reads on
    teardown to write the conversation to the Chat thread.
    """
    from pipecat.audio.vad.silero import SileroVADAnalyzer
    from pipecat.pipeline.pipeline import Pipeline
    from pipecat.pipeline.worker import PipelineParams, PipelineWorker
    from pipecat.processors.aggregators.llm_context import LLMContext
    from pipecat.processors.aggregators.llm_response_universal import (
        LLMContextAggregatorPair,
        LLMUserAggregatorParams,
        UserTurnStrategies,
    )
    from pipecat.transports.base_transport import TransportParams
    from pipecat.transports.smallwebrtc.transport import SmallWebRTCTransport
    from pipecat.turns.user_stop.speech_timeout_user_turn_stop_strategy import (
        SpeechTimeoutUserTurnStopStrategy,
    )

    from openjarvis.server.voice.llm import OpenJarvisLLMService
    from openjarvis.server.voice.tts import VieNeuTTSService

    transport = SmallWebRTCTransport(
        webrtc_connection=connection,
        params=TransportParams(audio_in_enabled=True, audio_out_enabled=True),
    )
    llm = OpenJarvisLLMService(binding, recall=recall)
    context = LLMContext()
    # In 1.7.0 the VAD analyser belongs to the user aggregator, not the
    # transport, and interruption is always on — there is no flag to enable.
    # Running it here, locally, is what keeps barge-in independent of the
    # round trip to the transcription service.
    #
    # realtime_service_mode must be forced off. The Gemini Live transcriber
    # announces itself as a realtime service, which auto-flips the pair into
    # realtime mode — and that mode drives the service's own speech-to-speech
    # turn with event-only signals, never pushing LLMContextFrame. Our LLM is
    # the OpenJarvis Agent, which only runs on LLMContextFrame; the Gemini
    # service exists to transcribe, not to answer. Cascade mode is the mode
    # the design assumes.
    # The default turn stop waits ~3 s of silence (smart-turn model) before
    # declaring the turn over; activity_end — and with it the transcript and
    # the Agent run — only follows. 0.6 s keeps the turn snappy without
    # clipping a pause mid-sentence. wait_for_transcript stays on so a turn
    # never ends before its user message exists.
    user_aggregator, assistant_aggregator = LLMContextAggregatorPair(
        context,
        user_params=LLMUserAggregatorParams(
            vad_analyzer=SileroVADAnalyzer(),
            user_turn_strategies=UserTurnStrategies(
                stop=[
                    SpeechTimeoutUserTurnStopStrategy(
                        user_speech_timeout=USER_SPEECH_TIMEOUT_S,
                        wait_for_transcript=True,
                    )
                ]
            ),
        ),
        realtime_service_mode=False,
    )
    pipeline = Pipeline(
        [
            transport.input(),
            stt,
            user_aggregator,
            llm,
            VieNeuTTSService(renderer, sample_rate=VIENEU_SAMPLE_RATE_HZ),
            transport.output(),
            assistant_aggregator,
        ]
    )
    worker = PipelineWorker(
        pipeline,
        params=PipelineParams(
            enable_metrics=True,
            audio_out_sample_rate=VIENEU_SAMPLE_RATE_HZ,
        ),
    )
    return worker, context
