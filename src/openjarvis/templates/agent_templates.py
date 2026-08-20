"""Agent template loader — load pre-configured agent manifests from TOML files."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib  # type: ignore[no-redef]

from openjarvis.core.paths import get_config_dir


@dataclass(slots=True)
class AgentTemplate:
    """A pre-configured agent manifest loaded from a TOML template."""

    name: str
    description: str = ""
    system_prompt: str = ""
    agent_type: str = "simple"
    tools: List[str] = field(default_factory=list)
    max_turns: int = 10
    temperature: float = 0.7


def load_template(path: str | Path) -> AgentTemplate:
    """Load an agent template from a TOML file.

    Expected format::

        [template]
        name = "code-reviewer"
        description = "Reviews code for bugs, style, and best practices"

        [agent]
        type = "native_react"
        max_turns = 8
        temperature = 0.3
        tools = ["file_read", "think"]
        system_prompt = \"\"\"You are a code reviewer...\"\"\"

    Raises:
        FileNotFoundError: If *path* does not exist.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Template file not found: {path}")

    with open(path, "rb") as fh:
        data = tomllib.load(fh)

    template_data: Dict = data.get("template", {})
    agent_data: Dict = data.get("agent", {})

    return AgentTemplate(
        name=template_data.get("name", path.stem),
        description=template_data.get("description", ""),
        system_prompt=agent_data.get("system_prompt", ""),
        agent_type=agent_data.get("type", "simple"),
        tools=agent_data.get("tools", []),
        max_turns=agent_data.get("max_turns", 10),
        temperature=agent_data.get("temperature", 0.7),
    )


def _builtin_templates_dir() -> Path:
    """Return the path to the built-in templates shipped with the package."""
    return Path(__file__).resolve().parent / "data"


def _user_templates_dir() -> Path:
    """Return the path to user-defined templates (~/.openjarvis/templates/agents/)."""
    return get_config_dir() / "templates" / "agents"


def discover_templates(
    extra_dirs: Optional[List[str | Path]] = None,
) -> List[AgentTemplate]:
    """Discover and load all agent templates from known directories.

    Search order:
    1. Built-in templates shipped with the package (``templates/data/``).
    2. User templates at ``~/.openjarvis/templates/agents/``.
    3. Any additional directories supplied via *extra_dirs*.

    Returns a list of :class:`AgentTemplate` instances sorted by name.
    """
    dirs: List[Path] = [_builtin_templates_dir(), _user_templates_dir()]
    if extra_dirs:
        dirs.extend(Path(d) for d in extra_dirs)

    seen: Dict[str, AgentTemplate] = {}
    for directory in dirs:
        if not directory.is_dir():
            continue
        for toml_path in sorted(directory.glob("*.toml")):
            tpl = load_template(toml_path)
            # Later directories override earlier ones (user overrides builtin).
            seen[tpl.name] = tpl

    return sorted(seen.values(), key=lambda t: t.name)


__all__ = ["AgentTemplate", "discover_templates", "load_template"]
