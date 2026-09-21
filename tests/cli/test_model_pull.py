"""Tests for ``jarvis model pull`` multi-engine support."""

from __future__ import annotations

import io
from contextlib import closing
from unittest import mock

import httpx
from click.testing import CliRunner
from rich.console import Console

from openjarvis.cli.model import ollama_pull
from openjarvis.core.config import JarvisConfig


class TestOllamaPull:
    """Test the extracted ollama_pull helper."""

    def test_ollama_pull_stream_error(self) -> None:
        output = io.StringIO()
        response = httpx.Response(
            200,
            request=httpx.Request("POST", "http://localhost:11434/api/pull"),
            content=(
                b'{"status":"pulling manifest"}\n'
                b'{"error":"download failed [red]disk full[/red]"}\n'
            ),
        )
        with mock.patch("httpx.stream", return_value=closing(response)):
            result = ollama_pull(
                "http://localhost:11434", "qwen3.5:2b", Console(file=output)
            )

        assert result is False
        assert "download failed [red]disk full[/red]" in output.getvalue()
        assert "Successfully pulled" not in output.getvalue()
        assert response.is_closed

    def test_ollama_pull_success(self) -> None:
        import io

        console = Console(file=io.StringIO())
        mock_lines = [
            '{"status": "pulling manifest"}',
            '{"status": "downloading", "total": 100, "completed": 100}',
            '{"status": "success"}',
        ]
        mock_resp = mock.MagicMock()
        mock_resp.raise_for_status = mock.MagicMock()
        mock_resp.iter_lines.return_value = iter(mock_lines)
        mock_resp.__enter__ = mock.MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = mock.MagicMock(return_value=False)

        with mock.patch("httpx.stream", return_value=mock_resp):
            result = ollama_pull("http://localhost:11434", "qwen3.5:2b", console)
        assert result is True

    def test_ollama_pull_connect_error(self) -> None:
        import io

        import httpx

        console = Console(file=io.StringIO())
        with mock.patch("httpx.stream", side_effect=httpx.ConnectError("refused")):
            result = ollama_pull("http://localhost:11434", "qwen3.5:2b", console)
        assert result is False


class TestPullCliMultiEngine:
    """Test the pull CLI command dispatches to correct engine."""

    def test_pull_ollama_stream_error_exits_unsuccessfully(self) -> None:
        from openjarvis.cli import cli

        response = httpx.Response(
            200,
            request=httpx.Request("POST", "http://localhost:11434/api/pull"),
            content=b'{"status":"pulling manifest"}\n{"error":"disk full"}\n',
        )
        with (
            mock.patch("openjarvis.cli.model.load_config", return_value=JarvisConfig()),
            mock.patch("httpx.stream", return_value=closing(response)),
        ):
            result = CliRunner().invoke(
                cli, ["model", "pull", "qwen3.5:2b", "--engine", "ollama"]
            )

        assert result.exit_code == 1
        assert "disk full" in result.output
        assert "Successfully pulled" not in result.output

    def test_pull_llamacpp_uses_huggingface_cli(self) -> None:
        from openjarvis.cli import cli

        runner = CliRunner()
        with (
            mock.patch("openjarvis.cli.model.load_config") as mock_cfg,
            mock.patch("subprocess.run") as mock_run,
        ):
            mock_cfg.return_value.engine.default = "llamacpp"
            mock_cfg.return_value.engine.ollama_host = None
            mock_run.return_value = mock.MagicMock(returncode=0)

            result = runner.invoke(
                cli, ["model", "pull", "qwen3.5:9b", "--engine", "llamacpp"]
            )

        assert result.exit_code == 0
        mock_run.assert_called_once()
        call_args = mock_run.call_args[0][0]
        assert "huggingface-cli" in call_args
        assert "qwen3.5-9b-q4_k_m.gguf" in call_args

    def test_pull_mlx_uses_huggingface_cli(self) -> None:
        from openjarvis.cli import cli

        runner = CliRunner()
        with (
            mock.patch("openjarvis.cli.model.load_config") as mock_cfg,
            mock.patch("subprocess.run") as mock_run,
        ):
            mock_cfg.return_value.engine.default = "mlx"
            mock_cfg.return_value.engine.ollama_host = None
            mock_run.return_value = mock.MagicMock(returncode=0)

            result = runner.invoke(
                cli, ["model", "pull", "qwen3.5:9b", "--engine", "mlx"]
            )

        assert result.exit_code == 0
        mock_run.assert_called_once()
        call_args = mock_run.call_args[0][0]
        assert "huggingface-cli" in call_args
        assert "mlx-community/Qwen3.5-9B-MLX-4bit" in call_args

    def test_pull_llamacpp_huggingface_cli_not_found(self) -> None:
        from openjarvis.cli import cli

        runner = CliRunner()
        with (
            mock.patch("openjarvis.cli.model.load_config") as mock_cfg,
            mock.patch("subprocess.run", side_effect=FileNotFoundError),
        ):
            mock_cfg.return_value.engine.default = "llamacpp"
            mock_cfg.return_value.engine.ollama_host = None

            result = runner.invoke(
                cli, ["model", "pull", "qwen3.5:9b", "--engine", "llamacpp"]
            )

        assert result.exit_code != 0
        assert "huggingface_hub" in result.output or "pip install" in result.output
