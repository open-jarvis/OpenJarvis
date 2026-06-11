"""--base-url/--api-key forwarding through the eval CLI plumbing.

Covers the fix for the eval-CLI endpoint gap: the flags used to be silently
dropped for jarvis-direct/jarvis-agent and ignored by terminalbench-native
(which hardcoded api_base="http://localhost:8000/v1").
"""

from __future__ import annotations

import io
import os
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import click
import pytest
from rich.console import Console

from openjarvis.evals.cli import _build_backend, _run_terminalbench_native
from openjarvis.evals.core.types import RunConfig


def _quiet_console() -> Console:
    return Console(file=io.StringIO())


def _tb_config(**overrides) -> RunConfig:
    defaults = dict(
        benchmark="terminalbench-native",
        backend="jarvis-direct",
        model="my-model",
        max_samples=1,
        max_workers=1,
        temperature=0.2,
    )
    defaults.update(overrides)
    return RunConfig(**defaults)


class TestBuildBackendForwardsEndpoint:
    @patch("openjarvis.evals.backends.jarvis_direct.JarvisDirectBackend")
    def test_jarvis_direct_receives_base_url_and_api_key(self, mock_cls):
        _build_backend(
            "jarvis-direct",
            "vllm",
            "orchestrator",
            [],
            base_url="http://node7:8123/v1",
            api_key="sk-k",
        )
        kwargs = mock_cls.call_args.kwargs
        assert kwargs["base_url"] == "http://node7:8123/v1"
        assert kwargs["api_key"] == "sk-k"

    @patch("openjarvis.evals.backends.jarvis_agent.JarvisAgentBackend")
    def test_jarvis_agent_receives_base_url_and_api_key(self, mock_cls):
        _build_backend(
            "jarvis-agent",
            "vllm",
            "orchestrator",
            ["calculator"],
            base_url="http://node7:8123/v1",
            api_key="sk-k",
        )
        kwargs = mock_cls.call_args.kwargs
        assert kwargs["base_url"] == "http://node7:8123/v1"
        assert kwargs["api_key"] == "sk-k"

    @patch("openjarvis.evals.backends.jarvis_direct.JarvisDirectBackend")
    def test_suite_mode_scopes_endpoint_to_external_backends(self, mock_cls):
        """[backend.external] suite semantics stay hermes/openclaw-only:
        first_party_endpoint=False must not forward to first-party."""
        _build_backend(
            "jarvis-direct",
            "vllm",
            "orchestrator",
            [],
            base_url="http://node7:8123/v1",
            api_key="sk-k",
            first_party_endpoint=False,
        )
        kwargs = mock_cls.call_args.kwargs
        assert kwargs["base_url"] is None
        assert kwargs["api_key"] is None

    def test_hermes_still_requires_base_url_and_api_key(self):
        with pytest.raises(click.UsageError, match="hermes"):
            _build_backend("hermes", None, "orchestrator", [])

    def test_openclaw_still_requires_base_url_and_api_key(self):
        with pytest.raises(click.UsageError, match="openclaw"):
            _build_backend("openclaw", None, "orchestrator", [])


class TestTerminalBenchNativeApiBase:
    @patch("openjarvis.evals.backends.terminalbench_native.TerminalBenchNativeBackend")
    def test_base_url_passed_through_as_api_base(self, mock_cls):
        mock_backend = MagicMock()
        mock_backend.run_harness.return_value = SimpleNamespace(trial_results=[])
        mock_cls.return_value = mock_backend

        _run_terminalbench_native(
            _tb_config(),
            _quiet_console(),
            base_url="http://node7:8123/v1",
        )
        assert mock_cls.call_args.kwargs["api_base"] == "http://node7:8123/v1"

    @patch("openjarvis.evals.backends.terminalbench_native.TerminalBenchNativeBackend")
    def test_base_url_without_v1_gets_single_v1_suffix(self, mock_cls):
        mock_backend = MagicMock()
        mock_backend.run_harness.return_value = SimpleNamespace(trial_results=[])
        mock_cls.return_value = mock_backend

        _run_terminalbench_native(
            _tb_config(),
            _quiet_console(),
            base_url="http://node7:8123",
        )
        assert mock_cls.call_args.kwargs["api_base"] == "http://node7:8123/v1"

    @patch("openjarvis.evals.backends.terminalbench_native.TerminalBenchNativeBackend")
    def test_default_api_base_unchanged_without_base_url(self, mock_cls):
        mock_backend = MagicMock()
        mock_backend.run_harness.return_value = SimpleNamespace(trial_results=[])
        mock_cls.return_value = mock_backend

        _run_terminalbench_native(_tb_config(), _quiet_console())
        assert mock_cls.call_args.kwargs["api_base"] == "http://localhost:8000/v1"

    @patch("openjarvis.evals.backends.terminalbench_native.TerminalBenchNativeBackend")
    def test_api_key_exported_as_openai_api_key_during_run(self, mock_cls, monkeypatch):
        """terminus-2 reads OPENAI_API_KEY via LiteLLM; the var must be set
        during harness.run() and restored afterwards."""
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        seen: dict = {}

        def fake_run_harness(run_id):
            seen["openai_api_key"] = os.environ.get("OPENAI_API_KEY")
            return SimpleNamespace(trial_results=[])

        mock_backend = MagicMock()
        mock_backend.run_harness.side_effect = fake_run_harness
        mock_cls.return_value = mock_backend

        _run_terminalbench_native(
            _tb_config(),
            _quiet_console(),
            base_url="http://node7:8123/v1",
            api_key="sk-tb",
        )
        assert seen["openai_api_key"] == "sk-tb"
        assert "OPENAI_API_KEY" not in os.environ  # restored

    @patch("openjarvis.evals.backends.terminalbench_native.TerminalBenchNativeBackend")
    def test_preexisting_openai_api_key_restored(self, mock_cls, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-original")
        mock_backend = MagicMock()
        mock_backend.run_harness.return_value = SimpleNamespace(trial_results=[])
        mock_cls.return_value = mock_backend

        _run_terminalbench_native(
            _tb_config(),
            _quiet_console(),
            base_url="http://node7:8123/v1",
            api_key="sk-tb",
        )
        assert os.environ["OPENAI_API_KEY"] == "sk-original"


class TestRunSingleSuiteModeGating:
    @patch("openjarvis.evals.cli._run_terminalbench_native")
    def test_suite_mode_drops_endpoint_for_terminalbench(self, mock_tb):
        from openjarvis.evals.cli import _run_single

        mock_tb.return_value = SimpleNamespace(accuracy=0.0)
        config = _tb_config(base_url="http://node7:8123/v1", api_key="sk-k")
        _run_single(config, console=_quiet_console(), suite_mode=True)
        assert mock_tb.call_args.kwargs["base_url"] is None
        assert mock_tb.call_args.kwargs["api_key"] is None

    @patch("openjarvis.evals.cli._run_terminalbench_native")
    def test_cli_mode_forwards_endpoint_for_terminalbench(self, mock_tb):
        from openjarvis.evals.cli import _run_single

        mock_tb.return_value = SimpleNamespace(accuracy=0.0)
        config = _tb_config(base_url="http://node7:8123/v1", api_key="sk-k")
        _run_single(config, console=_quiet_console())
        assert mock_tb.call_args.kwargs["base_url"] == "http://node7:8123/v1"
        assert mock_tb.call_args.kwargs["api_key"] == "sk-k"
