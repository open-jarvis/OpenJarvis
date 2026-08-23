"""Ensure nested skill execution preserves the caller security identity."""

from __future__ import annotations

from types import SimpleNamespace

from openjarvis.core.config import JarvisConfig
from openjarvis.core.types import ToolCall
from openjarvis.security.capabilities import CapabilityPolicy
from openjarvis.skills.executor import SkillExecutor
from openjarvis.skills.tool_adapter import SkillTool
from openjarvis.skills.types import SkillManifest, SkillStep
from openjarvis.system import SystemBuilder
from openjarvis.tools.repl import ReplTool


class _HealthyEngine:
    def health(self) -> bool:
        return True


class _PipelineSkillManager:
    inner_executor = None

    def __init__(self, *args, **kwargs) -> None:
        self._executor = None

    def discover(self, paths=None) -> None:
        pass

    def set_tool_executor(self, executor) -> None:
        self._executor = executor

    def get_skill_tools(self, *, tool_executor=None):
        executor = tool_executor or self._executor
        type(self).inner_executor = executor
        manifest = SkillManifest(
            name="restricted_pipeline",
            steps=[
                SkillStep(
                    tool_name="repl",
                    arguments_template='{"code": "sentinel = 42"}',
                )
            ],
        )
        return [SkillTool(manifest, SkillExecutor(executor))]

    def get_few_shot_examples(self):
        return []


def test_builder_nested_skill_cannot_fall_back_to_default_identity(
    tmp_path, monkeypatch
) -> None:
    config = JarvisConfig()
    config.telemetry.enabled = False
    config.traces.enabled = False
    config.skills.enabled = True
    config.skills.skills_dir = str(tmp_path / "skills")
    config.agent_manager.enabled = False
    config.sessions.enabled = False
    config.scheduler.enabled = False
    config.workflow.enabled = False

    policy = CapabilityPolicy(default_deny=True)
    policy.grant("_default", "code:execute")
    policy.deny("restricted", "code:execute")
    repl = ReplTool()

    monkeypatch.setattr(
        "openjarvis.security.setup_security",
        lambda config, engine, bus: SimpleNamespace(
            engine=engine,
            capability_policy=policy,
            rate_limiter=None,
            audit_logger=None,
        ),
    )
    monkeypatch.setattr("openjarvis.skills.manager.SkillManager", _PipelineSkillManager)

    builder = (
        SystemBuilder(config)
        .engine_instance(_HealthyEngine())
        .model("model")
        .agent("restricted")
        .telemetry(False)
        .traces(False)
        .speech(False)
    )
    monkeypatch.setattr(builder, "_resolve_memory", lambda config: None)
    monkeypatch.setattr(builder, "_resolve_channel", lambda config, bus: None)
    monkeypatch.setattr(builder, "_resolve_tools", lambda *args, **kwargs: [repl])
    monkeypatch.setattr(builder, "_setup_sandbox", lambda config: None)
    monkeypatch.setattr(builder, "_setup_scheduler", lambda config, bus: (None, None))
    monkeypatch.setattr(builder, "_setup_workflow", lambda config, bus: None)
    monkeypatch.setattr(builder, "_setup_sessions", lambda config: None)
    monkeypatch.setattr(builder, "_setup_learning_orchestrator", lambda config: None)

    system = builder.build()
    inner = _PipelineSkillManager.inner_executor
    assert inner._agent_id == "restricted"
    assert system.tool_executor._agent_id == "restricted"

    result = system.tool_executor.execute(
        ToolCall(
            id="nested-skill-denied",
            name="skill_restricted_pipeline",
            arguments="{}",
        )
    )

    assert not result.success
    assert "code:execute" in result.content
    assert repl._sessions == {}
