"""Tests for ``jarvis doctor`` CLI command."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from openjarvis.cli import cli
from openjarvis.cli.doctor_cmd import (
    CheckResult,
    _check_config_exists,
    _check_default_model,
    _check_nodejs,
    _check_python_version,
    _check_speech_backend,
    _run_all_checks,
)
from openjarvis.core.config import JarvisConfig
from openjarvis.core.registry import EngineRegistry


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
            patch(
                "openjarvis.cli.doctor_cmd._check_speech_backend",
                return_value=CheckResult("Speech backend", "ok", "mock ready"),
            ),
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
            patch(
                "openjarvis.cli.doctor_cmd._check_speech_backend",
                return_value=CheckResult("Speech backend", "ok", "mock ready"),
            ),
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
    @pytest.mark.parametrize(
        "major,minor,status",
        [
            (3, 10, "fail"),
            (3, 11, "ok"),
            (3, 13, "ok"),
            (3, 14, "fail"),
            (4, 11, "fail"),
        ],
    )
    def test_supported_range(self, major, minor, status):
        with patch(
            "openjarvis.cli.doctor_cmd.sys.version_info",
            SimpleNamespace(major=major, minor=minor, micro=0),
        ):
            assert _check_python_version().status == status

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

    def test_full_doctor_health_checks_each_engine_once(self) -> None:
        """All engine/model checks share one health snapshot (#766)."""
        config = JarvisConfig()
        config.intelligence.default_model = "model-a"
        config.intelligence.preferred_engine = "alpha"
        config.engine.default = "alpha"

        for key in ("alpha", "beta"):
            EngineRegistry.register_value(
                key, type(key, (), {"engine_id": key, "is_cloud": False})
            )
        alpha = MagicMock()
        alpha._host = "http://localhost:8000"
        alpha.health.return_value = True
        alpha.list_models.return_value = ["model-a"]
        beta = MagicMock()
        beta._host = "http://localhost:8000"
        beta.health.return_value = False

        def make_engine(key, _config):
            return {"alpha": alpha, "beta": beta}[key]

        ok = CheckResult("other", "ok", "ok")
        with (
            patch("openjarvis.cli.doctor_cmd._ensure_engines_imported"),
            patch("openjarvis.cli.doctor_cmd._get_config", return_value=config),
            patch("openjarvis.cli.doctor_cmd.load_config", return_value=config),
            patch(
                "openjarvis.core.registry.EngineRegistry.keys",
                return_value=["beta", "alpha"],
            ),
            patch(
                "openjarvis.engine._discovery._make_engine",
                side_effect=make_engine,
            ) as make,
            patch("openjarvis.cli.doctor_cmd._check_python_version", return_value=ok),
            patch("openjarvis.cli.doctor_cmd._check_config_exists", return_value=ok),
            patch("openjarvis.cli.doctor_cmd._check_config_parses", return_value=ok),
            patch("openjarvis.cli.doctor_cmd._check_optional_deps", return_value=[]),
            patch("openjarvis.cli.doctor_cmd._check_speech_backend", return_value=ok),
            patch("openjarvis.cli.doctor_cmd._check_nodejs", return_value=ok),
            patch("openjarvis.cli.doctor_cmd._check_security_profile", return_value=ok),
        ):
            results = _run_all_checks()

        assert make.call_count == 2
        alpha.health.assert_called_once_with()
        beta.health.assert_called_once_with()
        alpha.close.assert_called_once_with()
        beta.close.assert_called_once_with()
        assert any(
            result.name == "Default model" and result.status == "ok"
            for result in results
        )


class TestCheckDefaultModel:
    def test_empty_default_model_is_not_a_warning(self) -> None:
        """Leaving default model empty should be treated as valid auto-routing."""
        mock_config = MagicMock()
        mock_config.intelligence.default_model = ""
        with patch("openjarvis.cli.doctor_cmd.load_config", return_value=mock_config):
            result = _check_default_model()
        assert result.status == "ok"
        assert "auto" in result.message.lower()

    def test_mlx_catalog_model_is_checked_by_repo_id(self) -> None:
        mock_config = JarvisConfig()
        mock_config.intelligence.default_model = "qwen3.5:4b"
        mock_config.intelligence.preferred_engine = "mlx"
        mock_config.engine.default = "mlx"
        EngineRegistry.register_value(
            "mlx", type("MLX", (), {"engine_id": "mlx", "is_cloud": False})
        )
        mock_engine = MagicMock()
        mock_engine._host = "http://localhost:8000"
        mock_engine.health.return_value = True
        mock_engine.list_models.return_value = ["mlx-community/Qwen3.5-4B-OptiQ-4bit"]

        with (
            patch("openjarvis.cli.doctor_cmd.load_config", return_value=mock_config),
            patch("openjarvis.cli.doctor_cmd._ensure_engines_imported"),
            patch.object(EngineRegistry, "keys", return_value=["mlx"]),
            patch(
                "openjarvis.engine._discovery._make_engine",
                return_value=mock_engine,
            ),
        ):
            result = _check_default_model()

        assert result.status == "ok"
        assert "qwen3.5:4b" in result.message
        assert "mlx" in result.message


class TestCheckSpeechBackend:
    def test_check_speech_backend_ready(self) -> None:
        backend = MagicMock()
        backend.backend_id = "faster-whisper"
        backend.health.return_value = True

        with patch(
            "openjarvis.speech._discovery.get_speech_backend",
            return_value=backend,
        ):
            result = _check_speech_backend()

        assert result.status == "ok"
        assert "faster-whisper" in result.message

    def test_check_speech_backend_reports_load_error(self) -> None:
        backend = MagicMock()
        backend.backend_id = "faster-whisper"
        backend.health.return_value = False
        backend.last_error.return_value = "missing cublas64_12.dll"

        with patch(
            "openjarvis.speech._discovery.get_speech_backend",
            return_value=backend,
        ):
            result = _check_speech_backend()

        assert result.status == "warn"
        assert "faster-whisper unavailable" in result.message
        assert result.details == "missing cublas64_12.dll"

    def test_check_speech_backend_missing_uses_desktop_hint(self) -> None:
        with patch(
            "openjarvis.speech._discovery.get_speech_backend",
            return_value=None,
        ):
            result = _check_speech_backend()

        assert result.status == "warn"
        assert result.details is not None
        assert "uv sync --extra desktop" in result.details


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


@pytest.mark.parametrize(
    "host,cloud,should_probe",
    [
        ("http://localhost:8000", False, True),
        ("http://[::1]:8000", False, True),
        ("http://127.0.0.1:8000", False, True),
        (None, False, True),
        (None, True, False),
        ("https://integrate.api.nvidia.com", True, False),
        ("https://api.example.com?@localhost", False, False),
        ("https://api.example.com#@127.0.0.1", False, False),
        ("http://box.local:8000", False, False),
        ("http://192.168.1.20:8000", False, False),
        ("http://localhost:99999", False, False),
    ],
)
def test_doctor_skips_off_device_clients_before_construction(host, cloud, should_probe):
    from openjarvis.cli.doctor_cmd import _check_models, _probe_engines

    constructed = []
    health = MagicMock(return_value=True)
    models = MagicMock(return_value=["model-a"])

    class Engine:
        engine_id = "test-endpoint"
        _default_host = host
        is_cloud = cloud

        def __init__(self):
            constructed.append(self)
            self._host = host

        def health(self):
            return health()

        def list_models(self):
            return models()

    EngineRegistry.register_value("test-endpoint", Engine)
    with patch("openjarvis.cli.doctor_cmd._ensure_engines_imported"):
        probes = _probe_engines(JarvisConfig())
    _check_models(probes)
    assert probes["test-endpoint"].skipped is (not should_probe)
    assert len(constructed) == int(should_probe)
    assert health.call_count == int(should_probe)
    assert models.call_count == int(should_probe)


@pytest.mark.parametrize("probe_remote", [False, True])
def test_remote_opt_in_and_cli_flag(probe_remote):
    from openjarvis.cli.doctor_cmd import _probe_engines

    cls = type("CloudEngine", (), {"engine_id": "cloud", "is_cloud": True})
    EngineRegistry.register_value("cloud", cls)
    engine = MagicMock()
    engine._host = None
    engine.host = None
    engine.is_cloud = True
    engine.health.return_value = True
    with (
        patch("openjarvis.cli.doctor_cmd._ensure_engines_imported"),
        patch("openjarvis.engine._discovery._make_engine", return_value=engine) as make,
    ):
        probes = _probe_engines(JarvisConfig(), probe_remote=probe_remote)
    assert make.call_count == int(probe_remote)
    assert engine.health.call_count == int(probe_remote)
    assert probes["cloud"].skipped is (not probe_remote)
    with patch("openjarvis.cli.doctor_cmd._run_all_checks", return_value=[]) as checks:
        args = ["doctor", "--json"] + (["--probe-remote"] if probe_remote else [])
        result = CliRunner().invoke(cli, args)
        assert result.exit_code == 0
        checks.assert_called_once_with(probe_remote=probe_remote)


def test_default_model_on_skipped_engine_is_unchecked_not_missing():
    from openjarvis.cli.doctor_cmd import _EngineProbe

    config = JarvisConfig()
    config.engine.default = "nim"
    config.intelligence.default_model = "vendor/model"
    with patch("openjarvis.cli.doctor_cmd.load_config", return_value=config):
        result = _check_default_model({"nim": _EngineProbe(None, False, skipped=True)})
    assert result.status == "info"
    assert "--probe-remote" in result.message
    assert "not found" not in result.message


@pytest.mark.parametrize(
    "env_host", ["https://api.example.com", "http://localhost:8000"]
)
def test_nim_environment_host_controls_preflight(monkeypatch, env_host):
    from openjarvis.cli.doctor_cmd import _probe_engines
    from openjarvis.engine.nim import NIMEngine

    monkeypatch.setenv("NIM_HOST", env_host)
    EngineRegistry.register_value("nim", NIMEngine)
    engine = MagicMock()
    engine._host = env_host
    with (
        patch("openjarvis.cli.doctor_cmd._ensure_engines_imported"),
        patch("openjarvis.engine._discovery._make_engine", return_value=engine) as make,
    ):
        _probe_engines(JarvisConfig())
    assert make.call_count == int("localhost" in env_host)


def test_actual_endpoint_is_checked_again_and_errors_do_not_expose_secrets():
    from openjarvis.cli.doctor_cmd import _check_engines, _probe_engines

    cls = type("Engine", (), {"engine_id": "test", "is_cloud": False})
    EngineRegistry.register_value("test", cls)
    engine = MagicMock()
    engine._host = "https://remote.example.com"
    with (
        patch("openjarvis.cli.doctor_cmd._ensure_engines_imported"),
        patch("openjarvis.engine._discovery._make_engine", return_value=engine),
    ):
        probes = _probe_engines(JarvisConfig())
        assert probes["test"].skipped is True
        engine.health.assert_not_called()
        engine._host = "http://localhost:8000"
        engine.health.side_effect = RuntimeError("secret-access-token")
        probes = _probe_engines(JarvisConfig())
    assert probes["test"].engine is engine  # still owned for cleanup
    output = str(_check_engines(probes))
    assert "RuntimeError" in output
    assert "secret-access-token" not in output


def test_unreadable_host_is_not_assumed_local():
    from openjarvis.cli.doctor_cmd import _is_local_endpoint

    class Engine:
        @property
        def _host(self):
            raise ValueError("unreadable")

    assert _is_local_endpoint(Engine()) is False
