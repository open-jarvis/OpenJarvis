"""Per-session aggregator — turns many internal events into one analytics event.

Without this, a single chat (50 inferences, 10 tool calls) would
produce ~60 PostHog events. With it, the same chat produces one
``chat_session_ended`` event with summary properties — a ~60× reduction
that keeps per-DAU event volume in the target zone (~40 events/day).

The aggregator buffers per-session counts in memory, emits on
explicit session end, and also emits stale sessions on a background
flusher thread (so abandoned sessions don't accumulate forever).
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from openjarvis.analytics.client import AnalyticsClient

logger = logging.getLogger(__name__)

# How long before an idle session is force-flushed (5 minutes is a
# typical chat-app session timeout). 30 second flusher tick.
_IDLE_TIMEOUT_S = 300
_FLUSHER_TICK_S = 30


@dataclass(slots=True)
class _SessionStats:
    started_at: float = field(default_factory=time.time)
    last_activity: float = field(default_factory=time.time)
    inference_count: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    tool_count: int = 0
    error_count: int = 0
    latencies_ms: list[float] = field(default_factory=list)
    models: set[str] = field(default_factory=set)
    tools: set[str] = field(default_factory=set)
    engines: set[str] = field(default_factory=set)


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    sorted_vals = sorted(values)
    k = (len(sorted_vals) - 1) * pct
    f = int(k)
    c = min(f + 1, len(sorted_vals) - 1)
    if f == c:
        return sorted_vals[f]
    return sorted_vals[f] + (sorted_vals[c] - sorted_vals[f]) * (k - f)


class SessionAggregator:
    """Buffers per-session counts; emits ``chat_session_ended`` on close."""

    def __init__(
        self,
        client: "AnalyticsClient",
        *,
        idle_timeout_s: float = _IDLE_TIMEOUT_S,
        flusher_tick_s: float = _FLUSHER_TICK_S,
    ) -> None:
        self.client = client
        self.idle_timeout_s = idle_timeout_s
        self._sessions: dict[str, _SessionStats] = {}
        self._lock = threading.Lock()
        self._shutdown = threading.Event()
        self._flusher = threading.Thread(
            target=self._flush_idle_loop,
            args=(flusher_tick_s,),
            daemon=True,
            name="analytics-aggregator-flusher",
        )
        self._flusher.start()

    # -- recording -------------------------------------------------------

    def _touch(self, session_id: str) -> _SessionStats:
        s = self._sessions.get(session_id)
        if s is None:
            s = _SessionStats()
            self._sessions[session_id] = s
        s.last_activity = time.time()
        return s

    def record_inference(
        self,
        session_id: str,
        *,
        tokens_in: int = 0,
        tokens_out: int = 0,
        latency_ms: float = 0.0,
        model_hash: str = "",
        engine: str = "",
    ) -> None:
        with self._lock:
            s = self._touch(session_id)
            s.inference_count += 1
            s.tokens_in += max(0, tokens_in)
            s.tokens_out += max(0, tokens_out)
            if latency_ms > 0:
                s.latencies_ms.append(latency_ms)
            if model_hash:
                s.models.add(model_hash)
            if engine:
                s.engines.add(engine)

    def record_tool(self, session_id: str, *, tool_name: str = "") -> None:
        with self._lock:
            s = self._touch(session_id)
            s.tool_count += 1
            if tool_name:
                s.tools.add(tool_name)

    def record_error(self, session_id: str) -> None:
        with self._lock:
            s = self._touch(session_id)
            s.error_count += 1

    # -- lifecycle -------------------------------------------------------

    def end_session(self, session_id: str) -> None:
        """Emit ``chat_session_ended`` for one session and drop the buffer."""
        with self._lock:
            stats = self._sessions.pop(session_id, None)
        if stats is None or stats.inference_count == 0:
            # Nothing meaningful happened — don't emit a no-op event.
            return
        self._emit(stats)

    def _emit(self, stats: _SessionStats) -> None:
        props: dict[str, object] = {
            "turn_count": stats.inference_count,
            "tokens_in": stats.tokens_in,
            "tokens_out": stats.tokens_out,
            "latency_ms_p50": _percentile(stats.latencies_ms, 0.50),
            "latency_ms_p95": _percentile(stats.latencies_ms, 0.95),
            "tool_count": stats.tool_count,
            "unique_tools": len(stats.tools),
            "unique_models": len(stats.models),
            "error_count": stats.error_count,
            "duration_ms": int((stats.last_activity - stats.started_at) * 1000),
        }
        # Only emit model/engine when unambiguous (one used in session).
        if len(stats.models) == 1:
            props["model_hash"] = next(iter(stats.models))
        if len(stats.engines) == 1:
            props["engine"] = next(iter(stats.engines))
        self.client.capture("chat_session_ended", props)

    def _flush_idle_loop(self, tick_s: float) -> None:
        while not self._shutdown.wait(tick_s):
            now = time.time()
            with self._lock:
                stale_ids = [
                    sid
                    for sid, s in self._sessions.items()
                    if now - s.last_activity > self.idle_timeout_s
                ]
            for sid in stale_ids:
                try:
                    self.end_session(sid)
                except Exception as exc:
                    logger.debug("Aggregator idle flush failed: %s", exc)

    def shutdown(self) -> None:
        """Flush every buffered session and stop the flusher thread."""
        self._shutdown.set()
        with self._lock:
            stats_list = list(self._sessions.values())
            self._sessions.clear()
        for stats in stats_list:
            try:
                if stats.inference_count > 0:
                    self._emit(stats)
            except Exception as exc:
                logger.debug("Aggregator shutdown flush failed: %s", exc)


__all__ = ["SessionAggregator"]
