from __future__ import annotations

from typing import Any, Optional


class GatewayDaemon:
    """Composes channels, sessions, agents, and scheduler into a daemon."""

    def __init__(
        self,
        config: Any = None,
        session_store: Any = None,
        agent_manager: Any = None,
        agent_scheduler: Any = None,
        event_bus: Any = None,
    ) -> None:
        self._config = config
        self._session_store = session_store
        self._agent_manager = agent_manager
        self._agent_scheduler = agent_scheduler
        self._event_bus = event_bus
        self._running = False

    @staticmethod
    def session_key(
        platform: str,
        chat_type: str,
        chat_id: str,
        thread_id: Optional[str],
    ) -> str:
        return f"agent:main:{platform}:{chat_type}:{chat_id}:{thread_id}"

    def start(self) -> None:
        """Start the daemon (foreground)."""
        self._running = True

    def stop(self) -> None:
        """Stop the daemon."""
        self._running = False
