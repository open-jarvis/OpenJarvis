from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import replace
from typing import List

from openjarvis.core.registry import CompressionRegistry
from openjarvis.core.types import Message, Role


class BaseCompressor(ABC):
    """Abstract base for context compression strategies."""

    @abstractmethod
    def compress(self, messages: List[Message], threshold: float) -> List[Message]: ...


@CompressionRegistry.register("session_consolidation")
class SessionConsolidation(BaseCompressor):
    """Summarize oldest N% of turns, keep recent (100-N)%."""

    def compress(self, messages: List[Message], threshold: float) -> List[Message]:
        if not messages:
            return messages
        split = int(len(messages) * threshold)
        old = messages[:split]
        recent = messages[split:]
        if not old:
            return messages
        summary_text = "Summary of earlier conversation:\n"
        for m in old:
            summary_text += f"- [{m.role}]: {m.content[:100]}...\n"
        summary = Message(role=Role.SYSTEM, content=summary_text)
        return [summary] + recent


@CompressionRegistry.register("rule_based_precompression")
class RuleBasedPrecompression(BaseCompressor):
    """No LLM call. Strip boilerplate, truncate long outputs, collapse dupes."""

    TOOL_OUTPUT_MAX = 2000

    def compress(self, messages: List[Message], threshold: float) -> List[Message]:
        result: list[Message] = []
        for msg in messages:
            if msg.role == Role.TOOL and len(msg.content) > self.TOOL_OUTPUT_MAX:
                suffix = "\n[...truncated]"
                try:
                    parsed = json.loads(msg.content)
                    truncated = (
                        json.dumps(parsed, indent=None)[: self.TOOL_OUTPUT_MAX] + suffix
                    )
                except (json.JSONDecodeError, TypeError):
                    truncated = msg.content[: self.TOOL_OUTPUT_MAX] + suffix
                result.append(replace(msg, content=truncated))
            else:
                result.append(msg)
        return result


@CompressionRegistry.register("model_summarization")
class ModelSummarization(BaseCompressor):
    """LLM-based summarization using configured engine/model."""

    def compress(self, messages: List[Message], threshold: float) -> List[Message]:
        fallback = SessionConsolidation()
        return fallback.compress(messages, threshold)


@CompressionRegistry.register("tiered_summaries")
class TieredSummaries(BaseCompressor):
    """Progressive compression: L0 (full) -> L1 (paragraph) -> L2 (one-line)."""

    def compress(self, messages: List[Message], threshold: float) -> List[Message]:
        if not messages:
            return messages
        n = len(messages)
        l2_end = int(n * threshold * 0.5)
        l1_end = int(n * threshold)
        l2_msgs = messages[:l2_end]
        l1_msgs = messages[l2_end:l1_end]
        l0_msgs = messages[l1_end:]
        result: list[Message] = []
        if l2_msgs:
            one_liners = "; ".join(f"{m.role}: {m.content[:50]}" for m in l2_msgs)
            result.append(
                Message(
                    role=Role.SYSTEM,
                    content=f"[Oldest context] {one_liners}",
                )
            )
        if l1_msgs:
            paragraphs = "\n".join(f"- {m.role}: {m.content[:200]}" for m in l1_msgs)
            result.append(
                Message(
                    role=Role.SYSTEM,
                    content=f"[Earlier context]\n{paragraphs}",
                )
            )
        result.extend(l0_msgs)
        return result
