"""Tests for ClaudeCodeAgent."""

from __future__ import annotations

import errno
import json
import shutil
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import openjarvis.agents  # noqa: F401 -- trigger registration
from openjarvis.agents._stubs import AgentResult
from openjarvis.agents.claude_code import (
    _INSTALL_STATE_FILE,
    _OUTPUT_END,
    _OUTPUT_START,
    _RUNNER_SRC,
    ClaudeCodeAgent,
    _is_lock_contention,
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
        args=["node", "index.mjs"],
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
    )


def _create_mock_sdk_install(
    cwd: str,
    node_platform: str = "test",
    node_arch: str = "platform",
    node_libc: str = "",
) -> None:
    node_modules = Path(cwd) / "node_modules" / "@anthropic-ai"
    sdk_package = node_modules / "claude-agent-sdk" / "package.json"
    sdk_package.parent.mkdir(parents=True)
    sdk_package.write_text("{}")
    package_suffix = f"{node_platform}-{node_arch}"
    if node_platform == "linux" and node_libc == "musl":
        package_suffix += "-musl"
    executable = "claude.exe" if node_platform == "win32" else "claude"
    native_binary = node_modules / f"claude-agent-sdk-{package_suffix}" / executable
    native_binary.parent.mkdir(parents=True)
    native_binary.write_text("mock native binary")


def _mock_which(executable: str) -> str:
    return f"/usr/bin/{executable}"


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
    @pytest.fixture(autouse=True)
    def supported_node_version(self):
        with (
            patch(
                "openjarvis.agents.claude_code._node_major_version",
                return_value=22,
            ),
            patch(
                "openjarvis.agents.claude_code._node_runtime_platform",
                return_value=("test", "platform", ""),
            ),
        ):
            yield

    def test_raises_when_node_not_found(self):
        engine = MagicMock()
        engine.engine_id = "mock"
        agent = ClaudeCodeAgent(engine, "test-model")
        with patch("shutil.which", return_value=None):
            with pytest.raises(RuntimeError, match="Node.js"):
                agent._ensure_runner()

    def test_lock_retry_classification_rejects_filesystem_errors(self):
        assert _is_lock_contention(BlockingIOError(errno.EAGAIN, "busy"))
        assert not _is_lock_contention(OSError(errno.EINVAL, "unsupported"))

    def test_raises_when_node_is_too_old(self):
        engine = MagicMock()
        engine.engine_id = "mock"
        agent = ClaudeCodeAgent(engine, "test-model")

        with (
            patch("shutil.which", side_effect=_mock_which),
            patch(
                "openjarvis.agents.claude_code._node_major_version",
                return_value=20,
            ),
            pytest.raises(RuntimeError, match="found v20"),
        ):
            agent._ensure_runner()

    def test_raises_when_npm_not_found(self):
        engine = MagicMock()
        engine.engine_id = "mock"
        agent = ClaudeCodeAgent(engine, "test-model")

        def which(executable):
            return "/usr/bin/node" if executable == "node" else None

        with patch("shutil.which", side_effect=which):
            with pytest.raises(RuntimeError, match="npm"):
                agent._ensure_runner()

    def test_bundled_runner_has_runtime_entrypoint_and_lock(self):
        package = json.loads((_RUNNER_SRC / "package.json").read_text())

        assert package["main"] == "index.mjs"
        assert (_RUNNER_SRC / package["main"]).is_file()
        assert (_RUNNER_SRC / package["main"]).stat().st_size > 0
        assert (_RUNNER_SRC / "package-lock.json").is_file()
        assert "@anthropic-ai/claude-agent-sdk" in package["dependencies"]
        assert "@anthropic-ai/claude-code" not in package["dependencies"]

    def test_creates_complete_runner_dir(self, tmp_path, monkeypatch):
        engine = MagicMock()
        engine.engine_id = "mock"
        agent = ClaudeCodeAgent(engine, "test-model")

        home_dir = tmp_path / "home"
        monkeypatch.setenv("OPENJARVIS_HOME", str(home_dir))

        with (
            patch("shutil.which", side_effect=_mock_which),
            patch("subprocess.run") as mock_run,
        ):
            mock_run.side_effect = lambda *args, **kwargs: (
                _create_mock_sdk_install(kwargs["cwd"]) or _mock_proc()
            )
            result = agent._ensure_runner()
            assert result.parent == home_dir / "claude_code_runner"
            mock_run.assert_called_once()
            assert mock_run.call_args.args[0] == [
                "/usr/bin/npm",
                "ci",
                "--omit=dev",
                "--include=optional",
            ]

        package = json.loads((result / "package.json").read_text())
        assert (result / package["main"]).is_file()
        assert (result / agent._runner_entrypoint).is_file()
        assert agent._runner_entrypoint.startswith("index.")
        assert (result / "package-lock.json").is_file()
        assert (result / _INSTALL_STATE_FILE).is_file()

    def test_code_revisions_share_dependencies_with_immutable_entries(
        self, tmp_path, monkeypatch
    ):
        engine = MagicMock()
        engine.engine_id = "mock"
        agent = ClaudeCodeAgent(engine, "test-model")
        home_dir = tmp_path / "home"
        bundled = tmp_path / "bundled-runner"
        bundled.mkdir()
        for name in ("package.json", "package-lock.json", "index.mjs"):
            shutil.copy2(_RUNNER_SRC / name, bundled / name)
        monkeypatch.setenv("OPENJARVIS_HOME", str(home_dir))

        def install_sdk(*args, **kwargs):
            _create_mock_sdk_install(kwargs["cwd"])
            return _mock_proc()

        with (
            patch("shutil.which", side_effect=_mock_which),
            patch("openjarvis.agents.claude_code._RUNNER_SRC", bundled),
            patch("subprocess.run", side_effect=install_sdk) as mock_run,
        ):
            first_runner = agent._ensure_runner()
            first_entrypoint = agent._runner_entrypoint
            with (bundled / "index.mjs").open("a") as runner_source:
                runner_source.write("\n// next source revision\n")
            second_runner = agent._ensure_runner()
            second_entrypoint = agent._runner_entrypoint

        assert first_runner == second_runner
        assert first_entrypoint != second_entrypoint
        assert (first_runner / first_entrypoint).is_file()
        assert (second_runner / second_entrypoint).is_file()
        mock_run.assert_called_once()

    def test_skips_npm_install_when_cache_is_complete(self, tmp_path, monkeypatch):
        engine = MagicMock()
        engine.engine_id = "mock"
        agent = ClaudeCodeAgent(engine, "test-model")

        home_dir = tmp_path / "home"
        monkeypatch.setenv("OPENJARVIS_HOME", str(home_dir))

        def install_sdk(*args, **kwargs):
            _create_mock_sdk_install(kwargs["cwd"])
            return _mock_proc()

        with (
            patch("shutil.which", side_effect=_mock_which),
            patch("subprocess.run", side_effect=install_sdk) as mock_run,
        ):
            agent._ensure_runner()
            mock_run.reset_mock()
            agent._ensure_runner()
            mock_run.assert_not_called()

    def test_reinstalls_legacy_cache_with_node_modules(self, tmp_path, monkeypatch):
        engine = MagicMock()
        engine.engine_id = "mock"
        agent = ClaudeCodeAgent(engine, "test-model")

        home_dir = tmp_path / "home"
        legacy_dest = home_dir / "claude_code_runner"
        (legacy_dest / "node_modules").mkdir(parents=True)
        monkeypatch.setenv("OPENJARVIS_HOME", str(home_dir))

        with (
            patch("shutil.which", side_effect=_mock_which),
            patch("subprocess.run") as mock_run,
        ):
            mock_run.side_effect = lambda *args, **kwargs: (
                _create_mock_sdk_install(kwargs["cwd"]) or _mock_proc()
            )
            dest = agent._ensure_runner()

        mock_run.assert_called_once()
        assert mock_run.call_args.args[0] == [
            "/usr/bin/npm",
            "ci",
            "--omit=dev",
            "--include=optional",
        ]
        package = json.loads((dest / "package.json").read_text())
        assert (dest / package["main"]).is_file()

    def test_failed_install_does_not_mark_cache_valid(self, tmp_path, monkeypatch):
        engine = MagicMock()
        engine.engine_id = "mock"
        agent = ClaudeCodeAgent(engine, "test-model")

        home_dir = tmp_path / "home"
        monkeypatch.setenv("OPENJARVIS_HOME", str(home_dir))
        failure = subprocess.CalledProcessError(
            1,
            ["npm", "ci"],
            stderr="registry unavailable",
        )

        with (
            patch("shutil.which", side_effect=_mock_which),
            patch("subprocess.run", side_effect=failure),
            pytest.raises(RuntimeError, match="registry unavailable"),
        ):
            agent._ensure_runner()

        runner_root = home_dir / "claude_code_runner"
        assert not list(runner_root.rglob(_INSTALL_STATE_FILE))

    def test_node_architecture_uses_an_immutable_cache_generation(
        self, tmp_path, monkeypatch
    ):
        engine = MagicMock()
        engine.engine_id = "mock"
        agent = ClaudeCodeAgent(engine, "test-model")
        monkeypatch.setenv("OPENJARVIS_HOME", str(tmp_path / "home"))

        def install_for(arch):
            def install_sdk(*args, **kwargs):
                _create_mock_sdk_install(kwargs["cwd"], "darwin", arch)
                return _mock_proc()

            with (
                patch("shutil.which", side_effect=_mock_which),
                patch(
                    "openjarvis.agents.claude_code._node_runtime_platform",
                    return_value=("darwin", arch, ""),
                ),
                patch("subprocess.run", side_effect=install_sdk),
            ):
                return agent._ensure_runner()

        arm_runner = install_for("arm64")
        x64_runner = install_for("x64")

        assert arm_runner != x64_runner
        assert arm_runner.parent == x64_runner.parent
        assert "claude-agent-sdk-darwin-arm64" in {
            path.name
            for path in (arm_runner / "node_modules" / "@anthropic-ai").iterdir()
        }
        assert "claude-agent-sdk-darwin-x64" in {
            path.name
            for path in (x64_runner / "node_modules" / "@anthropic-ai").iterdir()
        }

    def test_uses_resolved_windows_executables(self, tmp_path, monkeypatch):
        engine = MagicMock()
        engine.engine_id = "mock"
        agent = ClaudeCodeAgent(engine, "test-model")
        monkeypatch.setenv("OPENJARVIS_HOME", str(tmp_path / "home"))
        node_path = r"C:\Program Files\nodejs\node.exe"
        npm_path = r"C:\Program Files\nodejs\npm.cmd"

        def which(executable):
            return node_path if executable == "node" else npm_path

        def install_sdk(*args, **kwargs):
            _create_mock_sdk_install(kwargs["cwd"])
            return _mock_proc()

        with (
            patch("shutil.which", side_effect=which),
            patch("subprocess.run", side_effect=install_sdk) as mock_run,
        ):
            agent._ensure_runner()

        assert mock_run.call_args.args[0][0] == npm_path
        assert agent._node_executable == node_path

    def test_concurrent_first_use_installs_once(self, tmp_path, monkeypatch):
        home_dir = tmp_path / "home"
        monkeypatch.setenv("OPENJARVIS_HOME", str(home_dir))
        agents = []
        for _ in range(2):
            engine = MagicMock()
            engine.engine_id = "mock"
            agents.append(ClaudeCodeAgent(engine, "test-model"))

        def install_sdk(*args, **kwargs):
            time.sleep(0.05)
            _create_mock_sdk_install(kwargs["cwd"])
            return _mock_proc()

        with (
            patch("shutil.which", side_effect=_mock_which),
            patch("subprocess.run", side_effect=install_sdk) as mock_run,
            ThreadPoolExecutor(max_workers=2) as executor,
        ):
            destinations = list(
                executor.map(lambda agent: agent._ensure_runner(), agents)
            )

        assert destinations[0] == destinations[1]
        mock_run.assert_called_once()


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
        assert call_kwargs.kwargs["encoding"] == "utf-8"
        stdin_json = json.loads(call_kwargs.kwargs["input"])
        assert stdin_json["prompt"] == "Do something"
        assert stdin_json["api_key"] == "sk-test"
        assert stdin_json["workspace"] == "/projects/myapp"
        assert stdin_json["session_id"] == "sess-123"
        assert stdin_json["allowed_tools"] == ["Read", "Write"]
        assert stdin_json["system_prompt"] == "Be helpful."

    def test_empty_allowed_tools_is_preserved(self):
        agent = self._make_agent(allowed_tools=[])
        proc = _mock_proc(
            stdout=_wrap_output({"content": "ok", "tool_results": [], "metadata": {}})
        )

        with (
            patch.object(agent, "_ensure_runner", return_value="/fake/runner"),
            patch("subprocess.run", return_value=proc) as mock_run,
        ):
            agent.run("Do not use tools")

        stdin_json = json.loads(mock_run.call_args.kwargs["input"])
        assert stdin_json["allowed_tools"] == []

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

    def test_nonzero_exit_preserves_structured_runner_error(self):
        agent = self._make_agent()
        output = _wrap_output(
            {
                "content": "Authentication failed for the supplied API key.",
                "tool_results": [],
                "metadata": {
                    "error": True,
                    "result_subtype": "error_during_execution",
                },
            }
        )
        proc = _mock_proc(returncode=1, stdout=output)

        with (
            patch.object(agent, "_ensure_runner", return_value="/fake/runner"),
            patch("subprocess.run", return_value=proc),
        ):
            result = agent.run("Failing task")

        assert "Authentication failed" in result.content
        assert result.metadata["error"] is True
        assert result.metadata["result_subtype"] == "error_during_execution"
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

    def test_end_sentinel_inside_content_does_not_truncate_payload(self):
        payload = {
            "content": f"literal marker: {_OUTPUT_END}",
            "tool_results": [],
            "metadata": {},
        }

        content, tools, meta = ClaudeCodeAgent._parse_output(_wrap_output(payload))

        assert content == f"literal marker: {_OUTPUT_END}"
        assert tools == []
        assert meta == {}

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
