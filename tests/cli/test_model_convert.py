"""Tests for ``jarvis model convert`` command."""

from __future__ import annotations

# Import the real module via importlib to patch its attributes.
import importlib
import subprocess
import sys
from pathlib import Path

import pytest
from click.testing import CliRunner

from openjarvis.cli.model import model

model_module = importlib.import_module("openjarvis.cli.model")


class TestModelConvert:
    """Tests for the convert command."""

    def test_convert_mlx_quantize(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """convert some/repo -q --engine mlx calls mlx_lm.convert with quantize=True."""
        # Create a fake output directory
        output_dir = tmp_path / "some--repo-mlx"
        output_dir.mkdir(parents=True)

        # Track calls to mlx_lm.convert
        convert_calls = []

        class FakeMLXLM:
            @staticmethod
            def convert(hf_path: str, mlx_path: str, quantize: bool) -> None:
                convert_calls.append((hf_path, mlx_path, quantize))

        # Monkeypatch sys.modules to inject fake mlx_lm
        monkeypatch.setitem(sys.modules, "mlx_lm", FakeMLXLM)

        # Monkeypatch load_config to return default engine
        class FakeConfig:
            class Engine:
                default = None

            engine = Engine()

        monkeypatch.setattr(model_module, "load_config", lambda: FakeConfig())

        # Run the command
        result = CliRunner().invoke(
            model,
            [
                "convert",
                "some/repo",
                "--engine",
                "mlx",
                "-q",
                "--output",
                str(output_dir),
            ],
        )

        assert result.exit_code == 0
        assert len(convert_calls) == 1
        assert convert_calls[0] == ("some/repo", str(output_dir), True)

    def test_convert_mlx_missing_extra(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """convert with --engine mlx fails when mlx_lm is not installed."""
        # Create a fake output directory
        output_dir = tmp_path / "some--repo-mlx"
        output_dir.mkdir(parents=True)

        # Make import mlx_lm raise ImportError
        real_import_func = __builtins__.get("__import__", __builtins__["__import__"])

        def fake_import(name, *args, **kwargs):
            if name == "mlx_lm" or name.startswith("mlx_lm."):
                raise ImportError("No module named 'mlx_lm'")
            return real_import_func(name, *args, **kwargs)

        monkeypatch.setitem(__builtins__, "__import__", fake_import)

        # Monkeypatch load_config
        class FakeConfig:
            class Engine:
                default = None

            engine = Engine()

        monkeypatch.setattr(model_module, "load_config", lambda: FakeConfig())

        # Run the command
        result = CliRunner().invoke(
            model,
            ["convert", "some/repo", "--engine", "mlx", "--output", str(output_dir)],
        )

        assert result.exit_code == 1
        assert "inference-mlx" in result.output

    def test_convert_engine_defaults_to_config(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """convert some/repo with no --engine uses config.engine.default == 'mlx'."""
        # Create a fake output directory
        output_dir = tmp_path / "some--repo-mlx"
        output_dir.mkdir(parents=True)

        # Track calls to mlx_lm.convert
        convert_calls = []

        class FakeMLXLM:
            @staticmethod
            def convert(hf_path: str, mlx_path: str, quantize: bool) -> None:
                convert_calls.append((hf_path, mlx_path, quantize))

        monkeypatch.setitem(sys.modules, "mlx_lm", FakeMLXLM)

        # Monkeypatch load_config to return mlx as default
        class FakeConfig:
            class Engine:
                default = "mlx"

            engine = Engine()

        monkeypatch.setattr(model_module, "load_config", lambda: FakeConfig())

        # Run the command without --engine flag
        result = CliRunner().invoke(
            model, ["convert", "some/repo", "--output", str(output_dir)]
        )

        assert result.exit_code == 0
        assert len(convert_calls) == 1

    def test_convert_gguf_shells_and_quantizes(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """llamacpp + --quantize shells the converter and the quantizer."""
        # Create a fake output directory
        output_dir = tmp_path / "some--repo-q4_k_m"
        output_dir.mkdir(parents=True)

        # Track subprocess calls
        subprocess_calls = []

        def fake_subprocess_run(args, check=False, **kwargs):
            subprocess_calls.append(args)
            if "llama-quantize" in args:
                # Simulate quantizer success
                return subprocess.CompletedProcess(args, 0, stdout="", stderr="")
            # Simulate converter success
            return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

        # Monkeypatch hf_download to return True
        monkeypatch.setattr(model_module, "hf_download", lambda *args, **kwargs: True)

        # Monkeypatch locators to return fake paths
        monkeypatch.setattr(
            model_module,
            "_locate_convert_script",
            lambda console: "/fake/convert_hf_to_gguf.py",
        )
        monkeypatch.setattr(
            model_module,
            "_locate_quantize_script",
            lambda console: "/fake/llama-quantize",
        )

        # Patch subprocess.run at the module level (where it's imported).
        monkeypatch.setattr("subprocess.run", fake_subprocess_run)

        # Monkeypatch load_config
        class FakeConfig:
            class Engine:
                default = None

            engine = Engine()

        monkeypatch.setattr(model_module, "load_config", lambda: FakeConfig())

        # Run the command
        result = CliRunner().invoke(
            model,
            [
                "convert",
                "some/repo",
                "--engine",
                "llamacpp",
                "--quantize",
                "q4_k_m",
                "--output",
                str(output_dir),
            ],
        )

        assert result.exit_code == 0

        # Check both subprocess calls were made
        assert any("convert_hf_to_gguf.py" in " ".join(c) for c in subprocess_calls)
        assert any("llama-quantize" in " ".join(c) for c in subprocess_calls)

    def test_convert_gguf_missing_tool(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """convert with --engine llamacpp fails when convert script is missing."""
        # Create a fake output directory
        output_dir = tmp_path / "some--repo-gguf"
        output_dir.mkdir(parents=True)

        # Monkeypatch hf_download to return True
        monkeypatch.setattr(model_module, "hf_download", lambda *args, **kwargs: True)

        # Monkeypatch locator to return None (tool not found)
        def fake_locate_convert_script(console):
            console.print(
                "[red]convert_hf_to_gguf.py not found.[/red]\n"
                "Install llama.cpp and set [cyan]$LLAMA_CPP_DIR[/cyan] "
                "to the repo root."
            )
            return None

        monkeypatch.setattr(
            model_module, "_locate_convert_script", fake_locate_convert_script
        )

        # Monkeypatch load_config
        class FakeConfig:
            class Engine:
                default = None

            engine = Engine()

        monkeypatch.setattr(model_module, "load_config", lambda: FakeConfig())

        # Run the command
        result = CliRunner().invoke(
            model,
            [
                "convert",
                "some/repo",
                "--engine",
                "llamacpp",
                "--output",
                str(output_dir),
            ],
        )

        assert result.exit_code == 1
        assert (
            "convert_hf_to_gguf.py" in result.output
            or "llama.cpp" in result.output.lower()
        )

    def test_convert_refuses_nonempty_output(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """convert refuses to overwrite non-empty output without --force."""
        # Create a fake output directory with existing content
        output_dir = tmp_path / "some--repo-mlx"
        output_dir.mkdir(parents=True)
        (output_dir / "existing_file.txt").write_text("keep")

        # Monkeypatch mlx_lm to track if it would be called (should not be)
        convert_calls = []

        class FakeMLXLM:
            @staticmethod
            def convert(hf_path: str, mlx_path: str, quantize: bool) -> None:
                convert_calls.append((hf_path, mlx_path, quantize))

        monkeypatch.setitem(sys.modules, "mlx_lm", FakeMLXLM)

        # Monkeypatch load_config
        class FakeConfig:
            class Engine:
                default = None

            engine = Engine()

        monkeypatch.setattr(model_module, "load_config", lambda: FakeConfig())

        # Run without --force
        result = CliRunner().invoke(
            model,
            ["convert", "some/repo", "--engine", "mlx", "--output", str(output_dir)],
        )

        assert result.exit_code == 1
        assert "--force" in result.output
        assert len(convert_calls) == 0  # mlx_lm.convert should NOT be called

        # Now run WITH --force
        result = CliRunner().invoke(
            model,
            [
                "convert",
                "some/repo",
                "--engine",
                "mlx",
                "--output",
                str(output_dir),
                "--force",
            ],
        )

        assert result.exit_code == 0
        assert len(convert_calls) == 1

    def test_convert_ollama_informational(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """convert some/repo --engine ollama prints informational message about pull."""
        # Create a fake output directory
        output_dir = tmp_path / "some--repo"
        output_dir.mkdir(parents=True)

        # Monkeypatch load_config
        class FakeConfig:
            class Engine:
                default = None

            engine = Engine()

        monkeypatch.setattr(model_module, "load_config", lambda: FakeConfig())

        # Run the command
        result = CliRunner().invoke(
            model,
            ["convert", "some/repo", "--engine", "ollama", "--output", str(output_dir)],
        )

        assert result.exit_code == 0
        assert "pull" in result.output.lower()
