"""Turn detection policies for cascade Voice sessions."""

from __future__ import annotations

import asyncio
import time

from pipecat.frames.frames import (
    VADUserStartedSpeakingFrame,
    VADUserStoppedSpeakingFrame,
)
from pipecat.turns.user_stop.turn_analyzer_user_turn_stop_strategy import (
    TurnAnalyzerUserTurnStopStrategy,
)


class ConfirmedTurnAnalyzerUserTurnStopStrategy(TurnAnalyzerUserTurnStopStrategy):
    """Require sustained silence before accepting a COMPLETE prediction."""

    def __init__(self, *, minimum_silence_secs: float, **kwargs) -> None:
        super().__init__(**kwargs)
        self._minimum_silence_secs = minimum_silence_secs
        self._silence_started_at: float | None = None
        self._confirmation_task: asyncio.Task[None] | None = None

    async def handle_user_turn_started(self) -> None:
        await self._cancel_confirmation()
        self._silence_started_at = None
        await super().handle_user_turn_started()

    async def handle_user_turn_stopped(self) -> None:
        await self._cancel_confirmation()
        self._silence_started_at = None
        await super().handle_user_turn_stopped()

    async def cleanup(self) -> None:
        await self._cancel_confirmation()
        await super().cleanup()

    async def _handle_vad_user_started_speaking(
        self, frame: VADUserStartedSpeakingFrame
    ) -> None:
        await self._cancel_confirmation()
        self._silence_started_at = None
        await super()._handle_vad_user_started_speaking(frame)

    async def _handle_vad_user_stopped_speaking(
        self, frame: VADUserStoppedSpeakingFrame
    ) -> None:
        self._silence_started_at = time.monotonic() - frame.stop_secs
        await super()._handle_vad_user_stopped_speaking(frame)

    async def trigger_user_turn_stopped(
        self, *, enable_user_speaking_frames: bool | None = None
    ) -> None:
        silence_elapsed = (
            time.monotonic() - self._silence_started_at
            if self._silence_started_at is not None
            else 0.0
        )
        remaining = max(0.0, self._minimum_silence_secs - silence_elapsed)
        if remaining == 0:
            await super().trigger_user_turn_stopped(
                enable_user_speaking_frames=enable_user_speaking_frames
            )
        elif self._confirmation_task is None:
            self._confirmation_task = self.task_manager.create_task(
                self._confirm_after(remaining, enable_user_speaking_frames),
                f"{self}::_confirm_after",
            )

    async def _confirm_after(
        self, delay: float, enable_user_speaking_frames: bool | None
    ) -> None:
        try:
            await asyncio.sleep(delay)
        except asyncio.CancelledError:
            return
        self._confirmation_task = None
        await super().trigger_user_turn_stopped(
            enable_user_speaking_frames=enable_user_speaking_frames
        )

    async def _cancel_confirmation(self) -> None:
        if self._confirmation_task is not None:
            await self.task_manager.cancel_task(self._confirmation_task)
            self._confirmation_task = None
