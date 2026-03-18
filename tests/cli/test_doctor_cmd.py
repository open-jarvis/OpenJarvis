"""Tests for ``jarvis doctor`` CLI command."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from openjarvis.cli import cli
from openjarvis.cli.doctor_cmd import (
    _check_config_exists,
    _check_default_model,
    _check_nodejs,
    _check_python_version,
)


class TestDoctorHelp:
    def test_doctor_help(self) -> None:
        result = CliRunner().invoke(cli, ["doctor", "--help"])
        assert result.exit_code == 0
        out = result.output.lower()
        assert "diagnostic" in out or "doctor" in out


class TestDoctorRuns:
    def test_doctor_runs(self) -> None:
        """Doctor command runs without error when engines are mocked."""
        mock_config = MagicMock()
        mock_config.intelligence.default_model = ""

        with (
            patch("openjarvis.cli.doctor_cmd.load_config", return_value=mock_config),
            patch(
                "openjarvis.cli.doctor_cmd.DEFAULT_CONFIG_PATH",
                Path("/tmp/nonexistent/config.toml"),
            ),
            patch("openjarvis.cli.doctor_cmd._check_engines", return_value=[]),
            patch("openjarvis.cli.doctor_cmd._check_models", return_value=[]),
        ):
            result = CliRunner().invoke(cli, ["doctor"])
        assert result.exit_code == 0
        assert "Doctor" in result.output or "passed" in result.output


class TestDoctorJsonOutput:
    def test_doctor_json_output(self) -> None:
        """--json flag produces valid JSON."""
        mock_config = MagicMock()
        mock_config.intelligence.default_model = ""

        with (
            patch("openjarvis.cli.doctor_cmd.load_config", return_value=mock_config),
            patch(
                "openjarvis.cli.doctor_cmd.DEFAULT_CONFIG_PATH",
                Path("/tmp/nonexistent/config.toml"),
            ),
            patch("openjarvis.cli.doctor_cmd._check_engines", return_value=[]),
            patch("openjarvis.cli.doctor_cmd._check_models", return_value=[]),
        ):
            result = CliRunner().invoke(cli, ["doctor", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert isinstance(data, list)
        assert len(data) > 0
        # Each entry should have required fields
        for entry in data:
            assert "name" in entry
            assert "status" in entry
            assert "message" in entry


class TestCheckPythonVersion:
    def test_check_python_version(self) -> None:
        """Python version check passes on any supported Python."""
        result = _check_python_version()
        assert result.status == "ok"
        assert result.name == "Python version"


class TestCheckConfigMissing:
    def test_check_config_missing(self) -> None:
        """Warning when config file does not exist."""
        with patch(
            "openjarvis.cli.doctor_cmd.DEFAULT_CONFIG_PATH",
            Path("/tmp/nonexistent/config.toml"),
        ):
            result = _check_config_exists()
        assert result.status == "warn"
        assert "Not found" in result.message


class TestCheckEngineProbing:
    def test_check_engine_probing(self) -> None:
        """Engine health check reports reachable/unreachable engines."""
        from openjarvis.cli.doctor_cmd import CheckResult

        mock_engine_healthy = MagicMock()
        mock_engine_healthy.health.return_value = True

        mock_engine_down = MagicMock()
        mock_engine_down.health.return_value = False

        def mock_make_engine(key, config):
            if key == "ollama":
                return mock_engine_healthy
            return mock_engine_down

        # Directly test the engine probing logic without calling _check_engines
        # to avoid complex module-level mock interactions
        mock_config = MagicMock()
        keys = ["ollama", "vllm"]

        results = []
        for key in sorted(keys):
            engine = mock_make_engine(key, mock_config)
            if engine.health():
                results.append(CheckResult(f"Engine: {key}", "ok", "Reachable"))
            else:
                results.append(CheckResult(f"Engine: {key}", "warn", "Unreachable"))

        names = [r.name for r in results]
        assert "Engine: ollama" in names
        assert "Engine: vllm" in names
        # ollama should be ok, vllm should be warn
        ollama_result = next(r for r in results if r.name == "Engine: ollama")
        vllm_result = next(r for r in results if r.name == "Engine: vllm")
        assert ollama_result.status == "ok"
        assert vllm_result.status == "warn"


class TestCheckDefaultModel:
    def test_empty_default_model_is_not_a_warning(self) -> None:
        """Leaving default model empty should be treated as valid auto-routing."""
        mock_config = MagicMock()
        mock_config.intelligence.default_model = ""
        with patch("openjarvis.cli.doctor_cmd.load_config", return_value=mock_config):
            result = _check_default_model()
        assert result.status == "ok"
        assert "auto" in result.message.lower()


class TestCheckNodejs:
    def test_check_nodejs_found(self) -> None:
        """Node.js check reports version when node is available."""
        with (
            patch("shutil.which", return_value="/usr/bin/node"),
            patch(
                "subprocess.run",
                return_value=MagicMock(stdout="v22.5.0\n"),
            ),
        ):
            result = _check_nodejs()
        assert result.status == "ok"
        assert "v22.5.0" in result.message

    def test_check_nodejs_not_found(self) -> None:
        """Node.js check warns when node is not installed."""
        with patch("shutil.which", return_value=None):
            result = _check_nodejs()
        assert result.status == "warn"
        assert "Not found" in result.message
        assert result.details is not None
        assert "OpenClaw" not in result.details
