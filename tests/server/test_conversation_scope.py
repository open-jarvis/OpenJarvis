"""Each conversation owns its working set -- including across a stream."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from fastapi.testclient import TestClient

from openjarvis.core import conversation
from openjarvis.core.conversation import conversation_scope, current_conversation_id
from openjarvis.server.middleware import create_conversation_scope_middleware


def test_scope_sets_and_restores():
    assert current_conversation_id() == ""

    with conversation_scope("thread-1"):
        assert current_conversation_id() == "thread-1"

    assert current_conversation_id() == ""


def test_nested_scopes_restore_the_outer_one():
    with conversation_scope("outer"):
        with conversation_scope("inner"):
            assert current_conversation_id() == "inner"
        assert current_conversation_id() == "outer"


def test_agent_turn_scope_issues_a_fresh_nonce_and_restores_the_outer_turn():
    assert hasattr(conversation, "agent_turn_scope")
    assert conversation.current_turn_nonce() == ""

    with conversation.agent_turn_scope() as outer:
        assert conversation.current_turn_nonce() == outer
        with conversation.agent_turn_scope() as inner:
            assert inner != outer
            assert conversation.current_turn_nonce() == inner
        assert conversation.current_turn_nonce() == outer

    assert conversation.current_turn_nonce() == ""


def test_checkout_nonce_is_single_use_and_expires_in_copied_context():
    from contextvars import copy_context

    with conversation_scope("checkout-nonce"):
        with conversation.agent_turn_scope() as nonce:
            copied = copy_context()
            assert conversation.claim_turn_nonce("wrong") is False
            assert conversation.claim_turn_nonce(nonce) is True
            assert conversation.claim_turn_nonce(nonce) is False
        assert copied.run(conversation.turn_nonce_is_active, nonce) is False


def _app_with_middleware(**kwargs) -> tuple:
    seen: list = []
    app = FastAPI()
    app.add_middleware(create_conversation_scope_middleware(**kwargs))

    @app.get("/plain")
    def plain():
        seen.append(current_conversation_id())
        return {"ok": True}

    @app.get("/streamed")
    def streamed():
        def body():
            # Runs after the handler has returned -- the case a
            # `with` block around the handler body would miss entirely.
            seen.append(current_conversation_id())
            yield b"chunk"

        return StreamingResponse(body())

    return app, seen


def test_a_plain_request_gets_a_conversation():
    app, seen = _app_with_middleware()

    TestClient(app).get("/plain")

    assert len(seen) == 1
    assert seen[0] != ""


def test_a_streamed_response_still_has_its_conversation():
    """The chat path streams, so the agent runs after the endpoint returned.

    Pins the property rather than trusting how FastAPI happens to copy context
    around an endpoint on any given version.
    """
    app, seen = _app_with_middleware()

    TestClient(app).get("/streamed")

    assert len(seen) == 1
    assert seen[0] != ""


def test_two_requests_do_not_share_a_conversation():
    app, seen = _app_with_middleware()
    client = TestClient(app)

    client.get("/streamed")
    client.get("/streamed")

    assert len(seen) == 2
    assert seen[0] != seen[1]


CONVERSATION_HEADER = "X-OpenJarvis-Conversation"


def test_the_server_issues_an_opaque_conversation_id():
    """The client must never have to invent the id it will send back."""
    app, seen = _app_with_middleware()

    response = TestClient(app).get("/plain")

    issued = response.headers[CONVERSATION_HEADER]
    assert len(issued) == 32
    assert issued == issued.lower()
    assert all(character in "0123456789abcdef" for character in issued)
    assert seen == [issued]


def test_returning_an_issued_id_reuses_its_scope():
    """This is the whole point: one text conversation, one working set."""
    app, seen = _app_with_middleware()
    client = TestClient(app)

    issued = client.get("/plain").headers[CONVERSATION_HEADER]
    second = client.get("/plain", headers={CONVERSATION_HEADER: issued})

    assert second.headers[CONVERSATION_HEADER] == issued
    assert seen == [issued, issued]


def test_a_streamed_response_also_reuses_an_issued_id():
    """The chat path streams; its scope must survive past the handler."""
    app, seen = _app_with_middleware()
    client = TestClient(app)

    issued = client.get("/streamed").headers[CONVERSATION_HEADER]
    client.get("/streamed", headers={CONVERSATION_HEADER: issued})

    assert seen == [issued, issued]


@pytest.mark.parametrize(
    "supplied",
    [
        "attacker-chosen",
        "../../etc/passwd",
        "0123456789abcdef0123456789abcdef",  # well-formed but never issued
        "",
        "ABCDEF0123456789ABCDEF0123456789",  # uppercase is not what we issue
    ],
)
def test_an_id_the_server_did_not_issue_is_replaced(supplied):
    """Honouring caller text would let one client read another's evidence."""
    app, seen = _app_with_middleware()

    response = TestClient(app).get("/plain", headers={CONVERSATION_HEADER: supplied})

    issued = response.headers[CONVERSATION_HEADER]
    assert issued != supplied
    assert len(issued) == 32
    assert seen == [issued]


def test_the_registry_evicts_instead_of_growing_forever():
    """A public terminal runs for weeks; an unbounded map is a slow leak."""
    app, _seen = _app_with_middleware(max_conversations=4)
    client = TestClient(app)

    oldest = client.get("/plain").headers[CONVERSATION_HEADER]
    newer = [client.get("/plain").headers[CONVERSATION_HEADER] for _ in range(4)]

    # The oldest id has been evicted, so returning it earns a fresh scope.
    assert (
        client.get("/plain", headers={CONVERSATION_HEADER: oldest}).headers[
            CONVERSATION_HEADER
        ]
        != oldest
    )
    # The most recent one is still recognised.
    assert (
        client.get("/plain", headers={CONVERSATION_HEADER: newer[-1]}).headers[
            CONVERSATION_HEADER
        ]
        == newer[-1]
    )


def test_reuse_keeps_an_id_alive_against_eviction():
    """An active conversation must not be evicted by unrelated traffic."""
    app, _seen = _app_with_middleware(max_conversations=3)
    client = TestClient(app)

    kept = client.get("/plain").headers[CONVERSATION_HEADER]
    for _ in range(2):
        client.get("/plain")
        # Touching `kept` makes it most-recently-used again.
        client.get("/plain", headers={CONVERSATION_HEADER: kept})

    assert (
        client.get("/plain", headers={CONVERSATION_HEADER: kept}).headers[
            CONVERSATION_HEADER
        ]
        == kept
    )


def test_create_app_puts_conversation_scope_outside_auth():
    """Authentication rejections must still enter the HTTP conversation scope."""
    from openjarvis.server.app import create_app

    app = create_app(engine=None, model="test-model", api_key="test-key")

    assert app.user_middleware[0].cls.__name__ == "ConversationScopeMiddleware"
    assert app.user_middleware[1].cls.__name__ == "AuthMiddleware"
