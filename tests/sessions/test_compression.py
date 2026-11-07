from __future__ import annotations

import pytest

from friday_ai.core.registry import CompressionRegistry
from friday_ai.core.types import Message, Role


@pytest.fixture(autouse=True)
def _register_compressors():
    """Re-register compression strategies after registry clear."""
    from friday_ai.sessions.compression import (
        ModelSummarization,
        RuleBasedPrecompression,
        SessionConsolidation,
        TieredSummaries,
    )

    for key, cls in [
        ("session_consolidation", SessionConsolidation),
        ("rule_based_precompression", RuleBasedPrecompression),
        ("model_summarization", ModelSummarization),
        ("tiered_summaries", TieredSummaries),
    ]:
        if not CompressionRegistry.contains(key):
            CompressionRegistry.register_value(key, cls)


def _make_messages(n: int) -> list[Message]:
    msgs = []
    for i in range(n):
        role = Role.USER if i % 2 == 0 else Role.ASSISTANT
        msgs.append(Message(role=role, content=f"Message {i}"))
    return msgs


def test_rule_based_strips_tool_boilerplate():
    from friday_ai.sessions.compression import RuleBasedPrecompression

    compressor = RuleBasedPrecompression()
    long_snippet = "x" * 5000
    tool_output = (
        '{"results": [{"title": "Result 1",'
        f' "snippet": "A very long snippet {long_snippet}"'
        "}]}"
    )
    msgs = [
        Message(role=Role.ASSISTANT, content="Let me search."),
        Message(role=Role.TOOL, content=tool_output),
        Message(
            role=Role.ASSISTANT,
            content="Based on the search, here is the answer.",
        ),
    ]
    result = compressor.compress(msgs, threshold=0.5)
    total_len = sum(len(m.content) for m in result)
    original_len = sum(len(m.content) for m in msgs)
    assert total_len < original_len


def test_session_consolidation_preserves_recent():
    from friday_ai.sessions.compression import SessionConsolidation

    compressor = SessionConsolidation()
    msgs = _make_messages(20)
    result = compressor.compress(msgs, threshold=0.5)
    assert len(result) < 20
    assert result[-1].content == msgs[-1].content


def test_compression_registry():
    from friday_ai.core.registry import CompressionRegistry
    from friday_ai.sessions.compression import RuleBasedPrecompression

    assert CompressionRegistry.contains("rule_based_precompression")
    cls = CompressionRegistry.get("rule_based_precompression")
    assert cls is RuleBasedPrecompression


def test_tiered_summaries_gradient():
    from friday_ai.sessions.compression import TieredSummaries

    compressor = TieredSummaries()
    msgs = _make_messages(20)
    result = compressor.compress(msgs, threshold=0.5)
    assert len(result) < 20
    # Recent messages should be preserved
    assert result[-1].content == msgs[-1].content
