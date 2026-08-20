"""Shared runtime-tool factory regressions."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from openjarvis.core.registry import ToolRegistry
from openjarvis.core.types import ToolResult
from openjarvis.system.runtime_tools import build_runtime_tools, resolve_tool_names
from openjarvis.tools._stubs import BaseTool, ToolSpec


def _config(*, enabled="", legacy="", skills=False, skills_dir=""):
    return SimpleNamespace(
        tools=SimpleNamespace(enabled=enabled),
        agent=SimpleNamespace(tools=legacy),
        skills=SimpleNamespace(enabled=skills, skills_dir=skills_dir),
    )


class _Tool(BaseTool):
    tool_id = "memory_search"

    def __init__(self, *, backend=None):  # noqa: ANN001
        self.backend = backend

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(name=self.tool_id, description="test")

    def execute(self, **params) -> ToolResult:  # noqa: ANN003
        return ToolResult(tool_name=self.tool_id, content=str(params), success=True)


class _ExternalTool(_Tool):
    tool_id = "external"


def test_resolve_tool_names_uses_canonical_precedence() -> None:
    config = _config(enabled="calculator, think", legacy="web_search")

    assert resolve_tool_names(config) == ["calculator", "think"]
    assert resolve_tool_names(config, override="external") == ["external"]


def test_memory_tool_receives_process_owned_backend() -> None:
    backend = object()
    ToolRegistry.register_value("memory_search", _Tool)

    bundle = build_runtime_tools(
        _config(enabled="memory_search"),
        bus=MagicMock(),
        engine=MagicMock(),
        model="test-model",
        memory_backend=backend,
        include_skills=False,
    )

    assert len(bundle.tools) == 1
    assert bundle.tools[0].backend is backend


def test_external_tools_are_deduplicated_before_execution() -> None:
    ToolRegistry.register_value("external", _ExternalTool)
    external = _ExternalTool()

    bundle = build_runtime_tools(
        _config(enabled="external"),
        bus=MagicMock(),
        engine=MagicMock(),
        model="test-model",
        extra_tools=[external],
        include_skills=False,
    )

    assert len(bundle.tools) == 1
    assert bundle.tools[0] is not external


def test_skill_executor_can_dispatch_process_owned_external_tools(
    monkeypatch,
    tmp_path,
) -> None:  # noqa: ANN001
    captured = {}

    class _SkillManager:
        def __init__(self, bus, capability_policy=None):  # noqa: ANN001
            captured["bus"] = bus
            captured["capability_policy"] = capability_policy

        def discover(self, *, paths):  # noqa: ANN001
            captured["paths"] = paths

        def set_tool_executor(self, executor):  # noqa: ANN001
            captured["executor"] = executor

        def get_skill_tools(self, *, tool_executor):  # noqa: ANN001
            assert tool_executor is captured["executor"]
            return []

        def get_few_shot_examples(self):
            return []

    monkeypatch.setattr("openjarvis.skills.manager.SkillManager", _SkillManager)
    external = _ExternalTool()
    bus = MagicMock()

    bundle = build_runtime_tools(
        _config(enabled="missing", skills=True, skills_dir=str(tmp_path)),
        bus=bus,
        engine=MagicMock(),
        model="test-model",
        extra_tools=[external],
    )

    assert bundle.tools == [external]
    assert captured["bus"] is bus
    assert captured["executor"]._tools == {"external": external}
