"""Bounded BrowserOpenError recovery matrix."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from openjarvis.browser import (
    BrowserControlHealth,
    BrowserOpenError,
    BrowserRecoveryController,
    BrowserSession,
    BrowserSessionStatus,
)


def _health(**changes) -> BrowserControlHealth:
    value = BrowserControlHealth(
        session_id="browser-test",
        browser_process_present=True,
        browser_pid=101,
        browser_start_time="2026-07-30T00:00:00+00:00",
        profile_path="temporary/profile",
        control_service_present=True,
        control_service_pid=101,
        control_port=9222,
        port_open=True,
        port_owner_pid=101,
        port_owner_matches=True,
        health_endpoint="http://127.0.0.1:9222/json/version",
        connection_ok=True,
        last_successful_heartbeat="2026-07-30T00:00:01+00:00",
        cause="healthy",
    )
    return replace(value, **changes)


class FakeManager:
    def __init__(self, healths, *, restart=False):
        self.healths = list(healths)
        self.restart = restart
        self.health_calls = 0
        self.restart_calls = 0

    def health(self, _session):
        index = min(self.health_calls, len(self.healths) - 1)
        self.health_calls += 1
        return self.healths[index]

    def restart_control_service(self, _session):
        self.restart_calls += 1
        return self.restart


class FakeAdapter:
    def __init__(self, result):
        self.result = result
        self.calls = 0

    def reconnect(self, _session):
        self.calls += 1
        return self.result


def _session() -> BrowserSession:
    return BrowserSession(
        session_id="browser-test",
        profile_path=Path("temporary/profile"),
        control_port=9222,
        browser_pid=101,
        control_service_pid=101,
        status=BrowserSessionStatus.DEGRADED,
        safe_checkpoint="before.navigation",
    )


@pytest.mark.parametrize(
    "unhealthy",
    [
        _health(
            browser_process_present=False,
            cause="browser_process_missing",
        ),
        _health(
            control_service_present=False,
            cause="control_service_missing",
        ),
        _health(
            port_open=False,
            port_owner_matches=False,
            connection_ok=False,
            cause="control_port_closed",
        ),
        _health(
            port_owner_pid=999,
            port_owner_matches=False,
            connection_ok=False,
            cause="control_port_wrong_owner",
        ),
        _health(
            connection_ok=False,
            cause="control_connection_failed",
        ),
    ],
)
def test_failure_causes_attempt_exactly_one_reconnect(unhealthy) -> None:
    manager = FakeManager([unhealthy, _health(), _health()])
    adapter = FakeAdapter(True)
    record = BrowserRecoveryController(manager, adapter).recover(_session())
    assert record.result == "reconnected"
    assert adapter.calls == 1
    assert manager.restart_calls == 0


def test_reconnect_failure_is_honest_and_bounded() -> None:
    unhealthy = _health(connection_ok=False, cause="connection_lost")
    manager = FakeManager([unhealthy, unhealthy, unhealthy], restart=False)
    adapter = FakeAdapter(False)
    session = _session()
    record = BrowserRecoveryController(manager, adapter).recover(session)
    assert record.result == "failed"
    assert session.status is BrowserSessionStatus.PAUSED
    assert adapter.calls == 1
    assert manager.restart_calls == 1
    with pytest.raises(BrowserOpenError, match="maximum"):
        BrowserRecoveryController(manager, adapter).recover(session)
    assert adapter.calls == 1


def test_control_service_restart_can_recover() -> None:
    unhealthy = _health(connection_ok=False, cause="connection_lost")
    manager = FakeManager([unhealthy, unhealthy, _health()], restart=True)
    adapter = FakeAdapter(False)
    record = BrowserRecoveryController(manager, adapter).recover(_session())
    assert record.result == "control_service_restarted"
    assert record.control_restart_attempted is True
    assert manager.restart_calls == 1


def test_navigation_disconnect_with_unknown_effect_pauses_without_retry() -> None:
    session = _session()
    session.effect_known = False
    manager = FakeManager([_health(connection_ok=False, cause="during_navigation")])
    adapter = FakeAdapter(True)
    with pytest.raises(BrowserOpenError, match="unknown"):
        BrowserRecoveryController(manager, adapter).recover(session)
    assert adapter.calls == 0
    assert session.status is BrowserSessionStatus.PAUSED


def test_healthy_session_does_not_reconnect_or_restart() -> None:
    manager = FakeManager([_health()])
    adapter = FakeAdapter(True)
    record = BrowserRecoveryController(manager, adapter).recover(_session())
    assert record.result == "already_healthy"
    assert adapter.calls == 0
    assert manager.restart_calls == 0


def test_events_include_health_recovery_and_failure() -> None:
    events = []
    unhealthy = _health(connection_ok=False, cause="connection_lost")
    manager = FakeManager([unhealthy, unhealthy, unhealthy], restart=False)
    controller = BrowserRecoveryController(
        manager,
        FakeAdapter(False),
        event_sink=lambda name, payload: events.append((name, payload)),
    )
    controller.recover(_session())
    names = [name for name, _ in events]
    assert names.count("browser.recovery_started") == 1
    assert names.count("browser.recovery_failed") == 1
    assert names.count("browser.health_checked") == 3


def test_recovery_never_changes_safe_checkpoint() -> None:
    session = _session()
    manager = FakeManager(
        [_health(connection_ok=False, cause="lost"), _health()], restart=False
    )
    record = BrowserRecoveryController(manager, FakeAdapter(True)).recover(session)
    assert record.checkpoint == "before.navigation"
    assert session.safe_checkpoint == "before.navigation"
