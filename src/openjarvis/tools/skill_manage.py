"""SkillManageTool — create, list, load, or delete agent-authored skills."""

from __future__ import annotations

import json
import logging
import os
import re
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, List, Optional
from urllib.parse import urlsplit

from openjarvis.core.paths import get_config_dir
from openjarvis.core.registry import ToolRegistry
from openjarvis.core.types import ToolResult
from openjarvis.tools._stubs import BaseTool, ToolSpec

logger = logging.getLogger(__name__)

_SAFE_SKILL_NAME = re.compile(r"^[a-z0-9]+(?:[._-][a-z0-9]+)*$")


def _toml_string(value: Any) -> str:
    """Serialize one untrusted value as a TOML basic string."""
    return json.dumps(str(value), ensure_ascii=False)


@ToolRegistry.register("skill_manage")
class SkillManageTool(BaseTool):
    """Manage agent-authored procedural skills."""

    def __init__(
        self,
        skills_dir: Path | str | None = None,
        *,
        skill_manager: Any = None,
        memory_backend: Any = None,
    ) -> None:
        if skills_dir is None:
            skills_dir = get_config_dir() / "skills"
        self._skills_dir = Path(skills_dir).expanduser()
        self._skill_manager = skill_manager
        self._memory_backend = memory_backend

    def bind_runtime(
        self,
        *,
        skill_manager: Any,
        memory_backend: Any,
        skills_dir: Path | str | None = None,
    ) -> None:
        """Attach the live services created during system composition."""
        self._skill_manager = skill_manager
        self._memory_backend = memory_backend
        if skills_dir is not None:
            self._skills_dir = Path(skills_dir).expanduser()

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="skill_manage",
            description="Create, list, load, delete, or run agent-authored skills.",
            parameters={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["create", "list", "load", "delete", "run"],
                        "description": "Action to perform.",
                    },
                    "name": {
                        "type": "string",
                        "description": "Skill name (for create/load/delete).",
                    },
                    "description": {
                        "type": "string",
                        "description": "Skill description (for create).",
                    },
                    "steps": {
                        "type": "array",
                        "description": (
                            "List of step dicts with tool_name and optional"
                            " arguments_template (for create)."
                        ),
                    },
                    "context": {
                        "type": "object",
                        "description": "Initial context for run.",
                    },
                    "intent": {
                        "type": "string",
                        "description": "Optional intent remembered for create.",
                    },
                    "requires_fresh_confirmation": {
                        "type": "boolean",
                        "description": "Whether replay requires a new confirmation.",
                    },
                    "checkout": {
                        "type": "boolean",
                        "description": (
                            "Enforce a single-use turn nonce and cart revision "
                            "for this procedure."
                        ),
                    },
                },
                "required": ["action"],
            },
            category="skill",
        )

    def execute(self, **params: Any) -> ToolResult:
        action = params.get("action", "list")
        name = params.get("name", "")
        if action == "create":
            return self._create(
                name,
                params.get("description", ""),
                params.get("steps", []),
                params.get("intent"),
                params.get("requires_fresh_confirmation", True),
                params.get("checkout", False),
            )
        elif action == "list":
            return self._list()
        elif action == "load":
            return self._load(name)
        elif action == "delete":
            return self._delete(name)
        elif action == "run":
            return self._run(name, params.get("context", {}))
        return ToolResult(
            tool_name=self.spec.name,
            success=False,
            content=f"Unknown action: {action}",
        )

    def _create(
        self,
        name: str,
        description: str,
        steps: List[dict],
        intent: Optional[str] = None,
        requires_fresh_confirmation: bool = True,
        checkout: bool = False,
    ) -> ToolResult:
        path = self._skill_path(name)
        if path is None:
            return self._invalid_name()
        self._skills_dir.mkdir(parents=True, exist_ok=True)
        lines = [
            "[skill]",
            f"name = {_toml_string(name)}",
            f"description = {_toml_string(description)}",
            f"checkout = {'true' if checkout else 'false'}",
            "",
        ]
        for step in steps:
            lines.append("[[skill.steps]]")
            lines.append(f"tool_name = {_toml_string(step.get('tool_name', ''))}")
            if "arguments_template" in step:
                lines.append(
                    f"arguments_template = {_toml_string(step['arguments_template'])}"
                )
            if "output_key" in step:
                lines.append(f"output_key = {_toml_string(step['output_key'])}")
            if step.get("assertions"):
                lines.append(
                    "assertions_json = " + _toml_string(json.dumps(step["assertions"]))
                )
            lines.append("")
        fd, temp_path = tempfile.mkstemp(dir=self._skills_dir, suffix=".toml")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                stream.write("\n".join(lines))
            os.replace(temp_path, path)
        finally:
            if os.path.exists(temp_path):
                os.unlink(temp_path)

        if self._skill_manager is not None:
            try:
                self._skill_manager.discover(paths=[self._skills_dir])
            except Exception as exc:
                return ToolResult(
                    tool_name=self.spec.name,
                    success=False,
                    content=f"Created skill but failed to discover it: {exc}",
                )
        normalized_intent = self._normalize_intent(intent)
        if normalized_intent and self._memory_backend is not None:
            try:
                replay_policy = (
                    "Run only after fresh confirmation."
                    if requires_fresh_confirmation
                    else "No confirmation is required; this skill only reads live data."
                )
                self._memory_backend.store(
                    (
                        f"Intent '{normalized_intent}' maps to skill '{name}'. "
                        f"{replay_policy}"
                    ),
                    source="openjarvis.skill_learning",
                    metadata={
                        "intent": normalized_intent,
                        "skill_name": name,
                        "requires_fresh_confirmation": requires_fresh_confirmation,
                    },
                )
            except Exception:
                # The skill is already written and discovered; losing only the
                # recall hint must not turn a successful create into a raise.
                logger.warning("Failed to remember skill intent", exc_info=True)
        return ToolResult(
            tool_name=self.spec.name,
            success=True,
            content=f"Created skill: {name}",
        )

    def has_skill(self, name: str) -> bool:
        """Whether a recalled procedure is executable in this runtime now."""
        exists = (
            self._skill_manager is not None
            and name in self._skill_manager.skill_names()
        )
        return bool(
            exists
            and not self._is_unguarded_transaction(name)
            and not self._is_superseded_learned_read(name)
        )

    @staticmethod
    def _http_origins(manifest: Any) -> set[tuple[str, str]]:
        origins: set[tuple[str, str]] = set()
        for step in manifest.steps:
            if step.tool_name != "http_request":
                continue
            try:
                url = json.loads(step.arguments_template).get("url", "")
            except (AttributeError, json.JSONDecodeError):
                continue
            parsed = urlsplit(str(url))
            if parsed.scheme and parsed.netloc:
                origins.add((parsed.scheme.lower(), parsed.netloc.lower()))
        return origins

    def _is_superseded_learned_read(self, name: Any) -> bool:
        if not isinstance(name, str) or not name.startswith("learned-read-"):
            return False
        resolve = getattr(self._skill_manager, "resolve", None)
        if not callable(resolve):
            return False
        try:
            learned = resolve(name)
        except (KeyError, TypeError):
            return False
        display = next(
            (
                step.tool_name
                for step in reversed(learned.steps)
                if step.tool_name.startswith("display_")
            ),
            "",
        )
        origins = self._http_origins(learned)
        if not display or not origins:
            return False
        for candidate_name in self._skill_manager.skill_names():
            if candidate_name == name or candidate_name.startswith("learned-"):
                continue
            try:
                candidate = resolve(candidate_name)
            except (KeyError, TypeError):
                continue
            candidate_display = next(
                (
                    step.tool_name
                    for step in reversed(candidate.steps)
                    if step.tool_name.startswith("display_")
                ),
                "",
            )
            if (
                candidate_display == display
                and origins & self._http_origins(candidate)
            ):
                return True
        return False

    def _is_unguarded_transaction(self, name: Any) -> bool:
        resolve = getattr(self._skill_manager, "resolve", None)
        if not callable(resolve):
            return False
        try:
            manifest = resolve(name)
        except (KeyError, TypeError):
            return False
        if manifest.checkout:
            return False
        source = (manifest.metadata.get("openjarvis", {}) or {}).get("source")
        learned_transaction = (
            isinstance(name, str) and name.startswith("learned-transaction-")
        ) or (
            source == "learned"
            and manifest.metadata.get("requires_fresh_confirmation") is True
        )
        if not learned_transaction:
            return False
        for step in manifest.steps:
            if step.tool_name != "http_request":
                continue
            try:
                method = json.loads(step.arguments_template).get("method", "GET")
            except (AttributeError, json.JSONDecodeError):
                match = re.search(
                    r'["\']method["\']\s*:\s*["\']([A-Za-z]+)',
                    step.arguments_template,
                )
                method = match.group(1) if match else "GET"
            if str(method).upper() in {"POST", "PUT", "PATCH", "DELETE"}:
                return True
        return False

    def _run(self, name: Any, context: Any) -> ToolResult:
        if self._skill_manager is None:
            return ToolResult(
                tool_name=self.spec.name,
                success=False,
                content="Skill manager unavailable: cannot run skills in this runtime.",
            )
        if not isinstance(context, dict):
            return ToolResult(
                tool_name=self.spec.name,
                success=False,
                content="Skill context must be an object.",
            )
        if self._is_unguarded_transaction(name):
            return ToolResult(
                tool_name=self.spec.name,
                success=False,
                content=(
                    "Blocked unguarded transaction skill; use an active "
                    "checkout procedure with fresh confirmation."
                ),
            )
        if self._is_superseded_learned_read(name):
            return ToolResult(
                tool_name=self.spec.name,
                success=False,
                content=(
                    "Blocked stale learned read; use the canonical read procedure "
                    "for this merchant."
                ),
            )
        context = {
            "today": datetime.now().astimezone().date().isoformat(),
            **context,
        }
        try:
            result = self._skill_manager.execute(name, context)
        except Exception as exc:
            return ToolResult(
                tool_name=self.spec.name,
                success=False,
                content=f"Skill run failed: {exc}",
            )
        if not result.step_results:
            return ToolResult(
                tool_name=self.spec.name,
                success=False,
                content="Skill run produced no result.",
            )
        final = result.step_results[-1]
        metadata = dict(final.metadata)
        if result.success and final.success and final.tool_name.startswith("display_"):
            metadata["completed_display"] = True
        return ToolResult(
            tool_name=self.spec.name,
            content=final.content,
            success=final.success,
            usage=final.usage,
            cost_usd=final.cost_usd,
            latency_seconds=final.latency_seconds,
            metadata=metadata,
        )

    def _list(self) -> ToolResult:
        if self._skill_manager is not None:
            skills = sorted(
                name
                for name in self._skill_manager.skill_names()
                if self.has_skill(name)
            )
        else:
            if not self._skills_dir.exists():
                return ToolResult(
                    tool_name=self.spec.name,
                    success=True,
                    content="No skills directory found.",
                )
            skills = [f.stem for f in sorted(self._skills_dir.glob("*.toml"))]
        if not skills:
            return ToolResult(
                tool_name=self.spec.name,
                success=True,
                content="No skills found.",
            )
        return ToolResult(
            tool_name=self.spec.name,
            success=True,
            content="Available skills:\n" + "\n".join(f"- {s}" for s in skills),
        )

    def _load(self, name: str) -> ToolResult:
        path = self._skill_path(name)
        if path is None:
            return self._invalid_name()
        if not path.exists():
            return ToolResult(
                tool_name=self.spec.name,
                success=False,
                content=f"Skill not found: {name}",
            )
        return ToolResult(
            tool_name=self.spec.name,
            success=True,
            content=path.read_text(encoding="utf-8"),
        )

    def _delete(self, name: str) -> ToolResult:
        path = self._skill_path(name)
        if path is None:
            return self._invalid_name()
        if not path.exists():
            return ToolResult(
                tool_name=self.spec.name,
                success=False,
                content=f"Skill not found: {name}",
            )
        path.unlink()
        return ToolResult(
            tool_name=self.spec.name,
            success=True,
            content=f"Deleted skill: {name}",
        )

    def _skill_path(self, name: Any) -> Path | None:
        """Return a resolved direct child, or reject before touching a file."""
        if not isinstance(name, str) or _SAFE_SKILL_NAME.fullmatch(name) is None:
            return None
        root = self._skills_dir.resolve()
        path = (root / f"{name}.toml").resolve()
        if path.parent != root:
            return None
        return path

    def _invalid_name(self) -> ToolResult:
        return ToolResult(
            tool_name=self.spec.name,
            success=False,
            content="Invalid skill name.",
        )

    @staticmethod
    def _normalize_intent(intent: Any) -> str:
        if not isinstance(intent, str):
            return ""
        return " ".join(intent.lower().split())
