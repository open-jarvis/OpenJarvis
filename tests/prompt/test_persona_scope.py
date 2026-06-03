"""Tests for #380 per-invocation persona scope (_resolve_persona)."""

from pathlib import Path

import pytest

from openjarvis.core.config import MemoryFilesConfig
from openjarvis.prompt.builder import SystemPromptBuilder


def test_empty_persona_passes_through_global_defaults():
    mf = MemoryFilesConfig()
    out = SystemPromptBuilder._resolve_persona(mf)
    assert out.soul_path == mf.soul_path  # unchanged = backward compatible


def test_none_persona_disables_all_files():
    out = SystemPromptBuilder._resolve_persona(MemoryFilesConfig(persona_name="none"))
    assert out.soul_path == "" and out.memory_path == "" and out.user_path == ""


def test_named_persona_resolves_to_personas_dir():
    out = SystemPromptBuilder._resolve_persona(MemoryFilesConfig(persona_name="coder"))
    base = str(Path.home() / ".openjarvis" / "personas" / "coder")
    assert out.soul_path == f"{base}/SOUL.md"
    assert out.memory_path == f"{base}/MEMORY.md"
    assert out.user_path == f"{base}/USER.md"


@pytest.mark.parametrize("bad", ["../etc", "a/b", "..\\win", "/abs", "x/../y"])
def test_path_traversal_rejected(bad):
    with pytest.raises(ValueError):
        SystemPromptBuilder._resolve_persona(MemoryFilesConfig(persona_name=bad))
