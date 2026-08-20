"""Regression test for #759: concurrent per-request model overrides on a
shared agent race and can permanently corrupt ``agent._model``.

``_handle_agent`` temporarily overwrites the shared ``agent._model`` for
the duration of one request, then restores it. Both the streaming and
non-streaming routes run this via ``asyncio.to_thread``, so two overlapping
requests execute on real OS threads and can interleave: request B may read
request A's override as its own "original" value, and whichever request's
cleanup runs last permanently pins the shared agent to the wrong model.
"""

from __future__ import annotations

import gc
import threading
import time
import weakref

import pytest

fastapi = pytest.importorskip("fastapi")

from openjarvis.agents._stubs import AgentResult  # noqa: E402
from openjarvis.server.models import ChatCompletionRequest, ChatMessage  # noqa: E402
from openjarvis.server.routes import (  # noqa: E402
    _agent_model_locks,
    _get_agent_model_lock,
    _handle_agent,
)


def _make_request(model: str, text: str) -> ChatCompletionRequest:
    return ChatCompletionRequest(
        model=model,
        messages=[ChatMessage(role="user", content=text)],
    )


class _FakeAgent:
    """Minimal agent stub whose ``run()`` records the live ``_model`` it
    actually saw partway through, with sleeps on either side to widen the
    window for another thread's override to leak in if calls aren't
    serialized."""

    def __init__(self, model: str) -> None:
        self._model = model

    def run(self, input_text: str, context=None) -> AgentResult:
        time.sleep(0.005)
        seen_model = self._model
        time.sleep(0.005)
        return AgentResult(content=f"{input_text}:{seen_model}", turns=1)


class _UnhashableNonWeakrefAgent:
    """A valid custom agent with neither hash nor weak-reference support."""

    __slots__ = ("_model",)
    __hash__ = None

    def __init__(self, model: str) -> None:
        self._model = model

    def run(self, input_text: str, context=None) -> AgentResult:
        time.sleep(0.005)
        seen_model = self._model
        time.sleep(0.005)
        return AgentResult(content=f"{input_text}:{seen_model}", turns=1)


@pytest.mark.parametrize("agent_cls", [_FakeAgent, _UnhashableNonWeakrefAgent])
def test_concurrent_model_overrides_do_not_corrupt_shared_agent(agent_cls):
    agent = agent_cls(model="default-model")
    n_workers = 16
    result_box: dict[int, str] = {}
    result_lock = threading.Lock()

    def worker(i: int) -> None:
        model = f"model-{i}"
        resp = _handle_agent(agent, model, _make_request(model, f"req-{i}"))
        with result_lock:
            result_box[i] = resp.choices[0].message.content

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n_workers)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
        assert not t.is_alive(), "worker thread hung"

    for i in range(n_workers):
        expected = f"req-{i}:model-{i}"
        assert result_box[i] == expected, (
            f"worker {i} observed {result_box[i]!r} during its own run() "
            f"call, expected {expected!r} -- another request's model "
            "override leaked into this one"
        )

    # After every request has completed, the shared agent must be back to
    # its true original -- no request's cleanup should have restored a
    # stale value it mistakenly captured as "original".
    assert agent._model == "default-model"


def test_model_lock_registry_does_not_retain_idle_locks_or_agents():
    agent = _FakeAgent(model="default-model")
    agent_ref = weakref.ref(agent)
    agent_id = id(agent)

    lock = _get_agent_model_lock(agent)
    assert _agent_model_locks[agent_id] is lock

    del lock
    del agent
    gc.collect()

    assert agent_ref() is None
    assert agent_id not in _agent_model_locks
