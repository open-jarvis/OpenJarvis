"""Scripted inference engine for deterministic agent testing."""

from __future__ import annotations

from typing import Any, AsyncIterator, Dict, List

from openjarvis.engine._stubs import InferenceEngine


class FakeEngine(InferenceEngine):
    """Returns pre-defined responses in order. Captures prompts for assertions."""

    engine_id = "fake"

    def __init__(self, responses: list[dict]) -> None:
        self._responses = list(responses)
        self._call_count = 0
        self._last_messages: list | None = None

    @property
    def call_count(self) -> int:
        return self._call_count

    @property
    def last_messages(self) -> list | None:
        return self._last_messages

    def generate(
        self,
        messages: list,
        *,
        model: str,
        temperature: float = 0.7,
        max_tokens: int = 1024,
        **kw: Any,
    ) -> Dict[str, Any]:
        self._last_messages = messages
        idx = min(self._call_count, len(self._responses) - 1)
        resp = self._responses[idx]
        self._call_count += 1

        # Support raising exceptions for error testing
        if "raise" in resp:
            raise resp["raise"]

        result: Dict[str, Any] = {
            "content": resp.get("content", ""),
            "usage": resp.get("usage", {
                "prompt_tokens": 10,
                "completion_tokens": 5,
                "total_tokens": 15,
            }),
            "model": model,
            "finish_reason": "tool_calls" if resp.get("tool_calls") else "stop",
        }
        if resp.get("tool_calls"):
            result["tool_calls"] = resp["tool_calls"]
        return result

    async def stream(
        self, messages: list, *, model: str, **kw: Any,
    ) -> AsyncIterator[str]:
        result = self.generate(messages, model=model, **kw)
        yield result["content"]

    def list_models(self) -> List[str]:
        return ["fake-model"]

    def health(self) -> bool:
        return True
