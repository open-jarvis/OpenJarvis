"""Tests for ClaudeCodeAgent."""

from __future__ import annotations

import json
import subprocess
from unittest.mock import MagicMock, patch

import pytest

import openjarvis.agents  # noqa: F401 -- trigger registration
from openjarvis.agents._stubs import AgentResult
from openjarvis.agents.claude_code import (
    _OUTPUT_END,
    _OUTPUT_START,
    ClaudeCodeAgent,
)
from openjarvis.core.events import EventBus, EventType
from openjarvis.core.registry import AgentRegistry

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SENTINEL_WRAP = "{start}\n{payload}\n{end}"


def _wrap_output(payload: dict) -> str:
    """Wrap a dict in sentinel markers like the runner would."""
    return _SENTINEL_WRAP.format(
        start=_OUTPUT_START,
        payload=json.dumps(payload),
        end=_OUTPUT_END,
    )


def _mock_proc(
    stdout: str = "",
    stderr: str = "",
    returncode: int = 0,
) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(
        args=["node", "dist/index.js"],
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
    )


# ---------------------------------------------------------------------------
# Registration tests
# ---------------------------------------------------------------------------


class TestClaudeCodeRegistration:
    def test_agent_id(self):
        engine = MagicMock()
        engine.engine_id = "mock"
        agent = ClaudeCodeAgent(engine, "test-model")
        assert agent.agent_id == "claude_code"

    def test_accepts_tools_false(self):
        assert ClaudeCodeAgent.accepts_tools is False

    def test_registry_key(self):
        AgentRegistry.register_value("claude_code", ClaudeCodeAgent)
        assert AgentRegistry.contains("claude_code")
        cls = AgentRegistry.get("claude_code")
        assert cls is ClaudeCodeAgent


# ---------------------------------------------------------------------------
# _ensure_runner tests
# ---------------------------------------------------------------------------


class TestEnsureRunner:
    def test_raises_when_node_not_found(self):
        engine = MagicMock()
        engine.engine_id = "mock"
        agent = ClaudeCodeAgent(engine, "test-model")
        with patch("shutil.which", return_value=None):
            with pytest.raises(RuntimeError, match="Node.js"):
                agent._ensure_runner()

    def test_creates_runner_dir(self, tmp_path):
        engine = MagicMock()
        engine.engine_id = "mock"
        agent = ClaudeCodeAgent(engine, "test-model")

        home_dir = tmp_path / "home"
        home_dir.mkdir()

        with (
            patch("shutil.which", return_value="/usr/bin/node"),
            patch("pathlib.Path.home", return_value=home_dir),
            patch("subprocess.run") as mock_run,
        ):
            mock_run.return_value = _mock_proc()
            dest = home_dir / ".openjarvis" / "claude_code_runner"
            result = agent._ensure_runner()
            assert result == dest
            mock_run.assert_called_once()
            call_args = mock_run.call_args
            assert "npm" in call_args[0][0][0]

    def test_skips_npm_install_when_node_modules_exists(self, tmp_path):
        engine = MagicMock()
        engine.engine_id = "mock"
        agent = ClaudeCodeAgent(engine, "test-model")

        home_dir = tmp_path / "home"
        dest = home_dir / ".openjarvis" / "claude_code_runner"
        dest.mkdir(parents=True)
        (dest / "node_modules").mkdir()

        with (
            patch("shutil.which", return_value="/usr/bin/node"),
            patch("pathlib.Path.home", return_value=home_dir),
            patch("subprocess.run") as mock_run,
        ):
            agent._ensure_runner()
            mock_run.assert_not_called()


# ---------------------------------------------------------------------------
# run() tests
# ---------------------------------------------------------------------------


class TestClaudeCodeRun:
    def _make_agent(self, **kwargs):
        engine = MagicMock()
        engine.engine_id = "mock"
        defaults = {
            "api_key": "test-key",
            "workspace": "/tmp/test",
        }
        defaults.update(kwargs)
        return ClaudeCodeAgent(engine, "test-model", **defaults)

    def test_successful_run(self):
        agent = self._make_agent()
        output = _wrap_output(
            {
                "content": "Hello from Claude Code!",
                "tool_results": [],
                "metadata": {"message_count": 3},
            }
        )
        proc = _mock_proc(stdout=output)

        with (
            patch.object(
                agent,
                "_ensure_runner",
                return_value="/fake/runner",
            ),
            patch("subprocess.run", return_value=proc),
        ):
            result = agent.run("Say hello")

        assert isinstance(result, AgentResult)
        assert result.content == "Hello from Claude Code!"
        assert result.turns == 1
        assert result.tool_results == []
        assert result.metadata["message_count"] == 3

    def test_run_with_tool_results(self):
        agent = self._make_agent()
        output = _wrap_output(
            {
                "content": "I read the file.",
                "tool_results": [
                    {
                        "tool_name": "Read",
                        "content": "file contents",
                        "success": True,
                    },
                ],
                "metadata": {},
            }
        )
        proc = _mock_proc(stdout=output)

        with (
            patch.object(
                agent,
                "_ensure_runner",
                return_value="/fake/runner",
            ),
            patch("subprocess.run", return_value=proc),
        ):
            result = agent.run("Read main.py")

        assert len(result.tool_results) == 1
        assert result.tool_results[0].tool_name == "Read"
        assert result.tool_results[0].content == "file contents"
        assert result.tool_results[0].success is True

    def test_stdin_json_payload(self):
        agent = self._make_agent(
            api_key="sk-test",
            workspace="/projects/myapp",
            session_id="sess-123",
            allowed_tools=["Read", "Write"],
            system_prompt="Be helpful.",
        )
        output = _wrap_output(
            {
                "content": "ok",
                "tool_results": [],
                "metadata": {},
            }
        )
        proc = _mock_proc(stdout=output)

        with (
            patch.object(
                agent,
                "_ensure_runner",
                return_value="/fake/runner",
            ),
            patch(
                "subprocess.run",
                return_value=proc,
            ) as mock_run,
        ):
            agent.run("Do something")

        call_kwargs = mock_run.call_args
        stdin_json = json.loads(call_kwargs.kwargs["input"])
        assert stdin_json["prompt"] == "Do something"
        assert stdin_json["api_key"] == "sk-test"
        assert stdin_json["workspace"] == "/projects/myapp"
        assert stdin_json["session_id"] == "sess-123"
        assert stdin_json["allowed_tools"] == ["Read", "Write"]
        assert stdin_json["system_prompt"] == "Be helpful."

    def test_timeout_handling(self):
        agent = self._make_agent(timeout=5)
        exc = subprocess.TimeoutExpired(
            cmd="node",
            timeout=5,
        )

        with (
            patch.object(
                agent,
                "_ensure_runner",
                return_value="/fake/runner",
            ),
            patch("subprocess.run", side_effect=exc),
        ):
            result = agent.run("Slow task")

        assert "timed out" in result.content
        assert result.metadata["error"] is True
        assert result.metadata["error_type"] == "timeout"

    def test_nonzero_exit_code(self):
        agent = self._make_agent()
        proc = _mock_proc(
            returncode=1,
            stderr="ENOENT: module not found",
        )

        with (
            patch.object(
                agent,
                "_ensure_runner",
                return_value="/fake/runner",
            ),
            patch("subprocess.run", return_value=proc),
        ):
            result = agent.run("Failing task")

        assert "failed" in result.content.lower()
        assert "ENOENT" in result.content
        assert result.metadata["error"] is True
        assert result.metadata["returncode"] == 1

    def test_no_sentinels_in_output(self):
        """Plain text without sentinels used as content."""
        agent = self._make_agent()
        proc = _mock_proc(stdout="Some plain text output")

        with (
            patch.object(
                agent,
                "_ensure_runner",
                return_value="/fake/runner",
            ),
            patch("subprocess.run", return_value=proc),
        ):
            result = agent.run("Query")

        assert result.content == "Some plain text output"
        assert result.tool_results == []

    def test_malformed_json_in_sentinels(self):
        """Sentinel-wrapped content is not valid JSON."""
        agent = self._make_agent()
        bad = f"{_OUTPUT_START}\nnot valid json\n{_OUTPUT_END}"
        proc = _mock_proc(stdout=bad)

        with (
            patch.object(
                agent,
                "_ensure_runner",
                return_value="/fake/runner",
            ),
            patch("subprocess.run", return_value=proc),
        ):
            result = agent.run("Query")

        assert result.metadata.get("parse_error") is True


# ---------------------------------------------------------------------------
# Event bus tests
# ---------------------------------------------------------------------------


class TestClaudeCodeEvents:
    def test_emits_turn_start_and_end(self):
        bus = EventBus(record_history=True)
        engine = MagicMock()
        engine.engine_id = "mock"
        agent = ClaudeCodeAgent(
            engine,
            "test-model",
            bus=bus,
            api_key="k",
        )
        output = _wrap_output(
            {
                "content": "hi",
                "tool_results": [],
                "metadata": {},
            }
        )
        proc = _mock_proc(stdout=output)

        with (
            patch.object(
                agent,
                "_ensure_runner",
                return_value="/fake/runner",
            ),
            patch("subprocess.run", return_value=proc),
        ):
            agent.run("Hello")

        types = [e.event_type for e in bus.history]
        assert EventType.AGENT_TURN_START in types
        assert EventType.AGENT_TURN_END in types

    def test_turn_start_data(self):
        bus = EventBus(record_history=True)
        engine = MagicMock()
        engine.engine_id = "mock"
        agent = ClaudeCodeAgent(
            engine,
            "test-model",
            bus=bus,
            api_key="k",
        )
        output = _wrap_output(
            {
                "content": "hi",
                "tool_results": [],
                "metadata": {},
            }
        )
        proc = _mock_proc(stdout=output)

        with (
            patch.object(
                agent,
                "_ensure_runner",
                return_value="/fake/runner",
            ),
            patch("subprocess.run", return_value=proc),
        ):
            agent.run("test input")

        start_events = [
            e for e in bus.history if e.event_type == EventType.AGENT_TURN_START
        ]
        assert len(start_events) == 1
        assert start_events[0].data["agent"] == "claude_code"
        assert start_events[0].data["input"] == "test input"

    def test_error_emits_turn_end(self):
        bus = EventBus(record_history=True)
        engine = MagicMock()
        engine.engine_id = "mock"
        agent = ClaudeCodeAgent(
            engine,
            "test-model",
            bus=bus,
            api_key="k",
        )
        proc = _mock_proc(returncode=1, stderr="error")

        with (
            patch.object(
                agent,
                "_ensure_runner",
                return_value="/fake/runner",
            ),
            patch("subprocess.run", return_value=proc),
        ):
            agent.run("Fail")

        types = [e.event_type for e in bus.history]
        assert EventType.AGENT_TURN_END in types


# ---------------------------------------------------------------------------
# _parse_output unit tests
# ---------------------------------------------------------------------------


class TestParseOutput:
    def test_parses_valid_sentinels(self):
        payload = {
            "content": "hello",
            "tool_results": [],
            "metadata": {"k": "v"},
        }
        stdout = _wrap_output(payload)
        content, tools, meta = ClaudeCodeAgent._parse_output(
            stdout,
        )
        assert content == "hello"
        assert tools == []
        assert meta == {"k": "v"}

    def test_no_sentinels(self):
        content, tools, meta = ClaudeCodeAgent._parse_output(
            "plain text",
        )
        assert content == "plain text"
        assert tools == []
        assert meta == {}

    def test_tool_results_parsed(self):
        payload = {
            "content": "done",
            "tool_results": [
                {
                    "tool_name": "Bash",
                    "content": "output",
                    "success": True,
                },
                {
                    "tool_name": "Write",
                    "content": "wrote file",
                    "success": False,
                },
            ],
            "metadata": {},
        }
        stdout = _wrap_output(payload)
        content, tools, meta = ClaudeCodeAgent._parse_output(
            stdout,
        )
        assert len(tools) == 2
        assert tools[0].tool_name == "Bash"
        assert tools[0].success is True
        assert tools[1].tool_name == "Write"
        assert tools[1].success is False

    def test_extra_stdout_before_sentinels(self):
        """Runner may log before sentinels -- should parse."""
        payload = {
            "content": "result",
            "tool_results": [],
            "metadata": {},
        }
        stdout = "some debug output\n" + _wrap_output(payload) + "\nmore output"
        content, tools, meta = ClaudeCodeAgent._parse_output(
            stdout,
        )
        assert content == "result"

    def test_invalid_json(self):
        stdout = f"{_OUTPUT_START}\n{{broken\n{_OUTPUT_END}"
        content, tools, meta = ClaudeCodeAgent._parse_output(
            stdout,
        )
        assert meta.get("parse_error") is True


# ---------------------------------------------------------------------------
# Constructor defaults tests
# ---------------------------------------------------------------------------


class TestClaudeCodeDefaults:
    def test_default_api_key_from_env(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "env-key-123")
        engine = MagicMock()
        engine.engine_id = "mock"
        agent = ClaudeCodeAgent(engine, "test-model")
        assert agent._api_key == "env-key-123"

    def test_explicit_api_key_overrides_env(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "env-key")
        engine = MagicMock()
        engine.engine_id = "mock"
        agent = ClaudeCodeAgent(
            engine,
            "test-model",
            api_key="explicit-key",
        )
        assert agent._api_key == "explicit-key"

    def test_default_timeout(self):
        engine = MagicMock()
        engine.engine_id = "mock"
        agent = ClaudeCodeAgent(engine, "test-model")
        assert agent._timeout == 300

    def test_custom_timeout(self):
        engine = MagicMock()
        engine.engine_id = "mock"
        agent = ClaudeCodeAgent(
            engine,
            "test-model",
            timeout=60,
        )
        assert agent._timeout == 60

    def test_no_bus_works(self):
        engine = MagicMock()
        engine.engine_id = "mock"
        agent = ClaudeCodeAgent(
            engine,
            "test-model",
            api_key="k",
        )
        output = _wrap_output(
            {
                "content": "ok",
                "tool_results": [],
                "metadata": {},
            }
        )
        proc = _mock_proc(stdout=output)

        with (
            patch.object(
                agent,
                "_ensure_runner",
                return_value="/fake/runner",
            ),
            patch("subprocess.run", return_value=proc),
        ):
            result = agent.run("Hello")

        assert result.content == "ok"
