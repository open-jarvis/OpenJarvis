"""Materialize a temp ``OPENJARVIS_HOME`` from TOML-resident overrides.

Both ``_eval_runner.py`` (step 6) and ``m3_hill_climb.py`` shadow the user's
real ``~/.openjarvis`` with a temp dir for distilled runs. The temp dir
contains only the override files declared under ``[[benchmarks]].overrides``
in the eval TOML, so the TOML is the only source of truth — no hidden
dependency on the user's filesystem.

Override layout in the eval TOML::

    [[benchmarks]]
    name = "..."
    agent = "..."

    [benchmarks.overrides.system_prompt]
    <agent_name> = "..."

    [benchmarks.overrides.few_shot]
    <agent_name> = [{ input = "...", output = "..." }, ...]

    [benchmarks.overrides.tool_descriptions]
    <tool_name> = "..."

These map to the paths the runtime loaders read::

    $OPENJARVIS_HOME/agents/<name>/system_prompt.md
    $OPENJARVIS_HOME/agents/<name>/few_shot.json
    $OPENJARVIS_HOME/tools/descriptions.toml
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

try:
    import tomllib  # type: ignore[import-not-found]
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # type: ignore[import-not-found,no-redef]


def render_tool_descriptions_toml(descs: dict[str, str]) -> str:
    """Match the single-line parser in tools/description_loader.py."""
    lines: list[str] = []
    for tool, desc in descs.items():
        single_line = " ".join(str(desc).split())
        lines.append(f"[{tool}]")
        lines.append(f'description = "{single_line}"')
        lines.append("")
    return "\n".join(lines)


def prepare_override_home(config_path: Path) -> Path | None:
    """Materialize a temp ``OPENJARVIS_HOME`` from a config TOML's overrides.

    Reads ``[[benchmarks]][0].overrides`` from ``config_path`` and writes the
    three override files into a fresh ``tempfile.mkdtemp`` directory.

    Returns the temp dir path, or ``None`` when the TOML has no overrides
    block. Caller is responsible for cleanup.
    """
    try:
        cfg = tomllib.loads(config_path.read_text())
    except (OSError, tomllib.TOMLDecodeError):
        return None
    benches = cfg.get("benchmarks") or []
    if not benches:
        return None
    overrides = benches[0].get("overrides") or {}
    if not overrides:
        return None

    home = Path(tempfile.mkdtemp(prefix="oj-eval-home-"))
    for agent_name, prompt in (overrides.get("system_prompt") or {}).items():
        p = home / "agents" / agent_name / "system_prompt.md"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(str(prompt), encoding="utf-8")
    for agent_name, fs in (overrides.get("few_shot") or {}).items():
        p = home / "agents" / agent_name / "few_shot.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(fs, indent=2), encoding="utf-8")
    descs = overrides.get("tool_descriptions") or {}
    if descs:
        p = home / "tools" / "descriptions.toml"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(render_tool_descriptions_toml(descs), encoding="utf-8")
    return home
