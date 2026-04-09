"""SkillManager — coordinates skill discovery, catalog, tool wrapping, and execution."""

from __future__ import annotations

import html
from pathlib import Path
from typing import Any, Dict, List, Optional

from openjarvis.core.events import EventBus
from openjarvis.skills.dependency import validate_dependencies
from openjarvis.skills.executor import SkillExecutor, SkillResult
from openjarvis.skills.loader import discover_skills
from openjarvis.skills.tool_adapter import SkillTool
from openjarvis.skills.types import SkillManifest
from openjarvis.tools._stubs import BaseTool, ToolExecutor


class SkillManager:
    """Coordinate skill discovery, resolution, catalog generation, and execution.

    Parameters
    ----------
    bus:
        Event bus for publishing lifecycle events.
    capability_policy:
        Optional capability policy passed through to tool executors.
    """

    def __init__(
        self,
        bus: EventBus,
        *,
        capability_policy: Optional[Any] = None,
        overlay_dir: Optional[Path] = None,
    ) -> None:
        self._bus = bus
        self._capability_policy = capability_policy
        self._skills: Dict[str, SkillManifest] = {}
        self._tool_executor: Optional[ToolExecutor] = None
        if overlay_dir is None:
            # Try to read from config first; fall back to the default
            # ~/.openjarvis/learning/skills/ if config can't be loaded.
            try:
                from openjarvis.core.config import load_config

                cfg = load_config()
                cfg_dir = getattr(
                    getattr(cfg.learning, "skills", None),
                    "overlay_dir",
                    None,
                )
                if cfg_dir:
                    overlay_dir = Path(cfg_dir).expanduser()
            except Exception:
                pass
            if overlay_dir is None:
                overlay_dir = Path(
                    "~/.openjarvis/learning/skills/"
                ).expanduser()
        self._overlay_dir = Path(overlay_dir).expanduser()

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------

    def discover(self, paths: Optional[List[Path]] = None) -> None:
        """Scan directories in order and register skills.

        First-seen name wins (workspace path listed first = highest precedence).
        After loading, the full dependency graph is validated and any
        sidecar overlays in ``overlay_dir`` are applied to discovered skills.

        Parameters
        ----------
        paths:
            Directories to scan.  If *None* or empty, no skills are loaded
            from disk — but ``_load_overlays()`` still runs (in case the
            caller had previously seeded ``self._skills`` directly).
        """
        if paths:
            for directory in paths:
                manifests = discover_skills(directory)
                for manifest in manifests:
                    # First-seen wins: do not overwrite an already-registered skill
                    if manifest.name not in self._skills:
                        self._skills[manifest.name] = manifest

            # Validate the dependency graph after loading skills
            if self._skills:
                validate_dependencies(self._skills)

        # Load optimization overlays (Plan 2A) — always runs, even when no
        # paths are provided, so callers can apply overlays to skills loaded
        # via other means.
        self._load_overlays()

    def _load_overlays(self) -> None:
        """Apply optimization overlays to discovered skills.

        For each skill, look for ``<overlay_dir>/<skill-name>/optimized.toml``.
        If present, override the manifest description and stash few-shot
        examples under ``manifest.metadata.openjarvis.few_shot``.

        Bad overlays are silently ignored — they should not break discovery.
        """
        from openjarvis.skills.overlay import SkillOverlayLoader

        loader = SkillOverlayLoader(self._overlay_dir)
        for name, manifest in self._skills.items():
            overlay = loader.load(name)
            if overlay is None:
                continue
            if overlay.description:
                manifest.description = overlay.description
            if overlay.few_shot:
                new_metadata = dict(manifest.metadata) if manifest.metadata else {}
                oj = dict(new_metadata.get("openjarvis", {}) or {})
                oj["few_shot"] = list(overlay.few_shot)
                new_metadata["openjarvis"] = oj
                manifest.metadata = new_metadata

    # ------------------------------------------------------------------
    # Resolve / introspect
    # ------------------------------------------------------------------

    def resolve(self, name: str) -> SkillManifest:
        """Return the manifest for a skill by name.

        Raises
        ------
        KeyError
            If *name* is not registered.
        """
        if name not in self._skills:
            raise KeyError(f"Skill '{name}' not found")
        return self._skills[name]

    def skill_names(self) -> List[str]:
        """Return the names of all registered skills."""
        return list(self._skills.keys())

    # ------------------------------------------------------------------
    # Tool wrapping
    # ------------------------------------------------------------------

    def get_skill_tools(
        self, *, tool_executor: Optional[ToolExecutor] = None
    ) -> List[BaseTool]:
        """Wrap each registered skill as a :class:`SkillTool` (a :class:`BaseTool`).

        Parameters
        ----------
        tool_executor:
            Tool executor to use when running skill pipelines.  Falls back to
            the one set via :meth:`set_tool_executor` if not provided here.

        Returns
        -------
        list[BaseTool]
            One :class:`SkillTool` per registered skill.
        """
        executor = tool_executor or self._tool_executor
        tools: List[BaseTool] = []

        for manifest in self._skills.values():
            real_executor = executor or _NullToolExecutor()
            skill_exec = SkillExecutor(real_executor, bus=self._bus)

            # Wire sub-skill resolver so nested skill_name steps can delegate back
            skill_exec.set_skill_resolver(self._make_resolver())

            skill_tool = SkillTool(manifest, skill_exec, skill_manager=self)
            tools.append(skill_tool)

        return tools

    def _make_resolver(self):
        """Return a resolver callback that delegates sub-skill execution."""

        def _resolver(name: str, context: Dict[str, Any]) -> SkillResult:
            manifest = self.resolve(name)
            skill_exec = SkillExecutor(
                self._tool_executor or _NullToolExecutor(),
                bus=self._bus,
            )
            skill_exec.set_skill_resolver(_resolver)
            return skill_exec.run(manifest, initial_context=context)

        return _resolver

    # ------------------------------------------------------------------
    # Catalog
    # ------------------------------------------------------------------

    def get_catalog_xml(self) -> str:
        """Generate an ``<available_skills>`` XML catalog.

        Skills with ``disable_model_invocation=True`` are excluded so that
        internal or automation-only skills are not surfaced to the model.
        """
        lines: List[str] = ["<available_skills>"]

        for manifest in self._skills.values():
            if manifest.disable_model_invocation:
                continue
            escaped_name = html.escape(manifest.name)
            escaped_desc = html.escape(manifest.description or manifest.name)
            lines.append(
                f"  <skill name={escaped_name!r} description={escaped_desc!r} />"
            )

        lines.append("</available_skills>")
        return "\n".join(lines)

    def get_few_shot_examples(self) -> List[str]:
        """Return formatted few-shot example strings ready for system prompt.

        Pulls from ``manifest.metadata.openjarvis.few_shot`` for every
        registered skill.  Returns one formatted string per example.
        """
        examples: List[str] = []
        for name, manifest in self._skills.items():
            oj = manifest.metadata.get("openjarvis", {}) if manifest.metadata else {}
            few_shot = oj.get("few_shot", []) or []
            for ex in few_shot:
                if not isinstance(ex, dict):
                    continue
                inp = str(ex.get("input", ""))
                out = str(ex.get("output", ""))
                if inp or out:
                    examples.append(f"### {name}\nInput: {inp}\nOutput: {out}")
        return examples

    # ------------------------------------------------------------------
    # Trace-driven skill discovery (Plan 2A)
    # ------------------------------------------------------------------

    def discover_from_traces(
        self,
        trace_store: Any,
        *,
        min_frequency: int = 3,
        min_outcome: float = 0.5,
        output_dir: Optional[Path] = None,
    ) -> List[Dict[str, Any]]:
        """Mine the trace store for recurring tool sequences.

        For each recurring sequence found by :class:`SkillDiscovery`, write
        a TOML skill manifest into *output_dir* (default
        ``~/.openjarvis/skills/discovered/``).  Returns a list of dicts with
        ``name`` and ``path`` for each manifest written.

        Names are normalized to spec-compliant kebab-case (lowercase with
        hyphens, no underscores) so the resulting manifests load cleanly
        through the discovery walker.
        """
        from openjarvis.learning.agents.skill_discovery import SkillDiscovery

        traces = trace_store.list_traces(limit=10000)
        discovery = SkillDiscovery(
            min_frequency=min_frequency,
            min_outcome=min_outcome,
        )
        discovered = discovery.analyze_traces(traces)

        if output_dir is None:
            output_dir = Path("~/.openjarvis/skills/discovered/").expanduser()
        output_dir = Path(output_dir).expanduser()
        output_dir.mkdir(parents=True, exist_ok=True)

        written: List[Dict[str, Any]] = []
        for skill in discovered:
            name = self._normalize_skill_name(skill.name)
            skill_subdir = output_dir / name
            skill_subdir.mkdir(parents=True, exist_ok=True)
            toml_path = skill_subdir / "skill.toml"
            toml_path.write_text(
                self._serialize_discovered_skill(name, skill),
                encoding="utf-8",
            )
            written.append({"name": name, "path": str(toml_path)})

        return written

    @staticmethod
    def _normalize_skill_name(raw_name: str) -> str:
        """Convert an arbitrary discovered name to a spec-compliant kebab name.

        - Lowercase
        - Replace underscores and whitespace with hyphens
        - Collapse runs of hyphens
        - Strip leading/trailing hyphens
        """
        import re

        normalized = raw_name.lower()
        normalized = re.sub(r"[_\s]+", "-", normalized)
        normalized = re.sub(r"-+", "-", normalized)
        normalized = normalized.strip("-")
        if not normalized:
            normalized = "discovered-skill"
        return normalized

    @staticmethod
    def _serialize_discovered_skill(name: str, skill: Any) -> str:
        """Serialize a DiscoveredSkill into a spec-compliant skill.toml."""
        lines: List[str] = ["[skill]"]
        lines.append(f'name = "{name}"')
        lines.append('version = "0.1.0"')
        # Truncate description to spec max 1024 chars
        description = (skill.description or f"Discovered skill: {name}")[:1024]
        # Escape backslashes and double quotes for basic TOML strings
        description = description.replace("\\", "\\\\").replace('"', '\\"')
        lines.append(f'description = "{description}"')
        lines.append('author = "openjarvis (auto-discovered)"')
        lines.append('tags = ["auto-discovered"]')
        lines.append("")

        for tool_name in skill.tool_sequence:
            lines.append("[[skill.steps]]")
            lines.append(f'tool_name = "{tool_name}"')
            lines.append('arguments_template = "{}"')
            lines.append('output_key = ""')
            lines.append("")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    def execute(
        self,
        name: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> SkillResult:
        """Resolve and execute a skill by name.

        Parameters
        ----------
        name:
            Skill name to execute.
        context:
            Initial context dict passed to the executor.

        Returns
        -------
        SkillResult
        """
        manifest = self.resolve(name)
        executor = SkillExecutor(
            self._tool_executor or _NullToolExecutor(),
            bus=self._bus,
        )
        executor.set_skill_resolver(self._make_resolver())
        return executor.run(manifest, initial_context=context)

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------

    def set_tool_executor(self, tool_executor: ToolExecutor) -> None:
        """Attach a :class:`ToolExecutor` for running tool steps in skill pipelines."""
        self._tool_executor = tool_executor

    # ------------------------------------------------------------------
    # Lifecycle stubs (not yet implemented)
    # ------------------------------------------------------------------

    def install(self, source: Any, *, verify: bool = True) -> None:
        """Install a skill from a remote source.  Not yet implemented."""
        raise NotImplementedError("Skill installation not yet implemented")

    def remove(self, name: Any) -> None:
        """Remove a skill by name.  Not yet implemented."""
        raise NotImplementedError("Skill removal not yet implemented")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


class _NullToolExecutor(ToolExecutor):
    """A no-op ToolExecutor used when no real executor is available.

    Allows SkillTool/SkillExecutor construction to succeed even before a
    real tool executor is wired in; any actual tool call will produce an
    error ToolResult rather than raising.
    """

    def __init__(self) -> None:
        super().__init__(tools=[], bus=None)


__all__ = ["SkillManager"]
