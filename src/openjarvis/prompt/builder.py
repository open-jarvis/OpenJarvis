from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List, Literal, Optional, Tuple

from openjarvis.core.config import MemoryFilesConfig, SystemPromptConfig
from openjarvis.core.paths import get_config_dir

PromptCacheSegment = Literal["frozen_prefix", "dynamic_suffix"]


@dataclass(frozen=True, slots=True)
class PromptSection:
    """Inspectable prompt section emitted by SystemPromptBuilder."""

    name: str
    content: str
    source: str
    cache_segment: PromptCacheSegment


class SystemPromptBuilder:
    """Assembles system prompts with frozen prefix for cache stability."""

    def __init__(
        self,
        agent_template: str,
        memory_files_config: Optional[MemoryFilesConfig] = None,
        system_prompt_config: Optional[SystemPromptConfig] = None,
        skill_index: Optional[List[Tuple[str, str]]] = None,
        session_context: Optional[str] = None,
        previous_state: Optional[str] = None,
        skill_catalog_xml: Optional[str] = None,
        skill_few_shot: Optional[List[str]] = None,
        skill_few_shot_examples: Optional[List[str]] = None,
    ) -> None:
        self._agent_template = agent_template
        _mf = memory_files_config or MemoryFilesConfig()
        self._mf_config = self._resolve_persona(_mf)
        self._sp_config = system_prompt_config or SystemPromptConfig()
        self._skill_index = skill_index or []
        self._session_context = session_context
        self._previous_state = previous_state
        self._skill_catalog_xml = skill_catalog_xml
        # Allow either name; skill_few_shot_examples is the Plan 2A canonical name.
        if skill_few_shot_examples is not None:
            self._skill_few_shot = list(skill_few_shot_examples)
        else:
            self._skill_few_shot = list(skill_few_shot or [])
        self._frozen_prefix: Optional[str] = None
        self._frozen_sections: Optional[list[PromptSection]] = None

    def build(self) -> str:
        if self._frozen_prefix is None:
            self._frozen_prefix = self._build_frozen_prefix()
        parts = [self._frozen_prefix]
        if self._session_context:
            parts.append(f"\n\n## Session Context\n\n{self._session_context}")
        if self._previous_state:
            parts.append(f"\n\n## Previous State\n\n{self._previous_state}")
        return "".join(parts)

    def sections(self) -> list[PromptSection]:
        """Return prompt sections with lightweight cache/debug metadata."""
        sections = [*self._get_frozen_sections()]
        if self._session_context:
            sections.append(
                PromptSection(
                    name="session_context",
                    content=f"## Session Context\n\n{self._session_context}",
                    source="session_context",
                    cache_segment="dynamic_suffix",
                )
            )
        if self._previous_state:
            sections.append(
                PromptSection(
                    name="previous_state",
                    content=f"## Previous State\n\n{self._previous_state}",
                    source="previous_state",
                    cache_segment="dynamic_suffix",
                )
            )
        return sections

    def _get_frozen_sections(self) -> list[PromptSection]:
        if self._frozen_sections is None:
            self._frozen_sections = self._build_frozen_sections()
        return self._frozen_sections

    def _persona_sections(self) -> list[str]:
        """The SOUL / MEMORY / USER sections (no agent template, no skills)."""
        sections: list[str] = []
        soul = self._load_file(
            self._mf_config.soul_path,
            self._sp_config.soul_max_chars,
        )
        if soul:
            sections.append(f"## Agent Persona\n\n{soul}")
        memory = self._load_file(
            self._mf_config.memory_path,
            self._sp_config.memory_max_chars,
        )
        if memory:
            sections.append(f"## Agent Memory\n\n{memory}")
        user = self._load_file(
            self._mf_config.user_path,
            self._sp_config.user_max_chars,
        )
        if user:
            sections.append(f"## User Profile\n\n{user}")
        return sections

    def persona_sections(self) -> str:
        """Just the SOUL / MEMORY / USER persona, joined.

        For agents that assemble their own system prompt (monitor_operative,
        operative) and want to *append* persona without letting the builder
        replace their specialized instructions (#376). Returns "" when no
        persona files are present.
        """
        return "\n\n".join(self._persona_sections())

    def _build_frozen_prefix(self) -> str:
        return "\n\n".join(section.content for section in self._get_frozen_sections())

    def _build_frozen_sections(self) -> list[PromptSection]:
        sections: list[PromptSection] = []
        # Config-driven persona prefix from [system_prompt] prefix (#401),
        # prepended ahead of the agent template so it leads the frozen prefix.
        if self._sp_config.prefix:
            sections.append(
                PromptSection(
                    name="prefix",
                    content=self._sp_config.prefix,
                    source="system_prompt.prefix",
                    cache_segment="frozen_prefix",
                )
            )
        if self._agent_template:
            sections.append(
                PromptSection(
                    name="agent_template",
                    content=self._agent_template,
                    source="agent_template",
                    cache_segment="frozen_prefix",
                )
            )
        sections.extend(self._persona_prompt_sections())
        # XML skill catalog (preferred over legacy markdown list)
        if self._skill_catalog_xml:
            sections.append(
                PromptSection(
                    name="skill_catalog",
                    content="## Available Skills\n\n" + self._skill_catalog_xml,
                    source="skill_catalog_xml",
                    cache_segment="frozen_prefix",
                )
            )
        elif self._skill_index:
            skill_lines = []
            for name, desc in self._skill_index:
                truncated = desc[: self._sp_config.skill_desc_max_chars]
                if len(desc) > self._sp_config.skill_desc_max_chars:
                    truncated = truncated[:-3] + "..."
                skill_lines.append(f"- **{name}**: {truncated}")
            sections.append(
                PromptSection(
                    name="skill_index",
                    content="## Available Skills\n\n" + "\n".join(skill_lines),
                    source="skill_index",
                    cache_segment="frozen_prefix",
                )
            )
        if self._skill_few_shot:
            examples = "\n\n".join(self._skill_few_shot)
            sections.append(
                PromptSection(
                    name="skill_examples",
                    content="## Skill Examples\n\n" + examples,
                    source="skill_few_shot_examples",
                    cache_segment="frozen_prefix",
                )
            )
        return sections

    def _persona_prompt_sections(self) -> list[PromptSection]:
        sections: list[PromptSection] = []
        self._append_file_section(
            sections=sections,
            name="soul",
            heading="Agent Persona",
            path_str=self._mf_config.soul_path,
            max_chars=self._sp_config.soul_max_chars,
        )
        self._append_file_section(
            sections=sections,
            name="memory",
            heading="Agent Memory",
            path_str=self._mf_config.memory_path,
            max_chars=self._sp_config.memory_max_chars,
        )
        self._append_file_section(
            sections=sections,
            name="user",
            heading="User Profile",
            path_str=self._mf_config.user_path,
            max_chars=self._sp_config.user_max_chars,
        )
        return sections

    def _append_file_section(
        self,
        sections: list[PromptSection],
        name: str,
        heading: str,
        path_str: str,
        max_chars: int,
    ) -> None:
        content = self._load_file(path_str, max_chars)
        if content:
            sections.append(
                PromptSection(
                    name=name,
                    content=f"## {heading}\n\n{content}",
                    source=str(Path(path_str).expanduser()),
                    cache_segment="frozen_prefix",
                )
            )

    def _load_file(self, path_str: str, max_chars: int) -> str:
        # An empty path means "no file" (e.g. the persona "none" opt-out, which
        # resolves to empty paths). Guard before Path("") — which becomes "." —
        # so reading it does not raise IsADirectoryError.
        if not path_str:
            return ""
        path = Path(path_str).expanduser()
        if not path.exists():
            return ""
        # Always read as UTF-8. On Windows, ``read_text()`` falls back to the
        # system code page (e.g. cp950 for zh-TW, cp932 for ja) and raises
        # ``UnicodeDecodeError`` on any non-ASCII persona content.
        content = path.read_text(encoding="utf-8")
        if len(content) <= max_chars:
            return content
        return self._truncate(content, max_chars)

    def _truncate(self, text: str, max_chars: int) -> str:
        if self._sp_config.truncation_strategy == "head_tail":
            head_size = int(max_chars * 0.7)
            tail_size = int(max_chars * 0.2)
            omitted = len(text) - head_size - tail_size
            return (
                text[:head_size]
                + f"\n\n[...truncated {omitted} chars...]\n\n"
                + text[-tail_size:]
            )
        return text[:max_chars] + "\n[...truncated...]"

    @staticmethod
    def _resolve_persona(mf: MemoryFilesConfig) -> MemoryFilesConfig:
        """Resolve persona_name to effective file paths.
        - "" (empty) -> use mf's existing paths (global default, unchanged)
        - "none"      -> empty paths (opt-out, no persona injected)
        - "<name>"    -> ~/.openjarvis/personas/<name>/{SOUL,MEMORY,USER}.md
        """
        if not mf.persona_name:
            return mf
        if mf.persona_name == "none":
            return MemoryFilesConfig(
                soul_path="",
                memory_path="",
                user_path="",
                nudge_interval=mf.nudge_interval,
            )
        name = mf.persona_name
        if ".." in name or "/" in name or "\\" in name or name.startswith("/"):
            raise ValueError(
                f"Invalid persona name {name!r}: must be a simple "
                "identifier (no path separators or '..')."
            )
        base = get_config_dir() / "personas" / name
        return MemoryFilesConfig(
            soul_path=str(base / "SOUL.md"),
            memory_path=str(base / "MEMORY.md"),
            user_path=str(base / "USER.md"),
            nudge_interval=mf.nudge_interval,
            persona_name=name,
        )
