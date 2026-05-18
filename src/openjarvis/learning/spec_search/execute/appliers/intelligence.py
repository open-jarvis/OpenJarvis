"""Intelligence-pillar appliers: model routing and parameters.

See spec §4.1 op semantics for SET_MODEL_FOR_QUERY_CLASS and SET_MODEL_PARAM.
"""

from __future__ import annotations

from openjarvis.learning.spec_search.execute.base import (
    ApplyContext,
    ApplyResult,
    EditApplier,
    ValidationResult,
)
from openjarvis.learning.spec_search.models import Edit, EditOp


class SetModelForQueryClassApplier(EditApplier):
    """Update the routing policy map for a query class."""

    op = EditOp.SET_MODEL_FOR_QUERY_CLASS

    def validate(self, edit: Edit, ctx: ApplyContext) -> ValidationResult:
        if "query_class" not in edit.payload or "model" not in edit.payload:
            return ValidationResult(
                ok=False, reason="Missing query_class or model in payload"
            )
        return ValidationResult(ok=True)

    def apply(self, edit: Edit, ctx: ApplyContext) -> ApplyResult:
        query_class = edit.payload["query_class"]
        model = edit.payload["model"]
        config_path = ctx.config_path
        content = (
            config_path.read_text(encoding="utf-8") if config_path.exists() else ""
        )

        # Check if the policy_map section exists
        if "[learning.routing.policy_map]" in content:
            # Check if this query_class already has a line
            lines = content.splitlines()
            found = False
            for i, line in enumerate(lines):
                stripped = line.strip()
                if stripped.startswith(f"{query_class}") and "=" in stripped:
                    lines[i] = f'{query_class} = "{model}"'
                    found = True
                    break
            if not found:
                # Append after the [learning.routing.policy_map] header
                for i, line in enumerate(lines):
                    if line.strip() == "[learning.routing.policy_map]":
                        lines.insert(i + 1, f'{query_class} = "{model}"')
                        break
            content = "\n".join(lines) + "\n"
        else:
            # Append the section
            content += f'\n[learning.routing.policy_map]\n{query_class} = "{model}"\n'

        config_path.write_text(content, encoding="utf-8")
        return ApplyResult(changed_files=[str(config_path)])

    def rollback(self, edit: Edit, ctx: ApplyContext) -> None:
        pass  # Delegated to CheckpointStore.discard_stage() in the execution loop


class SetModelParamApplier(EditApplier):
    """Update a model parameter in config."""

    op = EditOp.SET_MODEL_PARAM

    def validate(self, edit: Edit, ctx: ApplyContext) -> ValidationResult:
        for key in ("model", "param", "value"):
            if key not in edit.payload:
                return ValidationResult(ok=False, reason=f"Missing {key} in payload")
        return ValidationResult(ok=True)

    def apply(self, edit: Edit, ctx: ApplyContext) -> ApplyResult:
        model = edit.payload["model"]
        param = edit.payload["param"]
        value = edit.payload["value"]
        config_path = ctx.config_path
        content = (
            config_path.read_text(encoding="utf-8") if config_path.exists() else ""
        )

        # Sanitize model name for TOML section header (replace : with -)
        section_key = model.replace(":", "-")
        section_header = f"[models.{section_key}]"

        if section_header in content:
            lines = content.splitlines()
            in_section = False
            found = False
            for i, line in enumerate(lines):
                if line.strip() == section_header:
                    in_section = True
                    continue
                if in_section and line.strip().startswith("["):
                    # Hit next section — insert before it
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
            content += f"\n{section_header}\n{param} = {value}\n"

        config_path.write_text(content, encoding="utf-8")
        return ApplyResult(changed_files=[str(config_path)])

    def rollback(self, edit: Edit, ctx: ApplyContext) -> None:
        pass  # Delegated to CheckpointStore.discard_stage()
