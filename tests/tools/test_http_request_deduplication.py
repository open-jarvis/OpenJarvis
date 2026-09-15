"""One exact mutation, one network dispatch -- across turns and threads.

The merchant has no cart endpoint: the local draft becomes a request body at
checkout. A model that re-sends the same confirmed order, or two turns racing,
must not become two coffees.
"""

from __future__ import annotations

import contextvars
import json
import threading
from unittest.mock import MagicMock, patch

import httpx
import pytest

from openjarvis.core.conversation import conversation_scope
from openjarvis.tools import evidence
from openjarvis.tools.http_request import HttpRequestTool

# A fake host on purpose: a mock that silently stops biting must not be
# able to place a real order. The Rust read path already bypassed one
# httpx patch during this work.
_URL = "https://shop.example/api/latest/orders/public"
_BODY = {"items": [{"slug": "latte-standard", "quantity": 1}], "type": "take-out"}


@pytest.fixture(autouse=True)
def _force_httpx_fallback():
    """No test here may reach the network; force the httpx path and stub SSRF."""
    mock_rust = MagicMock()
    mock_rust.HttpRequestTool.return_value.execute.side_effect = RuntimeError(
        "mocked out"
    )
    mock_rust.check_ssrf.return_value = None
    with patch(
        "openjarvis._rust_bridge.get_rust_module",
        return_value=mock_rust,
    ):
        yield


@pytest.fixture(autouse=True)
def _clean_store():
    evidence.reset()
    yield
    evidence.reset()


class _Transport:
    """Counts dispatches and returns a canned 200."""

    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.lock = threading.Lock()

    def __call__(self, method, url, **kwargs):
        with self.lock:
            self.calls.append({"method": method, "url": url, **kwargs})
        request = httpx.Request(method, url)
        return httpx.Response(
            200,
            request=request,
            json={"result": {"order": {"slug": "ord-777"}}},
        )


@pytest.fixture
def transport(monkeypatch) -> _Transport:
    sent = _Transport()
    monkeypatch.setattr(httpx, "request", sent)
    return sent


def _post(tool: HttpRequestTool, body=None):
    return tool.execute(
        url=_URL,
        method="POST",
        body=json.dumps(_BODY if body is None else body),
    )


def test_two_sequential_identical_posts_dispatch_once(transport):
    tool = HttpRequestTool()

    with conversation_scope("order-1"):
        first = _post(tool)
        second = _post(tool)

    assert len(transport.calls) == 1
    assert first.success is True
    assert second.success is False


def test_a_refused_duplicate_never_echoes_the_request_body(transport):
    """The refusal reaches the model; the customer's order body must not."""
    tool = HttpRequestTool()

    with conversation_scope("order-2"):
        _post(tool)
        refused = _post(tool)

    assert "latte-standard" not in refused.content
    assert "no network" in refused.content.lower()
    assert "response_seen" in refused.content


def test_two_concurrent_identical_posts_dispatch_once(transport):
    tool = HttpRequestTool()
    barrier = threading.Barrier(2)
    results: list = []
    results_lock = threading.Lock()

    def attempt() -> None:
        barrier.wait(timeout=5)
        result = _post(tool)
        with results_lock:
            results.append(result)

    with conversation_scope("order-3"):
        threads = [
            threading.Thread(target=contextvars.copy_context().run, args=(attempt,))
            for _ in range(2)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=5)

    assert len(results) == 2
    assert len(transport.calls) == 1
    assert sum(1 for result in results if result.success) == 1


def test_another_conversation_may_send_the_same_order(transport):
    tool = HttpRequestTool()

    with conversation_scope("order-4a"):
        _post(tool)
    with conversation_scope("order-4b"):
        second = _post(tool)

    assert len(transport.calls) == 2
    assert second.success is True


def test_a_different_order_is_not_deduplicated(transport):
    tool = HttpRequestTool()

    with conversation_scope("order-5"):
        _post(tool)
        _post(tool, body={"items": [{"slug": "latte-standard", "quantity": 2}]})

    assert len(transport.calls) == 2


def test_get_remains_freely_repeatable(transport):
    tool = HttpRequestTool()

    with conversation_scope("read-1"):
        tool.execute(url=_URL, method="GET")
        tool.execute(url=_URL, method="GET")
        tool.execute(url=_URL, method="HEAD")

    assert len(transport.calls) == 3


def test_a_request_proven_not_sent_can_be_retried(monkeypatch, transport):
    """A refused TCP connection never reached the shop, so retry is safe."""
    tool = HttpRequestTool()

    def _refuse(*args, **kwargs):
        raise httpx.ConnectError("connection refused")

    with conversation_scope("order-6"):
        monkeypatch.setattr(httpx, "request", _refuse)
        failed = _post(tool)
        monkeypatch.setattr(httpx, "request", transport)
        retry = _post(tool)

    assert failed.success is False
    assert retry.success is True
    assert len(transport.calls) == 1


def test_an_ambiguous_timeout_cannot_be_retried(monkeypatch, transport):
    """A read timeout after a POST does not prove the order was not placed."""
    tool = HttpRequestTool()

    def _timeout(*args, **kwargs):
        raise httpx.ReadTimeout("read timed out")

    with conversation_scope("order-7"):
        monkeypatch.setattr(httpx, "request", _timeout)
        failed = _post(tool)
        monkeypatch.setattr(httpx, "request", transport)
        retry = _post(tool)

    assert failed.success is False
    assert retry.success is False
    assert "ambiguous" in retry.content
    assert len(transport.calls) == 0
