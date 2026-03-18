from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def memory_file(tmp_path: Path) -> Path:
    p = tmp_path / "MEMORY.md"
    p.write_text("## Knowledge\n\n- User prefers dark mode\n")
    return p


def test_memory_read(memory_file: Path):
    from openjarvis.tools.memory_manage import MemoryManageTool

    tool = MemoryManageTool(memory_path=memory_file)
    result = tool.execute(action="read")
    assert "dark mode" in result.content


def test_memory_add(memory_file: Path):
    from openjarvis.tools.memory_manage import MemoryManageTool

    tool = MemoryManageTool(memory_path=memory_file)
    result = tool.execute(action="add", entry="User works at Acme Corp")
    assert result.success
    assert "Acme Corp" in memory_file.read_text()


def test_memory_remove(memory_file: Path):
    from openjarvis.tools.memory_manage import MemoryManageTool

    tool = MemoryManageTool(memory_path=memory_file)
    tool.execute(action="add", entry="temporary fact")
    result = tool.execute(action="remove", entry="temporary fact")
    assert result.success
    assert "temporary fact" not in memory_file.read_text()


def test_memory_create_if_missing(tmp_path: Path):
    from openjarvis.tools.memory_manage import MemoryManageTool

    path = tmp_path / "MEMORY.md"
    tool = MemoryManageTool(memory_path=path)
    result = tool.execute(action="add", entry="new fact")
    assert result.success
    assert path.exists()
    assert "new fact" in path.read_text()
