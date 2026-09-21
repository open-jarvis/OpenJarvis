"""Re-register components cleared by the root autouse _clean_registries
fixture, and seed the test skills these live tests expect, for tests in
this directory that construct a real SystemBuilder against a live
inference engine (see tests/skills/test_integration_live.py).
"""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _register_native_openhands() -> None:
    from openjarvis.agents.native_openhands import NativeOpenHandsAgent
    from openjarvis.core.registry import AgentRegistry

    if not AgentRegistry.contains("native_openhands"):
        AgentRegistry.register("native_openhands")(NativeOpenHandsAgent)


@pytest.fixture(autouse=True)
def _register_simple_agent() -> None:
    # Under the isolated test OPENJARVIS_HOME (no config.toml present),
    # config.agent.default_agent falls back to "simple" rather than a
    # developer's configured default -- SystemBuilder().build() with no
    # explicit .agent(...) call resolves to it. Same re-registration
    # pattern as native_openhands above.
    from openjarvis.agents.simple import SimpleAgent
    from openjarvis.core.registry import AgentRegistry

    if not AgentRegistry.contains("simple"):
        AgentRegistry.register("simple")(SimpleAgent)


@pytest.fixture(autouse=True)
def _register_ollama_engine() -> None:
    # Live skill-integration tests build against engine("ollama") without
    # an explicit EngineRegistry registration. Re-register it here, the
    # same way _register_native_openhands re-registers the default agent
    # above -- the root _clean_registries autouse fixture clears
    # EngineRegistry before every test, and Python only runs
    # @EngineRegistry.register()'s module-level decorator once per
    # process (module imports are cached), so nothing else repopulates
    # it for a later test in the same session.
    from openjarvis.core.registry import EngineRegistry
    from openjarvis.engine.ollama import OllamaEngine

    if not EngineRegistry.contains("ollama"):
        EngineRegistry.register("ollama")(OllamaEngine)


_SKILL_FILES = {
    "research-and-summarize/skill.toml": """[skill]
name = "research-and-summarize"
version = "0.1.0"
description = "Search the web and summarize the results"
author = "openjarvis"

[[skill.steps]]
tool_name = "web_search"
arguments_template = '{"query": "{query}"}'
output_key = "search_results"

[[skill.steps]]
tool_name = "think"
arguments_template = '{"thought": "Summarize: {search_results}"}'
output_key = "summary"
""",
    "code-explainer/SKILL.md": """---
name: code-explainer
description: Explains a block of code line by line in plain language.
---

# Code Explainer

Given a code snippet, explain what it does line by line, in plain language,
regardless of the programming language it is written in. Call out any
non-obvious logic, and note potential bugs or edge cases.
""",
    "math-solver/SKILL.md": """---
name: math-solver
description: Solves math problems step by step and shows the work.
---

# Math Solver

Given a math problem, solve it step by step, showing the reasoning and
intermediate results, and state the final numeric answer clearly at the end.
""",
}


@pytest.fixture(autouse=True)
def _seed_test_skills() -> None:
    # SystemBuilder().build() discovers skills from
    # config.skills.skills_dir, which resolves under the session's
    # isolated OPENJARVIS_HOME (see the root conftest.py's _TEST_HOME,
    # added for #787) -- not a developer's real ~/.openjarvis. Seed the
    # same fixtures there so SystemBuilder's own discovery finds them,
    # matching what the hardcoded ~/.openjarvis/skills/ paths in this
    # directory's other tests already assume are installed.
    from openjarvis.core.config import load_config

    skills_dir = Path(load_config().skills.skills_dir).expanduser()
    for rel_path, content in _SKILL_FILES.items():
        target = skills_dir / rel_path
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
