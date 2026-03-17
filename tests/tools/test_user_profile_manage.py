from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def user_file(tmp_path: Path) -> Path:
    p = tmp_path / "USER.md"
    p.write_text("## User Profile\n\n- Name: Alice\n")
    return p


def test_user_read(user_file: Path):
    from openjarvis.tools.user_profile_manage import UserProfileManageTool

    tool = UserProfileManageTool(user_path=user_file)
    result = tool.execute(action="read")
    assert "Alice" in result.content


def test_user_add(user_file: Path):
    from openjarvis.tools.user_profile_manage import UserProfileManageTool

    tool = UserProfileManageTool(user_path=user_file)
    result = tool.execute(action="add", entry="Role: Engineer")
    assert result.success
    assert "Engineer" in user_file.read_text()


def test_user_update(user_file: Path):
    from openjarvis.tools.user_profile_manage import UserProfileManageTool

    tool = UserProfileManageTool(user_path=user_file)
    result = tool.execute(action="update", entry="Name: Alice", new_entry="Name: Bob")
    assert result.success
    assert "Bob" in user_file.read_text()
    assert "Alice" not in user_file.read_text()
