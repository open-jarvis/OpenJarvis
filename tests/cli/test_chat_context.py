"""Tests for chat grounding / tool defaults."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from openjarvis.cli._chat_context import (
    ensure_chat_tool_names,
    memory_context_messages,
    preflight_web_block,
)
from openjarvis.core.config import JarvisConfig
from openjarvis.core.types import Message, Role


def test_ensure_chat_tool_names_adds_web_search() -> None:
    out = ensure_chat_tool_names(["think"], require_web_search=True)
    assert "web_search" in out
    assert "think" in out


def test_ensure_chat_tool_names_adds_memory_retrieve() -> None:
    out = ensure_chat_tool_names(
        ["web_search"],
        require_web_search=False,
        require_memory_retrieve=True,
    )
    assert out == ["web_search", "memory_retrieve"]


def test_ensure_chat_tool_names_idempotent() -> None:
    out = ensure_chat_tool_names(
        ["web_search", "memory_retrieve"],
        require_web_search=True,
        require_memory_retrieve=True,
    )
    assert out.count("web_search") == 1
    assert out.count("memory_retrieve") == 1


def test_memory_context_messages_disabled() -> None:
    cfg = JarvisConfig()
    cfg.agent.context_from_memory = False
    assert memory_context_messages("query", cfg) == []


def test_memory_context_messages_injects() -> None:
    cfg = JarvisConfig()
    cfg.agent.context_from_memory = True
    ctx_msg = Message(role=Role.SYSTEM, content="retrieved block")
    with patch("openjarvis.cli.ask._get_memory_backend") as get_b:
        get_b.return_value = MagicMock()
        with patch(
            "openjarvis.tools.storage.context.inject_context",
            return_value=[ctx_msg],
        ):
            msgs = memory_context_messages("hello", cfg)
    assert len(msgs) == 1
    assert "retrieved" in msgs[0].content


def test_preflight_web_block_skips_meta() -> None:
    assert preflight_web_block("czy używasz web-search?") is None


def test_tools_config_auto_learn_default_off() -> None:
    cfg = JarvisConfig()
    assert cfg.tools.auto_learn_qdrant is False
    assert cfg.tools.require_web_search is True
