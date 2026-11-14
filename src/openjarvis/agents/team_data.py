"""Per-team memory, knowledge and persona-memory storage for managed agents.

Each team owns ``<agents db dir>/team-data/<team_id>/`` with its own
``memory.db``, ``knowledge.db`` and ``MEMORY.md``. Team-scoped agents never
receive the global memory backend or knowledge store. An agent removed from its
team gets a private ``team-data/_agents/<agent_id>/`` area until reassigned.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


@dataclass
class AgentDataScope:
    """Storage an agent may use for one turn."""

    memory_backend: Any = None
    knowledge_db_path: Optional[Path] = None
    memory_files_config: Any = None
    team_scoped: bool = False
    owned_backend: bool = False


def _checked_id(value: str) -> str:
    if not value or any(c not in "0123456789abcdef" for c in value):
        raise ValueError("Invalid team or agent ID")
    return value


def _team_data_root(manager: Any) -> Path:
    return Path(manager._db_path).parent / "team-data"


def team_data_dir(manager: Any, team_id: str) -> Path:
    return _team_data_root(manager) / _checked_id(team_id)


def _ensure_private_dir(manager: Any, *parts: str) -> Path:
    """Create team-data/<parts...> with every level owner-only (0700)."""
    path = _team_data_root(manager)
    for part in ("", *parts):
        path = path / part if part else path
        path.mkdir(exist_ok=True, mode=0o700)
        path.chmod(0o700)
    return path


def ensure_team_data_dir(manager: Any, team_id: str) -> Path:
    return _ensure_private_dir(manager, _checked_id(team_id))


def _create_memory_backend(app_config: Any, db_path: Path) -> Any:
    import openjarvis.tools.storage  # noqa: F401
    from openjarvis.core.registry import MemoryRegistry

    key = getattr(getattr(app_config, "memory", None), "default_backend", "sqlite")
    for candidate in dict.fromkeys((key, "sqlite")):
        if not MemoryRegistry.contains(candidate):
            continue
        try:
            return MemoryRegistry.create(candidate, db_path=str(db_path))
        except TypeError:
            continue  # Backend has no on-disk path; use sqlite for isolation.
    return None


def _agent_data_dir(manager: Any, agent_record: Any) -> Path:
    if agent_record.get("team_id"):
        return ensure_team_data_dir(manager, agent_record["team_id"])
    return _ensure_private_dir(manager, "_agents", _checked_id(agent_record["id"]))


def agent_memory_files_config(manager: Any, agent_record: Any, app_config: Any) -> Any:
    """Persona-file config for prompts, without opening a memory backend."""
    memory_files = getattr(app_config, "memory_files", None)
    if manager is None or not (
        agent_record.get("team_id") or agent_record.get("team_scoped")
    ):
        return memory_files
    path = _agent_data_dir(manager, agent_record) / "MEMORY.md"
    return _team_memory_files(memory_files, path)


def resolve_agent_data_scope(
    manager: Any,
    agent_record: Any,
    *,
    memory_backend: Any = None,
    knowledge_db_path: Any = None,
    app_config: Any = None,
) -> AgentDataScope:
    """Return global storage for legacy agents, team storage for team agents."""
    memory_files = getattr(app_config, "memory_files", None)
    team_id = agent_record.get("team_id")
    if manager is None or not (team_id or agent_record.get("team_scoped")):
        return AgentDataScope(
            memory_backend=memory_backend,
            knowledge_db_path=Path(knowledge_db_path) if knowledge_db_path else None,
            memory_files_config=memory_files,
        )

    path = _agent_data_dir(manager, agent_record)
    backend = None
    try:
        backend = _create_memory_backend(app_config, path / "memory.db")
    except Exception:
        logger.warning("Team memory backend unavailable", exc_info=True)
    return AgentDataScope(
        memory_backend=backend,
        knowledge_db_path=path / "knowledge.db",
        memory_files_config=_team_memory_files(memory_files, path / "MEMORY.md"),
        team_scoped=True,
        owned_backend=backend is not None,
    )


def _team_memory_files(config: Any, memory_path: Path) -> Any:
    """Keep the shared persona (SOUL/USER) but give the team its own MEMORY.md."""
    from openjarvis.core.config import MemoryFilesConfig
    from openjarvis.prompt.builder import SystemPromptBuilder

    resolved = SystemPromptBuilder._resolve_persona(config or MemoryFilesConfig())
    # persona_name is cleared so the builder does not re-resolve the global path.
    return replace(resolved, memory_path=str(memory_path), persona_name="")


__all__ = [
    "AgentDataScope",
    "agent_memory_files_config",
    "ensure_team_data_dir",
    "resolve_agent_data_scope",
    "team_data_dir",
]
