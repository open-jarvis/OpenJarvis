"""Voice Session control-plane state for Chat Web Voice Mode."""

from __future__ import annotations

import secrets
import time
import uuid
from dataclasses import dataclass, field
from typing import Callable, Literal

from openjarvis.agents.runtime import AgentExecutionBinding
from openjarvis.core.types import Message

VoiceSessionStatus = Literal["connecting", "listening", "busy", "ended"]
VoiceTurnRole = Literal["user", "assistant"]
VoiceLanguage = Literal["vi", "en"]


class VoiceTurnRejected(ValueError):
    """Raised when a Final Voice Turn violates the Voice Session contract."""


@dataclass(frozen=True, slots=True)
class FinalVoiceTurn:
    voice_session_id: str
    chat_thread_id: str
    turn_id: int
    role: VoiceTurnRole
    content: str
    created_at: float


@dataclass(slots=True)
class VoiceSession:
    voice_session_id: str
    chat_thread_id: str
    execution_binding: AgentExecutionBinding
    initial_messages: tuple[Message, ...]
    status: VoiceSessionStatus
    created_at: float
    last_activity_at: float
    ended_at: float | None = None
    end_reason: str | None = None
    language: VoiceLanguage = "vi"
    pending_language: VoiceLanguage | None = None
    turns: dict[int, FinalVoiceTurn] = field(default_factory=dict)
    pending_voice_approval_expires_at: float | None = None
    active_turn_id: int | None = None
    cancellation_epoch: int = 0

    @property
    def model(self) -> str:
        return self.execution_binding.model


@dataclass(frozen=True, slots=True)
class StartVoiceSessionResult:
    status: VoiceSessionStatus
    session: VoiceSession | None
    fallback: Literal["text"] | None = None


class VoiceSessionService:
    """Owns Voice Session lifecycle and the single Local Voice Lease."""

    def __init__(
        self,
        *,
        now: Callable[[], float] | None = None,
        ttl_seconds: float = 300.0,
    ) -> None:
        self._now = now or time.time
        self._ttl_seconds = ttl_seconds
        self._sessions: dict[str, VoiceSession] = {}
        self._lease_session_id: str | None = None
        self._gated_websocket_tickets: dict[str, str] = {}

    def start_session(
        self,
        *,
        chat_thread_id: str,
        execution_binding: AgentExecutionBinding,
        initial_messages: tuple[Message, ...] = (),
    ) -> StartVoiceSessionResult:
        self.expire_stale_sessions()
        if self._lease_session_id is not None:
            return StartVoiceSessionResult(
                status="busy",
                session=None,
                fallback="text",
            )

        now = self._now()
        session = VoiceSession(
            voice_session_id=uuid.uuid4().hex,
            chat_thread_id=chat_thread_id,
            execution_binding=execution_binding,
            initial_messages=initial_messages,
            status="connecting",
            created_at=now,
            last_activity_at=now,
        )
        self._sessions[session.voice_session_id] = session
        self._lease_session_id = session.voice_session_id
        return StartVoiceSessionResult(status="connecting", session=session)

    def get_session(self, voice_session_id: str) -> VoiceSession:
        return self._sessions[voice_session_id]

    def issue_gated_websocket_ticket(self, voice_session_id: str) -> str:
        self.get_session(voice_session_id)
        ticket = secrets.token_urlsafe(32)
        self._gated_websocket_tickets[voice_session_id] = ticket
        return ticket

    def consume_gated_websocket_ticket(
        self, voice_session_id: str, candidate: str
    ) -> bool:
        expected = self._gated_websocket_tickets.get(voice_session_id)
        if (
            not expected
            or not candidate
            or not secrets.compare_digest(candidate, expected)
        ):
            return False
        self._gated_websocket_tickets.pop(voice_session_id, None)
        return True

    def mark_listening(self, voice_session_id: str) -> VoiceSession:
        session = self._sessions[voice_session_id]
        if session.status == "ended":
            return session
        session.status = "listening"
        session.last_activity_at = self._now()
        return session

    def request_language(
        self, voice_session_id: str, *, language: VoiceLanguage
    ) -> VoiceSession:
        session = self._sessions[voice_session_id]
        if session.status != "ended":
            session.pending_language = language
            session.last_activity_at = self._now()
        return session

    def apply_pending_language(self, voice_session_id: str) -> VoiceSession:
        session = self._sessions[voice_session_id]
        if session.pending_language is not None:
            session.language = session.pending_language
            session.pending_language = None
            session.last_activity_at = self._now()
        return session

    def activate_turn_epoch(self, voice_session_id: str, *, turn_id: int) -> int | None:
        """Make a newer user turn the session authority epoch.

        Returns the old turn that must be cancelled by the realtime service.
        """
        if turn_id <= 0:
            raise VoiceTurnRejected("turn_order_invalid")
        session = self._sessions[voice_session_id]
        active_turn_id = session.active_turn_id
        if active_turn_id is not None and turn_id <= active_turn_id:
            return None
        session.active_turn_id = turn_id
        session.cancellation_epoch += 1
        session.last_activity_at = self._now()
        return active_turn_id

    def set_pending_voice_approval(
        self, voice_session_id: str, *, expires_at: float
    ) -> VoiceSession:
        session = self._sessions[voice_session_id]
        session.pending_voice_approval_expires_at = expires_at
        session.last_activity_at = self._now()
        return session

    def arm_pending_voice_approval(
        self,
        voice_session_id: str,
        *,
        ttl_seconds: float,
    ) -> VoiceSession:
        if ttl_seconds <= 0:
            raise ValueError("pending_voice_approval_ttl_invalid")
        return self.set_pending_voice_approval(
            voice_session_id,
            expires_at=self._now() + ttl_seconds,
        )

    def clear_pending_voice_approval(self, voice_session_id: str) -> VoiceSession:
        session = self._sessions[voice_session_id]
        session.pending_voice_approval_expires_at = None
        session.last_activity_at = self._now()
        return session

    def has_pending_voice_approval(self, voice_session_id: str) -> bool:
        session = self._sessions[voice_session_id]
        expires_at = session.pending_voice_approval_expires_at
        if expires_at is None:
            return False
        if expires_at <= self._now():
            session.pending_voice_approval_expires_at = None
            return False
        return True

    def consume_pending_voice_approval(self, voice_session_id: str) -> bool:
        if not self.has_pending_voice_approval(voice_session_id):
            return False
        self.clear_pending_voice_approval(voice_session_id)
        return True

    def end_session(self, voice_session_id: str, *, reason: str) -> VoiceSession:
        session = self._sessions[voice_session_id]
        if session.status == "ended":
            return session

        session.status = "ended"
        session.ended_at = self._now()
        session.end_reason = reason
        self._gated_websocket_tickets.pop(voice_session_id, None)
        if self._lease_session_id == voice_session_id:
            self._lease_session_id = None
        return session

    def expire_stale_sessions(self) -> list[str]:
        now = self._now()
        expired: list[str] = []
        for session in list(self._sessions.values()):
            if session.status == "ended":
                continue
            if now - session.last_activity_at <= self._ttl_seconds:
                continue
            self.end_session(session.voice_session_id, reason="ttl")
            expired.append(session.voice_session_id)
        return expired

    def record_final_turn(
        self,
        *,
        voice_session_id: str,
        chat_thread_id: str,
        turn_id: int,
        role: VoiceTurnRole,
        content: str,
    ) -> FinalVoiceTurn:
        session = self._sessions[voice_session_id]
        if session.chat_thread_id != chat_thread_id:
            raise VoiceTurnRejected("chat_thread_mismatch")

        existing = session.turns.get(turn_id)
        if existing is not None:
            if (
                existing.chat_thread_id == chat_thread_id
                and existing.role == role
                and existing.content == content
            ):
                return existing
            raise VoiceTurnRejected("turn_id_conflict")

        if turn_id <= 0:
            raise VoiceTurnRejected("turn_order_invalid")

        now = self._now()
        turn = FinalVoiceTurn(
            voice_session_id=voice_session_id,
            chat_thread_id=chat_thread_id,
            turn_id=turn_id,
            role=role,
            content=content,
            created_at=now,
        )
        session.turns[turn_id] = turn
        session.last_activity_at = now
        return turn

    def record_played_assistant_boundary(
        self,
        *,
        voice_session_id: str,
        chat_thread_id: str,
        turn_id: int,
        content: str,
    ) -> None:
        session = self._sessions[voice_session_id]
        if session.chat_thread_id != chat_thread_id:
            raise VoiceTurnRejected("chat_thread_mismatch")
        existing = session.turns.get(turn_id)
        if not content:
            if existing is not None and existing.role == "assistant":
                del session.turns[turn_id]
            return
        if existing is None:
            self.record_final_turn(
                voice_session_id=voice_session_id,
                chat_thread_id=chat_thread_id,
                turn_id=turn_id,
                role="assistant",
                content=content,
            )
            return
        if existing.role != "assistant":
            raise VoiceTurnRejected("turn_id_conflict")
        session.turns[turn_id] = FinalVoiceTurn(
            voice_session_id=existing.voice_session_id,
            chat_thread_id=existing.chat_thread_id,
            turn_id=existing.turn_id,
            role="assistant",
            content=content,
            created_at=existing.created_at,
        )
        session.last_activity_at = self._now()
