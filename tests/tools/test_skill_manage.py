from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest
import tomllib

from openjarvis.core.events import EventBus
from openjarvis.core.types import ToolResult
from openjarvis.skills.executor import SkillResult
from openjarvis.skills.loader import load_skill
from openjarvis.skills.manager import SkillManager
from openjarvis.skills.types import SkillManifest, SkillStep
from openjarvis.tools.skill_manage import SkillManageTool


@pytest.fixture
def skills_dir(tmp_path: Path) -> Path:
    d = tmp_path / "skills"
    d.mkdir()
    return d


def test_skill_create(skills_dir: Path):
    from openjarvis.tools.skill_manage import SkillManageTool

    tool = SkillManageTool(skills_dir=skills_dir)
    result = tool.execute(
        action="create",
        name="api_health",
        description="Check API health",
        steps=[
            {
                "tool_name": "http_request",
                "arguments_template": '{"url": "{endpoint}/health"}',
            }
        ],
    )
    assert result.success
    assert (skills_dir / "api_health.toml").exists()


def test_skill_list(skills_dir: Path):
    from openjarvis.tools.skill_manage import SkillManageTool

    tool = SkillManageTool(skills_dir=skills_dir)
    tool.execute(
        action="create",
        name="skill_a",
        description="Skill A",
        steps=[{"tool_name": "calculator"}],
    )
    tool.execute(
        action="create",
        name="skill_b",
        description="Skill B",
        steps=[{"tool_name": "calculator"}],
    )
    result = tool.execute(action="list")
    assert "skill_a" in result.content
    assert "skill_b" in result.content


def test_skill_delete(skills_dir: Path):
    from openjarvis.tools.skill_manage import SkillManageTool

    tool = SkillManageTool(skills_dir=skills_dir)
    tool.execute(
        action="create",
        name="temp_skill",
        description="Temp",
        steps=[{"tool_name": "calculator"}],
    )
    assert (skills_dir / "temp_skill.toml").exists()
    result = tool.execute(action="delete", name="temp_skill")
    assert result.success
    assert not (skills_dir / "temp_skill.toml").exists()


def test_skill_load(skills_dir: Path):
    from openjarvis.tools.skill_manage import SkillManageTool

    tool = SkillManageTool(skills_dir=skills_dir)
    tool.execute(
        action="create",
        name="my_skill",
        description="My skill desc",
        steps=[
            {
                "tool_name": "web_search",
                "arguments_template": '{"q": "test"}',
            }
        ],
    )
    result = tool.execute(action="load", name="my_skill")
    assert "web_search" in result.content
    assert "My skill desc" in result.content


def test_skill_run_returns_only_the_final_inner_result(skills_dir: Path) -> None:
    class Manager:
        def execute(self, name: str, context: dict) -> SkillResult:
            assert name == "order-coffee"
            assert context == {
                "size": "large",
                "today": datetime.now().astimezone().date().isoformat(),
            }
            return SkillResult(
                skill_name=name,
                success=False,
                step_results=[
                    ToolResult(tool_name="http_request", content="request sent"),
                    ToolResult(
                        tool_name="display_bill",
                        content="payment required",
                        success=False,
                        metadata={"approval_id": "approval-1"},
                    ),
                ],
            )

    result = SkillManageTool(skills_dir=skills_dir, skill_manager=Manager()).execute(
        action="run",
        name="order-coffee",
        context={"size": "large"},
    )

    assert result.tool_name == "skill_manage"
    assert result.success is False
    assert result.content == "payment required"
    assert result.metadata == {"approval_id": "approval-1"}


def test_skill_run_marks_a_successful_inner_display_and_supplies_today(
    skills_dir: Path,
) -> None:
    class Manager:
        def execute(self, name: str, context: dict) -> SkillResult:
            assert context["today"] == datetime.now().astimezone().date().isoformat()
            return SkillResult(
                skill_name=name,
                success=True,
                step_results=[
                    ToolResult(tool_name="http_request", content="fresh menu"),
                    ToolResult(
                        tool_name="display_menu",
                        content="shown",
                        metadata={
                            "presentation_id": "p-1",
                            "customer_message": "Menu đang hiển thị.",
                        },
                    ),
                ],
            )

    result = SkillManageTool(skills_dir=skills_dir, skill_manager=Manager()).execute(
        action="run", name="read-menu", context={}
    )

    assert result.success is True
    assert result.metadata == {
        "presentation_id": "p-1",
        "customer_message": "Menu đang hiển thị.",
        "completed_display": True,
    }


def test_unguarded_learned_transaction_is_not_recalled_or_executed(
    skills_dir: Path,
) -> None:
    class Manager:
        manifest = SkillManifest(
            name="learned-transaction-fixture",
            steps=[
                SkillStep(
                    tool_name="http_request",
                    arguments_template='{"url":"https://merchant.test/orders","method":"POST"}',
                )
            ],
        )

        def skill_names(self) -> list[str]:
            return [self.manifest.name]

        def resolve(self, name: str) -> SkillManifest:
            assert name == self.manifest.name
            return self.manifest

        def execute(self, name: str, context: dict) -> SkillResult:
            raise AssertionError("unguarded transaction must not execute")

    tool = SkillManageTool(skills_dir=skills_dir, skill_manager=Manager())

    assert tool.has_skill("learned-transaction-fixture") is False
    result = tool.execute(
        action="run", name="learned-transaction-fixture", context={}
    )
    assert result.success is False
    assert "unguarded transaction" in result.content.lower()


def test_learned_read_is_suppressed_when_a_canonical_read_exists(
    skills_dir: Path,
) -> None:
    learned = SkillManifest(
        name="learned-read-menu",
        steps=[
            SkillStep(
                tool_name="http_request",
                arguments_template=(
                    '{"url":"https://merchant.test/menu?category=stale",'
                    '"method":"GET"}'
                ),
            ),
            SkillStep(tool_name="display_menu"),
        ],
    )
    canonical = SkillManifest(
        name="merchant-menu",
        steps=[
            SkillStep(
                tool_name="http_request",
                arguments_template=(
                    '{"url":"https://merchant.test/menu?category={category}",'
                    '"method":"GET"}'
                ),
            ),
            SkillStep(tool_name="display_menu"),
        ],
    )

    class Manager:
        manifests = {item.name: item for item in (learned, canonical)}

        def skill_names(self) -> list[str]:
            return list(self.manifests)

        def resolve(self, name: str) -> SkillManifest:
            return self.manifests[name]

        def execute(self, name: str, context: dict) -> SkillResult:
            raise AssertionError("superseded learned read must not execute")

    tool = SkillManageTool(skills_dir=skills_dir, skill_manager=Manager())

    assert tool.has_skill("merchant-menu") is True
    assert tool.has_skill("learned-read-menu") is False
    listed = tool.execute(action="list")
    assert "merchant-menu" in listed.content
    assert "learned-read-menu" not in listed.content
    result = tool.execute(action="run", name="learned-read-menu", context={})
    assert result.success is False
    assert "canonical read" in result.content.lower()


def test_skill_run_without_runtime_dependencies_does_not_create_a_directory(
    tmp_path: Path,
) -> None:
    skills_dir = tmp_path / "skills"

    result = SkillManageTool(skills_dir=skills_dir).execute(
        action="run",
        name="order-coffee",
        context={},
    )

    assert result.success is False
    assert "manager unavailable" in result.content.lower()
    assert not skills_dir.exists()


def test_skill_manage_schema_exposes_run_context_and_create_intent() -> None:
    properties = SkillManageTool().spec.parameters["properties"]

    assert "run" in properties["action"]["enum"]
    assert properties["context"]["type"] == "object"
    assert properties["intent"]["type"] == "string"


def test_read_skill_memory_hint_does_not_require_confirmation(tmp_path: Path) -> None:
    """Safe learned reads should be immediately reusable on a later turn."""

    class Memory:
        def __init__(self) -> None:
            self.records = []

        def store(self, content, **kwargs):
            self.records.append({"content": content, **kwargs})

    memory = Memory()
    tool = SkillManageTool(skills_dir=tmp_path / "skills", memory_backend=memory)

    result = tool.execute(
        action="create",
        name="read-menu",
        description="Read a live menu",
        steps=[],
        intent="Show the food menu",
        requires_fresh_confirmation=False,
    )

    assert result.success is True
    assert memory.records[0]["metadata"]["requires_fresh_confirmation"] is False
    assert "No confirmation is required" in memory.records[0]["content"]


def test_skill_create_hot_discovers_and_remembers_normalized_intent(
    skills_dir: Path,
) -> None:
    class Memory:
        def __init__(self) -> None:
            self.records: list[dict] = []

        def store(self, content: str, *, source: str, metadata: dict) -> str:
            self.records.append(
                {"content": content, "source": source, "metadata": metadata}
            )
            return "memory-1"

    manager = SkillManager(bus=EventBus())
    memory = Memory()
    result = SkillManageTool(
        skills_dir=skills_dir,
        skill_manager=manager,
        memory_backend=memory,
    ).execute(
        action="create",
        name="order-coffee",
        description="Order coffee after confirmation.",
        steps=[{"tool_name": "http_request", "arguments_template": "{}"}],
        intent="  Order   Coffee  ",
    )

    assert result.success is True
    assert manager.resolve("order-coffee").name == "order-coffee"
    assert memory.records == [
        {
            "content": (
                "Intent 'order coffee' maps to skill 'order-coffee'. "
                "Run only after fresh confirmation."
            ),
            "source": "openjarvis.skill_learning",
            "metadata": {
                "intent": "order coffee",
                "skill_name": "order-coffee",
                "requires_fresh_confirmation": True,
            },
        }
    ]


def test_skill_create_survives_a_failing_memory_backend(skills_dir: Path) -> None:
    """The skill file is already on disk; a Memory outage must not raise."""

    class BrokenMemory:
        def store(self, content: str, *, source: str, metadata: dict) -> str:
            raise RuntimeError("memory backend down")

    manager = SkillManager(bus=EventBus())
    result = SkillManageTool(
        skills_dir=skills_dir,
        skill_manager=manager,
        memory_backend=BrokenMemory(),
    ).execute(
        action="create",
        name="order-coffee",
        description="Order coffee after confirmation.",
        steps=[{"tool_name": "http_request", "arguments_template": "{}"}],
        intent="order coffee",
    )

    assert result.success is True
    assert manager.resolve("order-coffee").name == "order-coffee"


@pytest.mark.parametrize("action", ["create", "load", "delete"])
def test_skill_name_traversal_is_rejected_before_file_io(
    skills_dir: Path, action: str
) -> None:
    outside = skills_dir.parent / "config.toml"
    outside.write_text("owner-data")
    tool = SkillManageTool(skills_dir=skills_dir)

    result = tool.execute(
        action=action,
        name="../config",
        description="attacker",
        steps=[{"tool_name": "http_request"}],
    )

    assert result.success is False
    assert outside.read_text() == "owner-data"
    assert "owner-data" not in result.content


def test_absolute_skill_name_is_rejected_before_file_io(
    skills_dir: Path, tmp_path: Path
) -> None:
    outside = tmp_path / "absolute-target.toml"
    tool = SkillManageTool(skills_dir=skills_dir)

    result = tool.execute(
        action="create",
        name=str(outside.with_suffix("")),
        description="attacker",
        steps=[],
    )

    assert result.success is False
    assert not outside.exists()


@pytest.mark.parametrize("action", ["create", "load", "delete"])
def test_resolved_skill_target_must_be_a_direct_child(
    skills_dir: Path, tmp_path: Path, action: str
) -> None:
    outside = tmp_path / "owner.toml"
    outside.write_text("owner-data")
    link = skills_dir / "safe.toml"
    link.symlink_to(outside)
    tool = SkillManageTool(skills_dir=skills_dir)

    result = tool.execute(
        action=action,
        name="safe",
        description="attacker",
        steps=[{"tool_name": "http_request"}],
    )

    assert result.success is False
    assert outside.read_text() == "owner-data"
    assert link.is_symlink()
    assert "owner-data" not in result.content


def test_created_skill_quotes_untrusted_values_as_toml(skills_dir: Path) -> None:
    tool = SkillManageTool(skills_dir=skills_dir)
    description = 'legit"\n[attacker]\nowned = "yes'
    tool_name = 'http_request"\n[[attacker.steps]]\nname = "owned'
    arguments_template = '{"query": "customer\'s \\"coffee\\"\nsize"}'
    output_key = 'result"\n[attacker.output]\nowned = "yes'

    result = tool.execute(
        action="create",
        name="safe_skill",
        description=description,
        steps=[
            {
                "tool_name": tool_name,
                "arguments_template": arguments_template,
                "output_key": output_key,
            }
        ],
    )

    assert result.success is True
    path = skills_dir / "safe_skill.toml"
    raw = tomllib.loads(path.read_text())
    manifest = load_skill(path)
    assert set(raw) == {"skill"}
    assert manifest.name == "safe_skill"
    assert manifest.description == description
    assert len(manifest.steps) == 1
    assert manifest.steps[0].tool_name == tool_name
    assert manifest.steps[0].arguments_template == arguments_template
    assert manifest.steps[0].output_key == output_key
