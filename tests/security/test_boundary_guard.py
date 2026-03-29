"""Tests for BoundaryGuard — scanning at device exit points."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List

import pytest

from openjarvis.core.types import ToolCall

# ---------------------------------------------------------------------------
# Lightweight mock scanners that don't depend on Rust
# ---------------------------------------------------------------------------

@dataclass
class _Finding:
    pattern_name: str
    matched_text: str
    threat_level: str = "CRITICAL"


@dataclass
class _ScanResult:
    findings: List[_Finding] = field(default_factory=list)


class _MockSecretScanner:
    """Regex-only secret scanner for testing without Rust."""

    _PATTERNS = [
        ("openai_key", re.compile(r"sk-[A-Za-z0-9_-]{20,}")),
        ("aws_key", re.compile(r"AKIA[0-9A-Z]{16}")),
        ("slack_token", re.compile(r"xoxb-[0-9A-Za-z\-]+")),
    ]

    def scan(self, text: str) -> _ScanResult:
        findings = []
        for name, pattern in self._PATTERNS:
            for m in pattern.finditer(text):
                findings.append(_Finding(pattern_name=name, matched_text=m.group()))
        return _ScanResult(findings=findings)

    def redact(self, text: str) -> str:
        for name, pattern in self._PATTERNS:
            text = pattern.sub(f"[REDACTED:{name}]", text)
        return text


def _make_guard(mode: str = "redact", enabled: bool = True):
    """Create a BoundaryGuard with mock scanners (no Rust needed)."""
    from openjarvis.security.boundary import BoundaryGuard

    return BoundaryGuard(
        mode=mode,
        enabled=enabled,
        scanners=[_MockSecretScanner()],
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestBoundaryGuardScanOutbound:
    """scan_outbound should detect and redact secrets/PII."""

    def test_redacts_openai_key(self) -> None:
        guard = _make_guard(mode="redact")
        text = "Use this key: sk-proj-abc123def456ghi789jkl012mno345pqr678stu"
        result = guard.scan_outbound(text, destination="openai")
        assert "sk-proj-" not in result
        assert "[REDACTED" in result

    def test_redacts_aws_key(self) -> None:
        guard = _make_guard(mode="redact")
        text = "AWS key: AKIAIOSFODNN7EXAMPLE"
        result = guard.scan_outbound(text, destination="openai")
        assert "AKIAIOSFODNN7EXAMPLE" not in result

    def test_warn_mode_does_not_alter_text(self) -> None:
        guard = _make_guard(mode="warn")
        text = "Use this key: sk-proj-abc123def456ghi789jkl012mno345pqr678stu"
        result = guard.scan_outbound(text, destination="openai")
        assert result == text

    def test_block_mode_raises(self) -> None:
        from openjarvis.security.boundary import SecurityBlockError

        guard = _make_guard(mode="block")
        text = "Use this key: sk-proj-abc123def456ghi789jkl012mno345pqr678stu"
        with pytest.raises(SecurityBlockError):
            guard.scan_outbound(text, destination="openai")

    def test_clean_text_passes_through(self) -> None:
        guard = _make_guard(mode="redact")
        text = "Hello, how are you?"
        result = guard.scan_outbound(text, destination="openai")
        assert result == text


class TestBoundaryGuardCheckOutbound:
    """check_outbound should redact secrets in tool call arguments."""

    def test_redacts_tool_call_arguments(self) -> None:
        guard = _make_guard(mode="redact")
        tc = ToolCall(
            id="test_1",
            name="web_search",
            arguments=(
                '{"query": "my key is sk-proj-abc123def456ghi789jkl012mno345pqr678stu"}'
            ),
        )
        result = guard.check_outbound(tc)
        assert "sk-proj-" not in result.arguments
        assert result.id == "test_1"
        assert result.name == "web_search"

    def test_clean_args_pass_through(self) -> None:
        guard = _make_guard(mode="redact")
        tc = ToolCall(id="test_2", name="web_search", arguments='{"query": "weather"}')
        result = guard.check_outbound(tc)
        assert result.arguments == tc.arguments

    def test_block_mode_raises_on_tool_call(self) -> None:
        from openjarvis.security.boundary import SecurityBlockError

        guard = _make_guard(mode="block")
        tc = ToolCall(
            id="test_3",
            name="web_search",
            arguments='{"query": "AKIAIOSFODNN7EXAMPLE"}',
        )
        with pytest.raises(SecurityBlockError):
            guard.check_outbound(tc)


class TestBoundaryGuardDisabled:
    """When disabled, BoundaryGuard should pass everything through."""

    def test_disabled_passes_secrets_through(self) -> None:
        guard = _make_guard(mode="redact", enabled=False)
        text = "sk-proj-abc123def456ghi789jkl012mno345pqr678stu"
        result = guard.scan_outbound(text, destination="openai")
        assert result == text


class TestEngineTagging:
    """Cloud engines must have is_cloud=True, local engines is_cloud=False."""

    def test_inference_engine_default_is_local(self) -> None:
        from openjarvis.engine._stubs import InferenceEngine

        assert InferenceEngine.is_cloud is False

    def test_cloud_engine_is_cloud(self) -> None:
        from openjarvis.engine.cloud import CloudEngine

        assert CloudEngine.is_cloud is True

    def test_litellm_engine_is_cloud(self) -> None:
        from openjarvis.engine.litellm import LiteLLMEngine

        assert LiteLLMEngine.is_cloud is True

    def test_ollama_engine_is_local(self) -> None:
        from openjarvis.engine.ollama import OllamaEngine

        assert OllamaEngine.is_cloud is False


class TestToolTagging:
    """External tools must have is_local=False, local tools is_local=True."""

    def test_base_tool_default_is_local(self) -> None:
        from openjarvis.tools._stubs import BaseTool

        assert BaseTool.is_local is True

    def test_web_search_is_external(self) -> None:
        from openjarvis.tools.web_search import WebSearchTool

        assert WebSearchTool.is_local is False

    def test_http_request_is_external(self) -> None:
        from openjarvis.tools.http_request import HttpRequestTool

        assert HttpRequestTool.is_local is False

    def test_channel_send_is_external(self) -> None:
        from openjarvis.tools.channel_tools import ChannelSendTool

        assert ChannelSendTool.is_local is False

    def test_think_tool_is_local(self) -> None:
        from openjarvis.tools.think import ThinkTool

        assert ThinkTool.is_local is True

    def test_calculator_is_local(self) -> None:
        from openjarvis.tools.calculator import CalculatorTool

        assert CalculatorTool.is_local is True


class TestToolExecutorBoundaryIntegration:
    """ToolExecutor should use BoundaryGuard for external tool calls."""

    def _make_executor(self, boundary_guard=None):
        from openjarvis.tools._stubs import BaseTool, ToolExecutor, ToolSpec

        class FakeExternalTool(BaseTool):
            tool_id = "fake_external"
            is_local = False

            @property
            def spec(self):
                return ToolSpec(
                    name="fake_external",
                    description="test",
                    parameters={
                        "type": "object",
                        "properties": {"q": {"type": "string"}},
                    },
                )

            def execute(self, **params):
                from openjarvis.core.types import ToolResult

                return ToolResult(
                    tool_name="fake_external",
                    content=f"result for {params.get('q', '')}",
                    success=True,
                )

        return ToolExecutor(
            tools=[FakeExternalTool()],
            boundary_guard=boundary_guard,
        )

    def test_external_tool_args_scanned(self) -> None:
        guard = _make_guard(mode="redact")
        executor = self._make_executor(boundary_guard=guard)

        tc = ToolCall(
            id="t1",
            name="fake_external",
            arguments=(
                '{"q": "my key is sk-proj-abc123def456ghi789jkl012mno345pqr678stu"}'
            ),
        )
        result = executor.execute(tc)
        assert "sk-proj-" not in result.content

    def test_no_guard_passes_through(self) -> None:
        executor = self._make_executor(boundary_guard=None)
        tc = ToolCall(
            id="t2",
            name="fake_external",
            arguments='{"q": "sk-proj-abc123def456ghi789jkl012mno345pqr678stu"}',
        )
        result = executor.execute(tc)
        assert "sk-proj-" in result.content
