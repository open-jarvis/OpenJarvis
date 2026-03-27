"""Operator loader — load operator manifests from TOML files."""

from __future__ import annotations

from pathlib import Path

from openjarvis.operators.types import OperatorManifest

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib  # type: ignore[no-redef]


def load_operator(path: str | Path) -> OperatorManifest:
    """Load an operator manifest from a TOML file.

    Supports inline ``system_prompt`` or external ``system_prompt_path``
    (resolved relative to the TOML file).
    """
    path = Path(path)
    with open(path, "rb") as fh:
        data = tomllib.load(fh)

    op_data = data.get("operator", {})

    # Resolve schedule sub-table
    schedule = op_data.get("schedule", {})
    schedule_type = schedule.get("type", op_data.get("schedule_type", "interval"))
    schedule_value = schedule.get("value", op_data.get("schedule_value", "300"))

    # Resolve agent sub-table
    agent_data = op_data.get("agent", {})
    tools = agent_data.get("tools", op_data.get("tools", []))
    max_turns = agent_data.get("max_turns", op_data.get("max_turns", 20))
    temperature = agent_data.get("temperature", op_data.get("temperature", 0.3))
    system_prompt = agent_data.get("system_prompt", op_data.get("system_prompt", ""))
    system_prompt_path = agent_data.get(
        "system_prompt_path",
        op_data.get("system_prompt_path", ""),
    )

    # Load external system prompt if specified and inline is empty
    if not system_prompt and system_prompt_path:
        prompt_path = Path(system_prompt_path)
        if not prompt_path.is_absolute():
            prompt_path = path.parent / prompt_path
        if prompt_path.exists():
            system_prompt = prompt_path.read_text(encoding="utf-8")

    return OperatorManifest(
        id=op_data.get("id", path.stem),
        name=op_data.get("name", path.stem),
        version=op_data.get("version", "0.1.0"),
        description=op_data.get("description", ""),
        author=op_data.get("author", ""),
        tools=tools,
        system_prompt=system_prompt,
        system_prompt_path=system_prompt_path,
        max_turns=max_turns,
        temperature=temperature,
        schedule_type=schedule_type,
        schedule_value=str(schedule_value),
        metrics=op_data.get("metrics", []),
        required_capabilities=op_data.get("required_capabilities", []),
        settings=op_data.get("settings", {}),
        metadata=op_data.get("metadata", {}),
    )


__all__ = ["load_operator"]
