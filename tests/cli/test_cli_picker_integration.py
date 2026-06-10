"""Integration tests for CLI model picker and runtime panel paths."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from openjarvis.cli._model_switch import (
    interactive_pick_model,
    resolve_chat_cli_model,
    variant_preset_model,
)
from openjarvis.cli._runtime_panel import (
    ChatRuntimeOptions,
    interactive_pick_runtime_options,
    runtime_cli_options,
    tty_wants_runtime_panel,
)
from openjarvis.cli.chat_cmd import chat
from openjarvis.core.config import JarvisConfig


def _chat_patches(engine: MagicMock, config: JarvisConfig | None = None):
    cfg = config or JarvisConfig()
    cfg.intelligence.default_model = "default-m"
    return (
        patch("openjarvis.cli.chat_cmd.load_config", return_value=cfg),
        patch("openjarvis.engine.get_engine", return_value=("ollama", engine)),
        patch("openjarvis.intelligence.register_builtin_models"),
    )


class TestModelSwitchBranches:
    def test_variant_preset_no_intelligence(self) -> None:
        assert variant_preset_model(object(), "chat") == ""

    def test_interactive_pick_by_index(self) -> None:
        engine = MagicMock()
        engine.list_models.return_value = ["a", "b"]
        with patch("builtins.input", return_value="2"):
            assert interactive_pick_model(MagicMock(), engine) == "b"

    def test_interactive_pick_enter_default(self) -> None:
        engine = MagicMock()
        engine.list_models.return_value = ["only"]
        with patch("builtins.input", return_value=""):
            assert interactive_pick_model(MagicMock(), engine) is None

    def test_interactive_pick_list_models_raises(self) -> None:
        engine = MagicMock()
        engine.list_models.side_effect = RuntimeError("down")
        console = MagicMock()
        assert interactive_pick_model(console, engine) is None
        console.print.assert_called()

    def test_interactive_pick_empty_catalog(self) -> None:
        engine = MagicMock()
        engine.list_models.return_value = []
        console = MagicMock()
        assert interactive_pick_model(console, engine) is None

    def test_interactive_pick_keyboard_interrupt(self) -> None:
        engine = MagicMock()
        engine.list_models.return_value = ["m"]
        with patch("builtins.input", side_effect=KeyboardInterrupt):
            assert interactive_pick_model(MagicMock(), engine) is None

    def test_resolve_falls_back_to_discovered_model(self) -> None:
        cfg = JarvisConfig()
        cfg.intelligence.default_model = ""
        eng = MagicMock()
        with (
            patch(
                "openjarvis.engine.discover_engines",
                return_value=[("ollama", eng)],
            ),
            patch(
                "openjarvis.engine.discover_models",
                return_value={"ollama": ["discovered"]},
            ),
        ):
            m = resolve_chat_cli_model(
                console=MagicMock(),
                config=cfg,
                engine=eng,
                engine_name="ollama",
                cli_model=None,
                chat_variant="chat",
            )
        assert m == "discovered"


class TestRuntimePanelBranches:
    def test_summary_gpu_all_and_layers(self) -> None:
        assert "all layers" in ChatRuntimeOptions(num_gpu=-1).summary(
            engine_name="ollama"
        )
        assert "gpu=4 layers" in ChatRuntimeOptions(num_gpu=4).summary(
            engine_name="ollama"
        )
        assert "gpu=default" in ChatRuntimeOptions().summary(engine_name="ollama")

    def test_tty_skip_flag(self) -> None:
        assert tty_wants_runtime_panel(True) is False

    def test_interactive_runtime_ollama_full_flow(self) -> None:
        console = MagicMock()
        with patch(
            "builtins.input",
            side_effect=["65536", "0"],
        ):
            opts = interactive_pick_runtime_options(
                console, engine_name="ollama"
            )
        assert opts.num_ctx == 65536
        assert opts.num_gpu == 0

    def test_interactive_runtime_non_ollama_ctx_only(self) -> None:
        console = MagicMock()
        with patch("builtins.input", side_effect=["8192", "99"]):
            opts = interactive_pick_runtime_options(
                console, engine_name="vllm"
            )
        assert opts.num_ctx == 8192
        assert opts.num_gpu is None

    def test_interactive_runtime_ctx_interrupt(self) -> None:
        with patch("builtins.input", side_effect=KeyboardInterrupt):
            opts = interactive_pick_runtime_options(
                MagicMock(), engine_name="ollama"
            )
        assert opts == ChatRuntimeOptions()

    def test_interactive_runtime_gpu_interrupt_keeps_ctx(self) -> None:
        with patch("builtins.input", side_effect=["4096", KeyboardInterrupt]):
            opts = interactive_pick_runtime_options(
                MagicMock(), engine_name="ollama"
            )
        assert opts.num_ctx == 4096
        assert opts.num_gpu is None

    def test_cli_flags_skip_prompts(self) -> None:
        opts = interactive_pick_runtime_options(
            MagicMock(),
            engine_name="ollama",
            cli_num_ctx=32_000,
            cli_num_gpu=-1,
        )
        assert opts.to_engine_kwargs() == {"num_ctx": 32000, "num_gpu": 999}

    def test_runtime_cli_options_attached(self) -> None:
        import click

        @runtime_cli_options
        @click.command()
        def _cmd() -> None:
            pass

        param_names = [p.name for p in _cmd.params]
        assert "num_ctx" in param_names
        assert "num_gpu" in param_names
        assert "skip_runtime_panel" in param_names


class TestChatPickerIntegration:
    def test_native_react_gets_engine_options_via_setattr(self) -> None:
        """NativeReActAgent rejects engine_options kwarg; chat uses setattr."""
        import openjarvis.agents  # noqa: F401
        from openjarvis.agents.native_react import NativeReActAgent
        from openjarvis.core.registry import AgentRegistry

        if not AgentRegistry.contains("native_react"):
            AgentRegistry.register_value("native_react", NativeReActAgent)

        engine = MagicMock()
        engine.generate.return_value = {"content": "ok"}
        cfg = JarvisConfig()
        cfg.intelligence.default_model = "gemma4:e4b"
        cfg.agent.default_agent = "native_react"
        p = _chat_patches(engine, cfg)
        with (
            p[0],
            p[1],
            p[2],
            patch(
                "openjarvis.cli._model_switch.tty_wants_model_picker",
                return_value=False,
            ),
            patch(
                "openjarvis.cli._runtime_panel.tty_wants_runtime_panel",
                return_value=False,
            ),
        ):
            result = CliRunner().invoke(
                chat,
                ["--num-ctx", "8192", "--num-gpu", "0"],
                input="/quit\n",
            )
        assert result.exit_code == 0
        assert "failed" not in result.output.lower()

    def test_picker_selects_model_and_shows_runtime_banner(self) -> None:
        engine = MagicMock()
        engine.list_models.return_value = ["picked-model"]
        engine.generate.return_value = {"content": "hi"}
        p = _chat_patches(engine)
        with (
            p[0],
            p[1],
            p[2],
            patch(
                "openjarvis.cli._model_switch.tty_wants_model_picker",
                return_value=True,
            ),
            patch(
                "openjarvis.cli._runtime_panel.tty_wants_runtime_panel",
                return_value=False,
            ),
            patch(
                "openjarvis.cli._model_switch.interactive_pick_model",
                return_value="picked-model",
            ),
        ):
            result = CliRunner().invoke(
                chat,
                ["--agent", "none"],
                input="/model\n/runtime\n/quit\n",
            )
        assert result.exit_code == 0
        assert "picked-model" in result.output
        assert "Runtime:" in result.output

    def test_num_ctx_num_gpu_cli_bypasses_panel(self) -> None:
        engine = MagicMock()
        engine.generate.return_value = {"content": "ok"}
        p = _chat_patches(engine)
        with (
            p[0],
            p[1],
            p[2],
            patch(
                "openjarvis.cli._model_switch.tty_wants_model_picker",
                return_value=False,
            ),
            patch(
                "openjarvis.cli._runtime_panel.tty_wants_runtime_panel",
                return_value=True,
            ),
        ):
            result = CliRunner().invoke(
                chat,
                [
                    "--agent",
                    "none",
                    "-m",
                    "m1",
                    "--num-ctx",
                    "12000",
                    "--num-gpu",
                    "8",
                ],
                input="hello\n/runtime\n/quit\n",
            )
        assert result.exit_code == 0
        assert "ctx=12,000" in result.output
        assert "gpu=8 layers" in result.output
        engine.generate.assert_called_once()
        call_kw = engine.generate.call_args[1]
        assert call_kw.get("num_ctx") == 12000
        assert call_kw.get("num_gpu") == 8

    def test_no_model_available_exits(self) -> None:
        engine = MagicMock()
        cfg = JarvisConfig()
        cfg.intelligence.default_model = ""
        p = _chat_patches(engine, cfg)
        with (
            p[0],
            p[1],
            p[2],
            patch(
                "openjarvis.cli._model_switch.tty_wants_model_picker",
                return_value=False,
            ),
            patch(
                "openjarvis.cli._runtime_panel.tty_wants_runtime_panel",
                return_value=False,
            ),
            patch(
                "openjarvis.cli._model_switch.resolve_chat_cli_model",
                return_value="",
            ),
        ):
            result = CliRunner().invoke(chat, [])
        assert result.exit_code == 1
        assert "No model available" in result.output

    def test_smart_preset_used_when_no_flag(self) -> None:
        cfg = JarvisConfig()
        cfg.intelligence.model_chat = "preset-chat"
        eng = MagicMock()
        eng.generate.return_value = {"content": "x"}
        p = _chat_patches(eng, cfg)
        with (
            p[0],
            p[1],
            p[2],
            patch(
                "openjarvis.cli._model_switch.tty_wants_model_picker",
                return_value=False,
            ),
            patch(
                "openjarvis.cli._runtime_panel.tty_wants_runtime_panel",
                return_value=False,
            ),
        ):
            result = CliRunner().invoke(
                chat,
                ["-m", "smart", "--agent", "none"],
                input="/quit\n",
            )
        assert result.exit_code == 0
        assert "preset-chat" in result.output

