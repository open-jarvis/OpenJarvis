"""Canonical browser session, health, and recovery records."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class BrowserSessionStatus(str, Enum):
    CREATED = "created"
    STARTING = "starting"
    READY = "ready"
    DEGRADED = "degraded"
    RECOVERING = "recovering"
    PAUSED = "paused"
    CLOSED = "closed"


@dataclass(slots=True)
class BrowserControlHealth:
    session_id: str
    browser_process_present: bool
    browser_pid: int | None
    browser_start_time: str | None
    profile_path: str
    control_service_present: bool
    control_service_pid: int | None
    control_port: int
    port_open: bool
    port_owner_pid: int | None
    port_owner_matches: bool
    health_endpoint: str
    connection_ok: bool
    last_successful_heartbeat: str | None
    cause: str
    checked_at: str = field(default_factory=utc_now)

    @property
    def healthy(self) -> bool:
        return all(
            (
                self.browser_process_present,
                self.control_service_present,
                self.port_open,
                self.port_owner_matches,
                self.connection_ok,
            )
        )


@dataclass(slots=True)
class BrowserRecoveryRecord:
    session_id: str
    attempt: int
    maximum_attempts: int
    cause: str
    reconnect_attempted: bool
    reconnect_succeeded: bool
    control_restart_attempted: bool
    control_restart_succeeded: bool
    result: str
    checkpoint: str
    started_at: str
    completed_at: str


@dataclass(slots=True)
class BrowserSession:
    profile_path: Path
    control_port: int
    session_id: str = field(default_factory=lambda: f"browser_{uuid.uuid4().hex}")
    status: BrowserSessionStatus = BrowserSessionStatus.CREATED
    browser_pid: int | None = None
    browser_start_time: str | None = None
    control_service_pid: int | None = None
    last_successful_heartbeat: str | None = None
    recovery_attempts: int = 0
    maximum_recovery_attempts: int = 1
    reconnect_attempts: int = 0
    control_restart_attempts: int = 0
    safe_checkpoint: str = "session.created"
    effect_known: bool = True
    owned_process: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


__all__ = [
    "BrowserControlHealth",
    "BrowserRecoveryRecord",
    "BrowserSession",
    "BrowserSessionStatus",
    "utc_now",
]
