"""Tests for ContainerRunner and SandboxedAgent."""

from __future__ import annotations

import json
import subprocess
from unittest.mock import MagicMock, patch

import pytest

from openjarvis.agents._stubs import AgentResult, BaseAgent
from openjarvis.core.events import EventBus, EventType
from openjarvis.sandbox.runner import (
    _OUTPUT_END,
    _OUTPUT_START,
    ContainerRunner,
    SandboxedAgent,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _wrap_output(payload: dict) -> str:
    return f"{_OUTPUT_START}\n{json.dumps(payload)}\n{_OUTPUT_END}"


def _mock_proc(
    stdout: str = "",
    stderr: str = "",
    returncode: int = 0,
) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(
        args=["docker", "run"],
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
    )


# ---------------------------------------------------------------------------
# ContainerRunner tests
# ---------------------------------------------------------------------------


class TestContainerRunnerInit:
    def test_defaults(self):
        runner = ContainerRunner()
        assert runner._image == ContainerRunner.DEFAULT_IMAGE
        assert runner._timeout == ContainerRunner.DEFAULT_TIMEOUT
        assert runner._runtime == "docker"
        assert runner._max_concurrent == 5

    def test_custom_values(self):
        runner = ContainerRunner(
            image="custom:latest",
            timeout=600,
            max_concurrent=10,
            runtime="podman",
        )
        assert runner._image == "custom:latest"
        assert runner._timeout == 600
        assert runner._runtime == "podman"
        assert runner._max_concurrent == 10


class TestBuildDockerArgs:
    def test_basic_args(self):
        runner = ContainerRunner()
        with patch("shutil.which", return_value="/usr/bin/docker"):
            args = runner._build_docker_args(
                "test-container",
                [],
                None,
            )
        assert "/usr/bin/docker" in args
        assert "run" in args
        assert "--rm" in args
        assert "--name" in args
        assert "test-container" in args
        assert "--network" in args
        assert "none" in args
        assert runner._image in args

    def test_with_mounts(self):
        runner = ContainerRunner()
        with patch("shutil.which", return_value="/usr/bin/docker"):
            args = runner._build_docker_args(
                "test-container",
                ["/data/project"],
                None,
            )
        assert "-v" in args
        idx = args.index("-v")
        assert args[idx + 1] == "/data/project:/data/project:ro"

    def test_with_env(self):
        runner = ContainerRunner()
        with patch("shutil.which", return_value="/usr/bin/docker"):
            args = runner._build_docker_args(
                "test-container",
                [],
                {"FOO": "bar"},
            )
        assert "-e" in args
        idx = args.index("-e")
        assert args[idx + 1] == "FOO=bar"


class TestContainerRunnerRun:
    def test_successful_run(self):
        runner = ContainerRunner()
        output = _wrap_output({"content": "Hello!"})
        with (
            patch("shutil.which", return_value="/usr/bin/docker"),
            patch(
                "subprocess.run",
                return_value=_mock_proc(
                    stdout=output,
                ),
            ),
        ):
            result = runner.run({"prompt": "test"})
        assert result["content"] == "Hello!"

    def test_timeout(self):
        runner = ContainerRunner(timeout=5)
        with (
            patch("shutil.which", return_value="/usr/bin/docker"),
            patch(
                "subprocess.run",
                side_effect=subprocess.TimeoutExpired(
                    cmd=["docker"],
                    timeout=5,
                ),
            ),
            patch.object(runner, "stop"),
        ):
            result = runner.run({"prompt": "test"})
        assert result["error"] is True
        assert result["error_type"] == "timeout"

    def test_nonzero_exit(self):
        runner = ContainerRunner()
        with (
            patch("shutil.which", return_value="/usr/bin/docker"),
            patch(
                "subprocess.run",
                return_value=_mock_proc(
                    returncode=1,
                    stderr="OOM killed",
                ),
            ),
        ):
            result = runner.run({"prompt": "test"})
        assert result["error"] is True
        assert "OOM killed" in result["content"]

    def test_no_sentinel_output(self):
        runner = ContainerRunner()
        with (
            patch("shutil.which", return_value="/usr/bin/docker"),
            patch(
                "subprocess.run",
                return_value=_mock_proc(
                    stdout="plain text output",
                ),
            ),
        ):
            result = runner.run({"prompt": "test"})
        assert result["content"] == "plain text output"


class TestContainerRunnerRuntimeCheck:
    def test_raises_when_runtime_not_found(self):
        runner = ContainerRunner()
        with patch("shutil.which", return_value=None):
            with pytest.raises(RuntimeError, match="not found"):
                runner._check_runtime()


class TestCleanupOrphans:
    def test_cleanup_orphans(self):
        runner = ContainerRunner()
        with (
            patch("shutil.which", return_value="/usr/bin/docker"),
            patch("subprocess.run") as mock_run,
        ):
            mock_run.return_value = _mock_proc(stdout="abc123\ndef456")
            runner.cleanup_orphans()
        assert mock_run.call_count == 2  # ps + rm


class TestContainerRunnerParseOutput:
    def test_parse_valid_json(self):
        output = _wrap_output({"content": "result", "metadata": {}})
        result = ContainerRunner._parse_output(output)
        assert result["content"] == "result"

    def test_parse_no_sentinels(self):
        result = ContainerRunner._parse_output("plain output")
        assert result["content"] == "plain output"

    def test_parse_invalid_json(self):
        output = f"{_OUTPUT_START}\nnot-json\n{_OUTPUT_END}"
        result = ContainerRunner._parse_output(output)
        assert result.get("parse_error") is True


# ---------------------------------------------------------------------------
# SandboxedAgent tests
# ---------------------------------------------------------------------------


class TestSandboxedAgentInit:
    def test_accepts_tools_false(self):
        assert SandboxedAgent.accepts_tools is False

    def test_agent_id(self):
        assert SandboxedAgent.agent_id == "sandboxed"

    def test_wraps_agent(self):
        inner = MagicMock(spec=BaseAgent)
        inner.agent_id = "inner"
        inner._engine = MagicMock()
        inner._model = "test-model"
        runner = MagicMock(spec=ContainerRunner)

        agent = SandboxedAgent(
            inner,
            runner,
            engine=inner._engine,
            model="test-model",
        )
        assert agent._wrapped_agent is inner
        assert agent._runner is runner


class TestSandboxedAgentRun:
    def test_delegates_to_runner(self):
        inner = MagicMock(spec=BaseAgent)
        inner.agent_id = "test"
        inner._model = "test-model"
        runner = MagicMock(spec=ContainerRunner)
        runner.run.return_value = {
            "content": "sandbox result",
            "tool_results": [],
            "metadata": {},
        }

        engine = MagicMock()
        agent = SandboxedAgent(
            inner,
            runner,
            engine=engine,
            model="test-model",
        )
        result = agent.run("hello")

        assert isinstance(result, AgentResult)
        assert result.content == "sandbox result"
        assert result.turns == 1
        runner.run.assert_called_once()

    def test_parses_tool_results(self):
        inner = MagicMock(spec=BaseAgent)
        inner.agent_id = "test"
        inner._model = "m"
        runner = MagicMock(spec=ContainerRunner)
        runner.run.return_value = {
            "content": "done",
            "tool_results": [
                {
                    "tool_name": "calc",
                    "content": "42",
                    "success": True,
                },
            ],
        }

        engine = MagicMock()
        agent = SandboxedAgent(
            inner,
            runner,
            engine=engine,
            model="m",
        )
        result = agent.run("compute")

        assert len(result.tool_results) == 1
        assert result.tool_results[0].tool_name == "calc"
        assert result.tool_results[0].content == "42"

    def test_emits_events(self):
        inner = MagicMock(spec=BaseAgent)
        inner.agent_id = "test"
        inner._model = "m"
        runner = MagicMock(spec=ContainerRunner)
        runner.run.return_value = {"content": "ok"}

        bus = EventBus(record_history=True)
        engine = MagicMock()
        agent = SandboxedAgent(
            inner,
            runner,
            engine=engine,
            model="m",
            bus=bus,
        )
        agent.run("test")

        types = [e.event_type for e in bus.history]
        assert EventType.AGENT_TURN_START in types
        assert EventType.AGENT_TURN_END in types
