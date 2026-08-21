"""Tests for ``jarvis model convert`` command."""

from __future__ import annotations

# Import the real module via importlib to patch its attributes.
import importlib
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

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
        snapshot = tmp_path / "snapshot"
        snapshot.mkdir()

        # Track calls to mlx_lm.convert
        convert_calls = []

        class FakeMLXLM:
            @staticmethod
            def convert(hf_path: str, mlx_path: str, quantize: bool) -> None:
                convert_calls.append((hf_path, mlx_path, quantize))
                target = Path(mlx_path)
                target.mkdir(parents=True)
                (target / "config.json").write_text("{}", encoding="utf-8")

        # Monkeypatch sys.modules to inject fake mlx_lm
        monkeypatch.setitem(sys.modules, "mlx_lm", FakeMLXLM)
        monkeypatch.setattr(
            model_module, "_download_snapshot", lambda *args: str(snapshot)
        )

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
        assert convert_calls[0][0] == str(snapshot)
        assert convert_calls[0][2] is True
        # mlx_lm receives a fresh sibling staging path; only a complete result
        # is published to the requested output directory.
        assert Path(convert_calls[0][1]) != output_dir
        assert Path(convert_calls[0][1]).parent.parent == output_dir.parent
        assert (output_dir / "config.json").is_file()
        assert "jarvis host" in result.output
        assert "--backend mlx" in result.output

    def test_convert_mlx_missing_extra(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """convert with --engine mlx fails when mlx_lm is not installed."""
        # Create a fake output directory
        output_dir = tmp_path / "some--repo-mlx"
        output_dir.mkdir(parents=True)
        snapshot = tmp_path / "snapshot"
        snapshot.mkdir()

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
        snapshot = tmp_path / "snapshot"
        snapshot.mkdir()

        # Track calls to mlx_lm.convert
        convert_calls = []

        class FakeMLXLM:
            @staticmethod
            def convert(hf_path: str, mlx_path: str, quantize: bool) -> None:
                convert_calls.append((hf_path, mlx_path, quantize))
                target = Path(mlx_path)
                target.mkdir(parents=True)
                (target / "config.json").write_text("{}", encoding="utf-8")

        monkeypatch.setitem(sys.modules, "mlx_lm", FakeMLXLM)
        monkeypatch.setattr(
            model_module, "_download_snapshot", lambda *args: str(snapshot)
        )

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

    def test_snapshot_download_returns_concrete_cache_path(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        snapshot = tmp_path / "models--some--repo" / "snapshots" / "revision"
        snapshot.mkdir(parents=True)
        calls = []

        def fake_snapshot_download(*, repo_id: str):
            calls.append(repo_id)
            return snapshot

        monkeypatch.setitem(
            sys.modules,
            "huggingface_hub",
            SimpleNamespace(snapshot_download=fake_snapshot_download),
        )

        resolved = model_module._download_snapshot("some/repo", MagicMock())

        assert resolved == str(snapshot)
        assert calls == ["some/repo"]

    def test_convert_gguf_shells_and_quantizes(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """llamacpp + --quantize shells the converter and the quantizer."""
        # Create a fake output directory
        output_dir = tmp_path / "some--repo-q4_k_m"
        output_dir.mkdir(parents=True)
        snapshot = tmp_path / "snapshot"
        snapshot.mkdir()

        # Track subprocess calls
        subprocess_calls = []

        def fake_subprocess_run(args, check=False, **kwargs):
            subprocess_calls.append(args)
            if args[0] == "/fake/llama-quantize":
                Path(args[2]).write_bytes(b"quantized")
            else:
                Path(args[args.index("--outfile") + 1]).write_bytes(b"f16")
            return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

        monkeypatch.setattr(
            model_module, "_download_snapshot", lambda *args: str(snapshot)
        )

        # Monkeypatch locators to return fake paths
        monkeypatch.setattr(
            model_module,
            "_locate_convert_script",
            lambda console, config=None: "/fake/convert_hf_to_gguf.py",
        )
        monkeypatch.setattr(
            model_module,
            "_locate_quantize_script",
            lambda console, config=None: "/fake/llama-quantize",
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
        converter_out = Path(subprocess_calls[0][-1])
        assert subprocess_calls[0][:-1] == [
            sys.executable,
            "/fake/convert_hf_to_gguf.py",
            str(snapshot),
            "--outtype",
            "f16",
            "--outfile",
        ]
        assert converter_out.name == "some--repo.f16.gguf"
        assert subprocess_calls[1] == [
            "/fake/llama-quantize",
            str(converter_out),
            str(converter_out.with_name("some--repo.q4_k_m.gguf")),
            "q4_k_m",
        ]
        assert (output_dir / "some--repo.q4_k_m.gguf").read_bytes() == b"quantized"
        assert "jarvis host" in result.output
        assert "--backend llamacpp" in result.output

    def test_convert_gguf_missing_tool(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """convert with --engine llamacpp fails when convert script is missing."""
        # Create a fake output directory
        output_dir = tmp_path / "some--repo-gguf"
        output_dir.mkdir(parents=True)

        snapshot = tmp_path / "snapshot"
        snapshot.mkdir()
        monkeypatch.setattr(
            model_module, "_download_snapshot", lambda *args: str(snapshot)
        )

        # Monkeypatch locator to return None (tool not found)
        def fake_locate_convert_script(console, config=None):
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
                target = Path(mlx_path)
                target.mkdir(parents=True)
                (target / "config.json").write_text("{}", encoding="utf-8")

        monkeypatch.setitem(sys.modules, "mlx_lm", FakeMLXLM)
        snapshot = tmp_path / "snapshot"
        snapshot.mkdir()
        monkeypatch.setattr(
            model_module, "_download_snapshot", lambda *args: str(snapshot)
        )

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
        assert not (output_dir / "existing_file.txt").exists()
        assert (output_dir / "config.json").is_file()
        assert list(tmp_path.glob(".some--repo-mlx.convert-*")) == []

    def test_force_failure_preserves_existing_output(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A failed forced conversion cannot destroy the previous artifact."""
        output_dir = tmp_path / "some--repo-mlx"
        output_dir.mkdir(parents=True)
        sentinel = output_dir / "existing_file.txt"
        sentinel.write_text("keep", encoding="utf-8")

        class FailingMLXLM:
            @staticmethod
            def convert(hf_path: str, mlx_path: str, quantize: bool) -> None:
                target = Path(mlx_path)
                target.mkdir(parents=True)
                (target / "partial.bin").write_bytes(b"partial")
                raise RuntimeError("conversion interrupted")

        monkeypatch.setitem(sys.modules, "mlx_lm", FailingMLXLM)
        monkeypatch.setattr(
            model_module, "_download_snapshot", lambda *args: str(tmp_path / "snapshot")
        )

        class FakeConfig:
            class Engine:
                default = None

            engine = Engine()

        monkeypatch.setattr(model_module, "load_config", lambda: FakeConfig())

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

        assert result.exit_code == 1
        assert sentinel.read_text(encoding="utf-8") == "keep"
        assert not (output_dir / "partial.bin").exists()
        assert list(tmp_path.glob(".some--repo-mlx.convert-*")) == []

    def test_publish_failure_rolls_back_existing_output(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        output_dir = tmp_path / "model"
        output_dir.mkdir()
        sentinel = output_dir / "old.bin"
        sentinel.write_bytes(b"old")
        staged = tmp_path / "staged"
        staged.mkdir()
        (staged / "new.bin").write_bytes(b"new")
        real_replace = model_module.os.replace

        def fail_publish(source, destination):
            if Path(source) == staged and Path(destination) == output_dir:
                raise OSError("simulated publish failure")
            return real_replace(source, destination)

        monkeypatch.setattr(model_module.os, "replace", fail_publish)

        with pytest.raises(OSError, match="simulated publish failure"):
            model_module._publish_output(staged, output_dir)

        assert sentinel.read_bytes() == b"old"
        assert staged.joinpath("new.bin").read_bytes() == b"new"
        assert list(tmp_path.glob(".model.backup-*")) == []

    def test_force_replaces_symlink_without_touching_target(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        target = tmp_path / "target"
        target.mkdir()
        sentinel = target / "keep.txt"
        sentinel.write_text("keep", encoding="utf-8")
        output_dir = tmp_path / "model-link"
        output_dir.symlink_to(target, target_is_directory=True)

        class FakeMLXLM:
            @staticmethod
            def convert(hf_path: str, mlx_path: str, quantize: bool) -> None:
                converted = Path(mlx_path)
                converted.mkdir(parents=True)
                (converted / "config.json").write_text("{}", encoding="utf-8")

        monkeypatch.setitem(sys.modules, "mlx_lm", FakeMLXLM)
        monkeypatch.setattr(
            model_module, "_download_snapshot", lambda *args: str(tmp_path / "snapshot")
        )

        class FakeConfig:
            class Engine:
                default = None

            engine = Engine()

        monkeypatch.setattr(model_module, "load_config", lambda: FakeConfig())

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
        assert not output_dir.is_symlink()
        assert (output_dir / "config.json").is_file()
        assert sentinel.read_text(encoding="utf-8") == "keep"

    def test_convert_refuses_empty_directory_symlink_without_force(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        target = tmp_path / "empty-target"
        target.mkdir()
        output_dir = tmp_path / "model-link"
        output_dir.symlink_to(target, target_is_directory=True)

        class FakeConfig:
            class Engine:
                default = None

            engine = Engine()

        monkeypatch.setattr(model_module, "load_config", lambda: FakeConfig())

        result = CliRunner().invoke(
            model,
            ["convert", "some/repo", "--engine", "mlx", "--output", str(output_dir)],
        )

        assert result.exit_code == 1
        assert "symlink" in result.output
        assert "--force" in result.output
        assert output_dir.is_symlink()
        assert list(target.iterdir()) == []

    def test_convert_ollama_creates_model_from_gguf(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Ollama conversion creates a GGUF-backed model via a Modelfile."""
        output_dir = tmp_path / "some--repo-ollama"
        subprocess_calls: list[list[str]] = []

        def fake_convert_gguf(hf_repo, output, quantize, console, config=None):
            target = Path(output)
            target.mkdir(parents=True)
            gguf = target / "some--repo.f16.gguf"
            gguf.write_bytes(b"gguf")
            return str(gguf)

        def fake_subprocess_run(args, check=False, **kwargs):
            subprocess_calls.append(args)
            modelfile = Path(args[-1])
            assert modelfile.read_text(encoding="utf-8") == (
                "FROM ./some--repo.f16.gguf\n"
            )
            return subprocess.CompletedProcess(args, 0)

        monkeypatch.setattr(model_module, "_convert_gguf", fake_convert_gguf)
        monkeypatch.setattr(model_module.subprocess, "run", fake_subprocess_run)

        class FakeConfig:
            class Engine:
                default = None

            engine = Engine()

        monkeypatch.setattr(model_module, "load_config", lambda: FakeConfig())

        result = CliRunner().invoke(
            model,
            ["convert", "some/repo", "--engine", "ollama", "--output", str(output_dir)],
        )

        assert result.exit_code == 0
        assert subprocess_calls == [
            ["ollama", "create", "repo", "-f", subprocess_calls[0][-1]]
        ]
        assert (output_dir / "some--repo.f16.gguf").read_bytes() == b"gguf"
        assert (output_dir / "Modelfile").read_text(encoding="utf-8") == (
            "FROM ./some--repo.f16.gguf\n"
        )
        assert "jarvis chat --engine ollama --model repo" in result.output

    @pytest.mark.parametrize("engine", ["vllm", "sglang"])
    def test_direct_hf_engines_are_noop(
        self, engine: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        output_dir = tmp_path / "must-not-exist"

        class FakeConfig:
            class Engine:
                default = None

            engine = Engine()

        monkeypatch.setattr(model_module, "load_config", lambda: FakeConfig())

        result = CliRunner().invoke(
            model,
            [
                "convert",
                "some/repo",
                "--engine",
                engine,
                "--output",
                str(output_dir),
            ],
        )

        assert result.exit_code == 0
        assert not output_dir.exists()
        assert f"jarvis host some/repo --backend {engine}" in result.output

    def test_llamacpp_tools_found_from_configured_binary(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repo = tmp_path / "llama.cpp"
        converter = repo / "convert_hf_to_gguf.py"
        quantizer = repo / "build" / "bin" / "llama-quantize"
        binary = repo / "build" / "bin" / "llama-server"
        converter.parent.mkdir(parents=True)
        converter.write_text("", encoding="utf-8")
        quantizer.parent.mkdir(parents=True)
        quantizer.write_text("", encoding="utf-8")
        binary.write_text("", encoding="utf-8")
        config = SimpleNamespace(
            engine=SimpleNamespace(llamacpp=SimpleNamespace(binary_path=str(binary)))
        )
        monkeypatch.delenv("LLAMACPP_PATH", raising=False)
        monkeypatch.delenv("LLAMA_CPP_DIR", raising=False)
        monkeypatch.setattr(model_module.shutil, "which", lambda _: None)

        assert model_module._locate_convert_script(MagicMock(), config) == str(
            converter
        )
        assert model_module._locate_quantize_script(MagicMock(), config) == str(
            quantizer
        )

    @pytest.mark.parametrize(
        ("args", "message"),
        [
            (["--engine", "mlx", "--quantize", "q4_k_m"], "--quantize"),
            (["--engine", "llamacpp", "--mlx-4bit"], "--mlx-4bit"),
            (["--engine", "llamacpp", "--quantize", "../bad"], "Invalid"),
            (["--engine", "unknown"], "Unsupported"),
        ],
    )
    def test_invalid_engine_options_fail_before_writing(
        self,
        args: list[str],
        message: str,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        output_dir = tmp_path / "must-not-exist"

        class FakeConfig:
            class Engine:
                default = None

            engine = Engine()

        monkeypatch.setattr(model_module, "load_config", lambda: FakeConfig())
        result = CliRunner().invoke(
            model,
            ["convert", "some/repo", *args, "--output", str(output_dir)],
        )

        assert result.exit_code == 1
        assert message in result.output
        assert not output_dir.exists()
