from __future__ import annotations


def test_gateway_session_key_format():
    from openjarvis.daemon.gateway import GatewayDaemon

    key = GatewayDaemon.session_key(
        platform="telegram", chat_type="dm", chat_id="12345", thread_id=None
    )
    assert key == "agent:main:telegram:dm:12345:None"


def test_gateway_session_key_deterministic():
    from openjarvis.daemon.gateway import GatewayDaemon

    key1 = GatewayDaemon.session_key("discord", "group", "abc", "thread1")
    key2 = GatewayDaemon.session_key("discord", "group", "abc", "thread1")
    assert key1 == key2
