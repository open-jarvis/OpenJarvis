"""Tools-pillar appliers: add/remove tools, edit descriptions.

See spec §4.1 op semantics for tool ops.
"""

from __future__ import annotations

import re

from openjarvis.learning.spec_search.execute.base import (
    ApplyContext,
    ApplyResult,
    EditApplier,
    ValidationResult,
)
from openjarvis.learning.spec_search.models import Edit, EditOp


class AddToolToAgentApplier(EditApplier):
    """Add a tool to an agent's tool list in config."""

    op = EditOp.ADD_TOOL_TO_AGENT

    def validate(self, edit: Edit, ctx: ApplyContext) -> ValidationResult:
        for key in ("agent", "tool_name"):
            if key not in edit.payload:
                return ValidationResult(ok=False, reason=f"Missing {key} in payload")
        return ValidationResult(ok=True)

    def apply(self, edit: Edit, ctx: ApplyContext) -> ApplyResult:
        agent = edit.payload["agent"]
        tool_name = edit.payload["tool_name"]
        config_path = ctx.config_path
        content = (
            config_path.read_text(encoding="utf-8") if config_path.exists() else ""
        )

        section = f"[agent.{agent}]"
        if section in content:
            lines = content.splitlines()
            in_section = False
            for i, line in enumerate(lines):
                if line.strip() == section:
                    in_section = True
                    continue
                if in_section and line.strip().startswith("["):
                    break
                if in_section and line.strip().startswith("tools"):
                    # Parse existing tool list and add new tool
                    match = re.search(r"\[([^\]]*)\]", line)
                    if match:
                        existing = match.group(1)
                        if tool_name not in existing:
                            new_list = existing.rstrip() + f', "{tool_name}"'
                            lines[i] = f"tools = [{new_list}]"
                    break
            content = "\n".join(lines) + "\n"
        else:
            content += f'\n{section}\ntools = ["{tool_name}"]\n'

        config_path.write_text(content, encoding="utf-8")
        return ApplyResult(changed_files=[str(config_path)])

    def rollback(self, edit: Edit, ctx: ApplyContext) -> None:
        pass


class RemoveToolFromAgentApplier(EditApplier):
    """Remove a tool from an agent's tool list in config."""

    op = EditOp.REMOVE_TOOL_FROM_AGENT

    def validate(self, edit: Edit, ctx: ApplyContext) -> ValidationResult:
        for key in ("agent", "tool_name"):
            if key not in edit.payload:
                return ValidationResult(ok=False, reason=f"Missing {key} in payload")
        return ValidationResult(ok=True)

    def apply(self, edit: Edit, ctx: ApplyContext) -> ApplyResult:
        agent = edit.payload["agent"]
        tool_name = edit.payload["tool_name"]
        config_path = ctx.config_path
        content = (
            config_path.read_text(encoding="utf-8") if config_path.exists() else ""
        )

        section = f"[agent.{agent}]"
        if section in content:
            lines = content.splitlines()
            in_section = False
            for i, line in enumerate(lines):
                if line.strip() == section:
                    in_section = True
                    continue
                if in_section and line.strip().startswith("["):
                    break
                if in_section and line.strip().startswith("tools"):
                    # Remove the tool from the list
                    line = re.sub(rf',?\s*"{re.escape(tool_name)}"', "", line)
                    line = re.sub(rf'"{re.escape(tool_name)}"\s*,?\s*', "", line)
                    lines[i] = line
                    break
            content = "\n".join(lines) + "\n"

        config_path.write_text(content, encoding="utf-8")
        return ApplyResult(changed_files=[str(config_path)])

    def rollback(self, edit: Edit, ctx: ApplyContext) -> None:
        pass


class EditToolDescriptionApplier(EditApplier):
    """Update a tool's LM-facing description in descriptions.toml."""

    op = EditOp.EDIT_TOOL_DESCRIPTION

    def validate(self, edit: Edit, ctx: ApplyContext) -> ValidationResult:
        for key in ("tool_name", "new_description"):
            if key not in edit.payload:
                return ValidationResult(ok=False, reason=f"Missing {key} in payload")
        return ValidationResult(ok=True)

    def apply(self, edit: Edit, ctx: ApplyContext) -> ApplyResult:
        tool_name = edit.payload["tool_name"]
        new_desc = edit.payload["new_description"]
        desc_path = ctx.tools_dir / "descriptions.toml"
        desc_path.parent.mkdir(parents=True, exist_ok=True)

        content = desc_path.read_text(encoding="utf-8") if desc_path.exists() else ""

        section = f"[{tool_name}]"
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
                if in_section and line.strip().startswith("description"):
                    lines[i] = f'description = "{new_desc}"'
                    found = True
                    break
            if not found:
                for i, line in enumerate(lines):
                    if line.strip() == section:
                        lines.insert(i + 1, f'description = "{new_desc}"')
                        break
            content = "\n".join(lines) + "\n"
        else:
            content += f'\n{section}\ndescription = "{new_desc}"\n'

        desc_path.write_text(content, encoding="utf-8")
        return ApplyResult(changed_files=[str(desc_path)])

    def rollback(self, edit: Edit, ctx: ApplyContext) -> None:
        pass
