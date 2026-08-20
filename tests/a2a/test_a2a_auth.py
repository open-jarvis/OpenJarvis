"""A2A server authentication tests (issue #217)."""

from __future__ import annotations

from openjarvis.a2a.protocol import AgentCard
from openjarvis.a2a.server import A2AServer


def _request():
    return {
        "jsonrpc": "2.0",
        "id": "1",
        "method": "tasks/send",
        "params": {"input": "ping"},
    }


def test_no_auth_token_allows_requests():
    server = A2AServer(AgentCard(name="x"), handler=lambda t: f"echo:{t}")
    resp = server.handle_request(_request())
    assert resp.get("error") is None


def test_missing_token_rejected_when_required():
    server = A2AServer(AgentCard(name="x"), handler=lambda t: t, auth_token="sek")
    resp = server.handle_request(_request())
    assert resp["error"]["code"] == -32001


def test_wrong_token_rejected():
    server = A2AServer(AgentCard(name="x"), handler=lambda t: t, auth_token="sek")
    resp = server.handle_request(_request(), token="nope")
    assert resp["error"]["code"] == -32001


def test_correct_token_accepted_and_dispatched():
    server = A2AServer(
        AgentCard(name="x"), handler=lambda t: f"echo:{t}", auth_token="sek"
    )
    resp = server.handle_request(_request(), token="sek")
    assert resp.get("error") is None


def test_auth_scheme_advertised_on_card():
    server = A2AServer(AgentCard(name="x"), auth_token="sek")
    assert server.agent_card.authentication == {"schemes": ["bearer"]}


def test_no_token_unauthenticated_card_stays_empty():
    server = A2AServer(AgentCard(name="x"))
    assert server.agent_card.authentication == {}
