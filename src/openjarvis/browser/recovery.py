"""Bounded browser recovery state machine."""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from openjarvis.browser.models import (
    BrowserControlHealth,
    BrowserRecoveryRecord,
    BrowserSession,
    BrowserSessionStatus,
    utc_now,
)
from openjarvis.browser.process import BrowserOpenError


class ReconnectableBrowser(Protocol):
    def reconnect(self, session: BrowserSession) -> bool: ...


class BrowserHealthManager(Protocol):
    def health(self, session: BrowserSession) -> BrowserControlHealth: ...

    def restart_control_service(self, session: BrowserSession) -> bool: ...


class BrowserRecoveryController:
    """Exactly one reconnect and at most one control-service restart."""

    def __init__(
        self,
        manager: BrowserHealthManager,
        adapter: ReconnectableBrowser,
        *,
        event_sink: Callable[[str, dict], None] | None = None,
    ) -> None:
        self.manager = manager
        self.adapter = adapter
        self.event_sink = event_sink or (lambda _event, _payload: None)

    def recover(self, session: BrowserSession) -> BrowserRecoveryRecord:
        initial = self.manager.health(session)
        self.event_sink("browser.health_checked", _health_payload(initial))
        if initial.healthy:
            return BrowserRecoveryRecord(
                session_id=session.session_id,
                attempt=session.recovery_attempts,
                maximum_attempts=session.maximum_recovery_attempts,
                cause="healthy",
                reconnect_attempted=False,
                reconnect_succeeded=False,
                control_restart_attempted=False,
                control_restart_succeeded=False,
                result="already_healthy",
                checkpoint=session.safe_checkpoint,
                started_at=initial.checked_at,
                completed_at=initial.checked_at,
            )
        if not session.effect_known:
            session.status = BrowserSessionStatus.PAUSED
            raise BrowserOpenError(
                "browser state is unknown after a possible external effect; task paused"
            )
        if session.recovery_attempts >= session.maximum_recovery_attempts:
            session.status = BrowserSessionStatus.PAUSED
            raise BrowserOpenError("maximum browser recovery attempts reached")

        started = utc_now()
        session.recovery_attempts += 1
        session.status = BrowserSessionStatus.RECOVERING
        self.event_sink(
            "browser.recovery_started",
            {
                "session_id": session.session_id,
                "attempt": session.recovery_attempts,
                "maximum_attempts": session.maximum_recovery_attempts,
                "cause": initial.cause,
                "checkpoint": session.safe_checkpoint,
            },
        )

        session.reconnect_attempts += 1
        reconnect_succeeded = bool(self.adapter.reconnect(session))
        after_reconnect = self.manager.health(session)
        self.event_sink("browser.health_checked", _health_payload(after_reconnect))
        if reconnect_succeeded and after_reconnect.healthy:
            session.status = BrowserSessionStatus.READY
            self.event_sink(
                "browser.reconnected",
                {
                    "session_id": session.session_id,
                    "attempt": session.recovery_attempts,
                },
            )
            return BrowserRecoveryRecord(
                session_id=session.session_id,
                attempt=session.recovery_attempts,
                maximum_attempts=session.maximum_recovery_attempts,
                cause=initial.cause,
                reconnect_attempted=True,
                reconnect_succeeded=True,
                control_restart_attempted=False,
                control_restart_succeeded=False,
                result="reconnected",
                checkpoint=session.safe_checkpoint,
                started_at=started,
                completed_at=utc_now(),
            )

        restart_attempted = False
        restart_succeeded = False
        if session.control_restart_attempts == 0:
            session.control_restart_attempts += 1
            restart_attempted = True
            restart_succeeded = bool(self.manager.restart_control_service(session))
        final = self.manager.health(session)
        self.event_sink("browser.health_checked", _health_payload(final))
        if restart_succeeded and final.healthy:
            session.status = BrowserSessionStatus.READY
            result = "control_service_restarted"
            self.event_sink(
                "browser.reconnected",
                {
                    "session_id": session.session_id,
                    "attempt": session.recovery_attempts,
                },
            )
        else:
            session.status = BrowserSessionStatus.PAUSED
            result = "failed"
            self.event_sink(
                "browser.recovery_failed",
                {
                    "session_id": session.session_id,
                    "attempt": session.recovery_attempts,
                    "cause": final.cause,
                },
            )
        return BrowserRecoveryRecord(
            session_id=session.session_id,
            attempt=session.recovery_attempts,
            maximum_attempts=session.maximum_recovery_attempts,
            cause=initial.cause,
            reconnect_attempted=True,
            reconnect_succeeded=reconnect_succeeded,
            control_restart_attempted=restart_attempted,
            control_restart_succeeded=restart_succeeded,
            result=result,
            checkpoint=session.safe_checkpoint,
            started_at=started,
            completed_at=utc_now(),
        )


def _health_payload(health: BrowserControlHealth) -> dict:
    return {
        "session_id": health.session_id,
        "browser_process_present": health.browser_process_present,
        "browser_pid": health.browser_pid,
        "browser_start_time": health.browser_start_time,
        "profile_path": health.profile_path,
        "control_service_present": health.control_service_present,
        "control_service_pid": health.control_service_pid,
        "control_port": health.control_port,
        "port_open": health.port_open,
        "port_owner_pid": health.port_owner_pid,
        "port_owner_matches": health.port_owner_matches,
        "health_endpoint": health.health_endpoint,
        "connection_ok": health.connection_ok,
        "last_successful_heartbeat": health.last_successful_heartbeat,
        "cause": health.cause,
        "checked_at": health.checked_at,
    }


__all__ = ["BrowserRecoveryController"]
