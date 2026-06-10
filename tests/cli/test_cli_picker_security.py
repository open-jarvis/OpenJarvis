"""Security tests for CLI model picker and runtime panel layers."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from openjarvis.cli._model_switch import (
    MAX_MODEL_ID_LEN,
    interactive_pick_model,
    resolve_chat_cli_model,
    sanitize_model_id,
    tty_wants_model_picker,
)
from openjarvis.cli._runtime_panel import (
    MAX_NUM_CTX,
    ChatRuntimeOptions,
    _parse_int,
    tty_wants_runtime_panel,
)
from openjarvis.core.config import JarvisConfig


class TestSanitizeModelId:
    def test_strips_control_characters(self) -> None:
        raw = "gemma\x00\x1f4:e4b\n"
        assert "\x00" not in sanitize_model_id(raw)
        assert "\n" not in sanitize_model_id(raw)

    def test_truncates_oversized_ids(self) -> None:
        raw = "m" * (MAX_MODEL_ID_LEN + 50)
        assert len(sanitize_model_id(raw)) == MAX_MODEL_ID_LEN

    def test_rejects_empty_after_sanitize(self) -> None:
        assert sanitize_model_id("  \t\x00  ") == ""


class TestRuntimePanelSecurity:
    def test_num_ctx_capped_at_max(self) -> None:
        opts = ChatRuntimeOptions(num_ctx=MAX_NUM_CTX + 50_000)
        assert opts.to_engine_kwargs()["num_ctx"] == MAX_NUM_CTX

    def test_parse_int_rejects_non_numeric(self) -> None:
        assert _parse_int("12abc", default=None) is None
        assert _parse_int("0x1000", default=None) is None
        assert _parse_int("1e6", default=None) is None

    def test_engine_kwargs_only_expected_keys(self) -> None:
        opts = ChatRuntimeOptions(num_ctx=4096, num_gpu=10)
        assert set(opts.to_engine_kwargs().keys()) <= {"num_ctx", "num_gpu"}

    def test_negative_num_ctx_not_forwarded(self) -> None:
        opts = ChatRuntimeOptions(num_ctx=-1)
        assert "num_ctx" not in opts.to_engine_kwargs()

    def test_num_gpu_all_layers_maps_to_bounded_value(self) -> None:
        opts = ChatRuntimeOptions(num_gpu=-1)
        assert opts.to_engine_kwargs()["num_gpu"] == 999

    def test_extreme_num_gpu_capped(self) -> None:
        from openjarvis.cli._runtime_panel import MAX_NUM_GPU_LAYERS

        opts = ChatRuntimeOptions(num_gpu=10**9)
        assert opts.to_engine_kwargs()["num_gpu"] == MAX_NUM_GPU_LAYERS


class TestModelPickerSecurity:
    def test_arbitrary_freeform_choice_not_accepted(self) -> None:
        """Unknown ids must not be passed through (only listed models)."""
        engine = MagicMock()
        engine.list_models.return_value = ["safe-model:latest"]
        console = MagicMock()
        with patch("builtins.input", return_value="../../../etc/passwd"):
            picked = interactive_pick_model(console, engine)
        assert picked is None

    def test_exact_listed_model_accepted(self) -> None:
        engine = MagicMock()
        engine.list_models.return_value = ["safe-model:latest"]
        console = MagicMock()
        with patch("builtins.input", return_value="safe-model:latest"):
            picked = interactive_pick_model(console, engine)
        assert picked == "safe-model:latest"

    def test_resolve_sanitizes_explicit_cli_model(self) -> None:
        cfg = JarvisConfig()
        eng = MagicMock()
        eng.list_models.return_value = []
        model = resolve_chat_cli_model(
            console=MagicMock(),
            config=cfg,
            engine=eng,
            engine_name="ollama",
            cli_model="ok\x00model",
            chat_variant="chat",
        )
        assert "\x00" not in model

    def test_substring_match_cannot_select_unlisted_model(self) -> None:
        engine = MagicMock()
        engine.list_models.return_value = ["prod-model:v1", "prod-model:v2"]
        console = MagicMock()
        with patch("builtins.input", return_value="prod"):
            picked = interactive_pick_model(console, engine)
        assert picked is None


class TestTtyGates:
    def test_skip_env_disables_model_picker(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("JARVIS_SKIP_MODEL_PICK", "1")
        with patch("sys.stdin.isatty", return_value=True):
            assert tty_wants_model_picker(False) is False

    def test_skip_env_disables_runtime_panel(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("JARVIS_SKIP_RUNTIME_PANEL", "1")
        with patch("sys.stdin.isatty", return_value=True):
            assert tty_wants_runtime_panel(False) is False


class TestAgentEngineOptionsIsolation:
    def test_engine_options_merge_does_not_leak_extra_keys(self) -> None:
        from openjarvis.agents._stubs import _ALLOWED_ENGINE_OPTION_KEYS
        from openjarvis.agents.simple import SimpleAgent
        from openjarvis.core.registry import AgentRegistry
        from openjarvis.core.types import Message, Role

        engine = MagicMock()
        engine.generate.return_value = {"content": "x"}
        if not AgentRegistry.contains("simple"):
            AgentRegistry.register_value("simple", SimpleAgent)

        agent = SimpleAgent(
            engine,
            "m",
            engine_options={"num_ctx": 8192, "evil": "payload"},
        )
        assert _ALLOWED_ENGINE_OPTION_KEYS == frozenset({"num_ctx", "num_gpu"})
        agent._generate([Message(role=Role.USER, content="hi")])
        call_kwargs = engine.generate.call_args[1]
        assert "evil" not in call_kwargs
        assert call_kwargs.get("num_ctx") == 8192
