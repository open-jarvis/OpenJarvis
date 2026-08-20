"""Agent-pillar appliers: prompts, class, params, few-shot.

See spec §4.1 op semantics for agent ops.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from openjarvis.learning.spec_search.execute.base import (
    ApplyContext,
    ApplyResult,
    EditApplier,
    ValidationResult,
)
from openjarvis.learning.spec_search.models import Edit, EditOp
from openjarvis.learning.spec_search.plan.prompt_diff import apply_unified_diff

logger = logging.getLogger(__name__)


def _agent_prompt_path(ctx: ApplyContext, agent_name: str) -> Path:
    return ctx.agents_dir / agent_name / "system_prompt.md"


def _extract_agent_name(edit: Edit) -> str:
    """Extract agent name from edit target or payload."""
    if "agent" in edit.payload:
        return edit.payload["agent"]
    # Try from target: "agents.simple.system_prompt" -> "simple"
    parts = edit.target.split(".")
    if len(parts) >= 2:
        return parts[1]
    return "default"


class ReplaceSystemPromptApplier(EditApplier):
    """Overwrite an agent's entire system prompt."""

    op = EditOp.REPLACE_SYSTEM_PROMPT

    def validate(self, edit: Edit, ctx: ApplyContext) -> ValidationResult:
        if "new_content" not in edit.payload:
            return ValidationResult(ok=False, reason="Missing new_content in payload")
        agent = _extract_agent_name(edit)
        prompt_path = _agent_prompt_path(ctx, agent)
        if not prompt_path.parent.exists():
            return ValidationResult(
                ok=False, reason=f"Agent directory not found: {prompt_path.parent}"
            )
        return ValidationResult(ok=True)

    def apply(self, edit: Edit, ctx: ApplyContext) -> ApplyResult:
        agent = _extract_agent_name(edit)
        prompt_path = _agent_prompt_path(ctx, agent)
        prompt_path.write_text(edit.payload["new_content"], encoding="utf-8")
        return ApplyResult(changed_files=[str(prompt_path)])

    def rollback(self, edit: Edit, ctx: ApplyContext) -> None:
        pass


class PatchSystemPromptApplier(EditApplier):
    """Apply a unified diff to an agent's system prompt."""

    op = EditOp.PATCH_SYSTEM_PROMPT

    def validate(self, edit: Edit, ctx: ApplyContext) -> ValidationResult:
        if "diff" not in edit.payload:
            return ValidationResult(ok=False, reason="Missing diff in payload")
        agent = _extract_agent_name(edit)
        prompt_path = _agent_prompt_path(ctx, agent)
        if not prompt_path.exists():
            return ValidationResult(
                ok=False, reason=f"Prompt file not found: {prompt_path}"
            )
        original = prompt_path.read_text(encoding="utf-8")
        patched = apply_unified_diff(original, edit.payload["diff"])
        if patched is None:
            return ValidationResult(
                ok=False, reason="Diff cannot be applied to current prompt"
            )
        return ValidationResult(ok=True)

    def apply(self, edit: Edit, ctx: ApplyContext) -> ApplyResult:
        agent = _extract_agent_name(edit)
        prompt_path = _agent_prompt_path(ctx, agent)
        original = prompt_path.read_text(encoding="utf-8")
        patched = apply_unified_diff(original, edit.payload["diff"])
        if patched is None:
            raise RuntimeError(f"Failed to apply diff to {prompt_path}")
        prompt_path.write_text(patched, encoding="utf-8")
        return ApplyResult(changed_files=[str(prompt_path)])

    def rollback(self, edit: Edit, ctx: ApplyContext) -> None:
        pass


class SetAgentClassApplier(EditApplier):
    """Change which agent class is used."""

    op = EditOp.SET_AGENT_CLASS

    def validate(self, edit: Edit, ctx: ApplyContext) -> ValidationResult:
        if "new_class" not in edit.payload:
            return ValidationResult(ok=False, reason="Missing new_class in payload")
        return ValidationResult(ok=True)

    def apply(self, edit: Edit, ctx: ApplyContext) -> ApplyResult:
        agent = _extract_agent_name(edit)
        new_class = edit.payload["new_class"]
        config_path = ctx.config_path
        content = (
            config_path.read_text(encoding="utf-8") if config_path.exists() else ""
        )  # noqa: E501

        section = f"[agent.{agent}]"
        if section in content:
            lines = content.splitlines()
            in_section = False
            found = False
            for i, line in enumerate(lines):
                if line.strip() == section:
                    in_section = True
                    continue
                if in_section and line.strip().startswith("["):
                    break
                if in_section and line.strip().startswith("class"):
                    lines[i] = f'class = "{new_class}"'
                    found = True
                    break
            if not found:
                for i, line in enumerate(lines):
                    if line.strip() == section:
                        lines.insert(i + 1, f'class = "{new_class}"')
                        break
            content = "\n".join(lines) + "\n"
        else:
            content += f'\n{section}\nclass = "{new_class}"\n'

        config_path.write_text(content, encoding="utf-8")
        return ApplyResult(changed_files=[str(config_path)])

    def rollback(self, edit: Edit, ctx: ApplyContext) -> None:
        pass


class SetAgentParamApplier(EditApplier):
    """Update an agent parameter."""

    op = EditOp.SET_AGENT_PARAM

    def validate(self, edit: Edit, ctx: ApplyContext) -> ValidationResult:
        for key in ("agent", "param", "value"):
            if key not in edit.payload:
                return ValidationResult(ok=False, reason=f"Missing {key} in payload")
        return ValidationResult(ok=True)

    def apply(self, edit: Edit, ctx: ApplyContext) -> ApplyResult:
        agent = edit.payload["agent"]
        param = edit.payload["param"]
        value = edit.payload["value"]
        config_path = ctx.config_path
        content = (
            config_path.read_text(encoding="utf-8") if config_path.exists() else ""
        )  # noqa: E501

        section = f"[agent.{agent}]"
        if section in content:
            lines = content.splitlines()
            in_section = False
            found = False
            for i, line in enumerate(lines):
                if line.strip() == section:
                    in_section = True
                    continue
                if in_section and line.strip().startswith("["):
                    lines.insert(i, f"{param} = {value}")
                    found = True
                    break
                if in_section and line.strip().startswith(f"{param}"):
                    lines[i] = f"{param} = {value}"
                    found = True
                    break
            if not found:
                lines.append(f"{param} = {value}")
            content = "\n".join(lines) + "\n"
        else:
            content += f"\n{section}\n{param} = {value}\n"

        config_path.write_text(content, encoding="utf-8")
        return ApplyResult(changed_files=[str(config_path)])

    def rollback(self, edit: Edit, ctx: ApplyContext) -> None:
        pass


class EditFewShotExemplarsApplier(EditApplier):
    """Write few-shot exemplars to an agent's directory."""

    op = EditOp.EDIT_FEW_SHOT_EXEMPLARS

    def validate(self, edit: Edit, ctx: ApplyContext) -> ValidationResult:
        if "exemplars" not in edit.payload:
            return ValidationResult(ok=False, reason="Missing exemplars in payload")
        agent = _extract_agent_name(edit)
        agent_dir = ctx.agents_dir / agent
        if not agent_dir.exists():
            return ValidationResult(
                ok=False, reason=f"Agent directory not found: {agent_dir}"
            )
        return ValidationResult(ok=True)

    def apply(self, edit: Edit, ctx: ApplyContext) -> ApplyResult:
        agent = _extract_agent_name(edit)
        fs_path = ctx.agents_dir / agent / "few_shot.json"
        fs_path.write_text(
            json.dumps(edit.payload["exemplars"], indent=2),
            encoding="utf-8",
        )
        return ApplyResult(changed_files=[str(fs_path)])

    def rollback(self, edit: Edit, ctx: ApplyContext) -> None:
        pass
