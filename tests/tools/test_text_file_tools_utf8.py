"""Tools that persist MEMORY.md, USER.md and skill files must use UTF-8.

``Path.read_text()`` / ``write_text()`` without ``encoding=`` use the locale
codec, which is cp1252 on a default Windows install. The prompt builder reads
MEMORY.md and USER.md as UTF-8 and ``tomllib`` only parses UTF-8, so a file
written in another codec crashes the read or the load.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import tomllib

_READ_TEXT = Path.read_text
_WRITE_TEXT = Path.write_text

# U+65E5 U+672C is not encodable in cp1252; U+00E9 is, but as a single byte
# (E9) that is not valid UTF-8 on its own.
_JP = "日本"
_E = "é"


def _utf8(path: Path) -> str:
    """Decode as strict UTF-8, ignoring platform newline translation."""
    return path.read_bytes().decode("utf-8").replace("\r\n", "\n")


@pytest.fixture(autouse=True)
def _cp1252_locale(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make ``Path.read_text`` / ``write_text`` default to cp1252."""

    def read_text(path, encoding=None, errors=None, newline=None):
        return _READ_TEXT(path, encoding=encoding or "cp1252", errors=errors)

    def write_text(path, data, encoding=None, errors=None, newline=None):
        return _WRITE_TEXT(
            path, data, encoding=encoding or "cp1252", errors=errors, newline=newline
        )

    monkeypatch.setattr(Path, "read_text", read_text)
    monkeypatch.setattr(Path, "write_text", write_text)


def test_memory_manage_round_trips_utf8(tmp_path: Path) -> None:
    from openjarvis.tools.memory_manage import MemoryManageTool

    path = tmp_path / "MEMORY.md"
    path.write_bytes(f"- caf{_E} {_JP}\n".encode("utf-8"))
    tool = MemoryManageTool(memory_path=path)

    assert f"caf{_E} {_JP}" in tool.execute(action="read").content

    assert tool.execute(action="add", entry=f"pr{_E}f{_E}re le th{_E}").success
    text = _utf8(path)
    assert f"caf{_E} {_JP}" in text
    assert f"pr{_E}f{_E}re le th{_E}" in text

    assert tool.execute(action="update", entry=f"th{_E}", new_entry="eau").success
    assert f"pr{_E}f{_E}re le eau" in _utf8(path)

    assert tool.execute(action="remove", entry=f"pr{_E}f{_E}re").success
    assert f"pr{_E}f{_E}re" not in _utf8(path)


def test_user_profile_manage_round_trips_utf8(tmp_path: Path) -> None:
    from openjarvis.tools.user_profile_manage import UserProfileManageTool

    path = tmp_path / "USER.md"
    path.write_bytes(f"- Zo{_E} {_JP}\n".encode("utf-8"))
    tool = UserProfileManageTool(user_path=path)

    assert f"Zo{_E} {_JP}" in tool.execute(action="read").content

    assert tool.execute(action="add", entry=f"Ville: Montr{_E}al").success
    text = _utf8(path)
    assert f"Zo{_E} {_JP}" in text
    assert f"Montr{_E}al" in text

    assert tool.execute(
        action="update", entry=f"Montr{_E}al", new_entry=f"Qu{_E}bec"
    ).success
    assert f"Qu{_E}bec" in _utf8(path)

    assert tool.execute(action="remove", entry=f"Qu{_E}bec").success
    assert f"Qu{_E}bec" not in _utf8(path)


def test_skill_manage_writes_utf8_toml(tmp_path: Path) -> None:
    from openjarvis.tools.skill_manage import SkillManageTool

    tool = SkillManageTool(skills_dir=tmp_path)
    description = f"V{_E}rifier l'{_E}tat {_JP}"

    assert tool.execute(
        action="create",
        name=f"caf{_E}",
        description=description,
        steps=[{"tool_name": "http_request"}],
    ).success

    data = tomllib.loads(_utf8(tmp_path / f"caf{_E}.toml"))
    assert data["skill"]["description"] == description

    loaded = tool.execute(action="load", name=f"caf{_E}")
    assert loaded.success
    assert description in loaded.content


@pytest.mark.parametrize("kind", ["memory", "user"])
def test_legacy_invalid_utf8_is_not_truncated(tmp_path: Path, kind: str) -> None:
    from openjarvis.tools.memory_manage import MemoryManageTool
    from openjarvis.tools.user_profile_manage import UserProfileManageTool

    path = tmp_path / "legacy.md"
    original = b"- caf\xe9\n"
    path.write_bytes(original)
    tool = (
        MemoryManageTool(memory_path=path)
        if kind == "memory"
        else UserProfileManageTool(user_path=path)
    )
    with pytest.raises(UnicodeDecodeError):
        tool.execute(action="add", entry="New fact")
    assert path.read_bytes() == original
