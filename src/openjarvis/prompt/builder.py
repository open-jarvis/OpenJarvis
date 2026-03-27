from __future__ import annotations

from pathlib import Path
from typing import List, Optional, Tuple

from openjarvis.core.config import MemoryFilesConfig, SystemPromptConfig


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
    ) -> None:
        self._agent_template = agent_template
        self._mf_config = memory_files_config or MemoryFilesConfig()
        self._sp_config = system_prompt_config or SystemPromptConfig()
        self._skill_index = skill_index or []
        self._session_context = session_context
        self._previous_state = previous_state
        self._frozen_prefix: Optional[str] = None

    def build(self) -> str:
        if self._frozen_prefix is None:
            self._frozen_prefix = self._build_frozen_prefix()
        parts = [self._frozen_prefix]
        if self._session_context:
            parts.append(f"\n\n## Session Context\n\n{self._session_context}")
        if self._previous_state:
            parts.append(f"\n\n## Previous State\n\n{self._previous_state}")
        return "".join(parts)

    def _build_frozen_prefix(self) -> str:
        sections: list[str] = []
        sections.append(self._agent_template)
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
        if self._skill_index:
            skill_lines = []
            for name, desc in self._skill_index:
                truncated = desc[: self._sp_config.skill_desc_max_chars]
                if len(desc) > self._sp_config.skill_desc_max_chars:
                    truncated = truncated[:-3] + "..."
                skill_lines.append(f"- **{name}**: {truncated}")
            sections.append("## Available Skills\n\n" + "\n".join(skill_lines))
        return "\n\n".join(sections)

    def _load_file(self, path_str: str, max_chars: int) -> str:
        path = Path(path_str).expanduser()
        if not path.exists():
            return ""
        content = path.read_text()
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
