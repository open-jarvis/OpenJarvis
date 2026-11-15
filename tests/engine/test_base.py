from __future__ import annotations

from openjarvis.core.types import Message, Role, ToolCall
from openjarvis.engine._base import estimate_prompt_tokens, messages_to_dicts
from openjarvis.engine._stubs import InferenceEngine


def test_estimate_prompt_tokens_handles_none_content_tool_call_turn() -> None:
    messages = [
        Message(role=Role.USER, content="hi"),
        Message(
            role=Role.ASSISTANT,
            content=None,
            tool_calls=[ToolCall(id="call_1", name="lookup", arguments="{}")],
        ),
    ]

    assert estimate_prompt_tokens(messages) == 12


def test_estimate_prompt_tokens_counts_tool_call_arguments() -> None:
    base = [
        Message(role=Role.USER, content="hi"),
        Message(role=Role.ASSISTANT, content=None),
    ]
    with_tool_call = [
        Message(role=Role.USER, content="hi"),
        Message(
            role=Role.ASSISTANT,
            content=None,
            tool_calls=[ToolCall(id="", name="", arguments="abcdefgh")],
        ),
    ]

    assert estimate_prompt_tokens(with_tool_call) - estimate_prompt_tokens(base) == 2


def test_estimate_prompt_tokens_counts_reasoning_metadata() -> None:
    base = [
        Message(role=Role.USER, content="hi"),
        Message(role=Role.ASSISTANT, content=None),
    ]
    with_reasoning = [
        Message(role=Role.USER, content="hi"),
        Message(
            role=Role.ASSISTANT,
            content=None,
            metadata={"reasoning_content": "abcdefgh"},
        ),
    ]

    assert estimate_prompt_tokens(with_reasoning) - estimate_prompt_tokens(base) == 2


def test_estimate_prompt_tokens_counts_tool_result_ids() -> None:
    messages = [
        Message(role=Role.USER, content="hi"),
        Message(role=Role.TOOL, content="ok", tool_call_id="abcdefgh"),
    ]

    assert estimate_prompt_tokens(messages) == 11


def test_inference_engine_stream_sync_defaults_to_generate() -> None:
    class _StubEngine(InferenceEngine):
        engine_id = "stub"

        def generate(
            self,
            messages,
            *,
            model,
            temperature=0.7,
            max_tokens=1024,
            **kwargs,
        ):
            return {"content": "Hello"}

        def list_models(self) -> list[str]:
            return ["stub"]

        def health(self) -> bool:
            return True

        async def stream(
            self,
            messages,
            *,
            model,
            temperature=0.7,
            max_tokens=1024,
            **kwargs,
        ):
            yield ""

    engine = _StubEngine()
    tokens = list(
        engine.stream_sync([Message(role=Role.USER, content="hi")], model="stub")
    )
    assert tokens == ["Hello"]


def test_messages_to_dicts_annotates_voice_wake_source() -> None:
    messages = [
        Message(
            role=Role.USER,
            content="lance le bloc-notes",
            metadata={"source": "voice_wake"},
        ),
    ]

    dicts = messages_to_dicts(messages)

    assert dicts[0]["content"] == "[Source: voice_wake] lance le bloc-notes"


def test_messages_to_dicts_omits_source_tag_without_metadata() -> None:
    dicts = messages_to_dicts([Message(role=Role.USER, content="hi")])

    assert dicts[0]["content"] == "hi"


def test_messages_to_dicts_handles_empty_content_with_source() -> None:
    dicts = messages_to_dicts(
        [Message(role=Role.USER, content="", metadata={"source": "voice"})],
    )

    assert dicts[0]["content"] == "[Source: voice]"
