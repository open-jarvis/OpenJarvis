"""`[security] allowed_dirs` is the default directory allow-list for file tools."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from openjarvis.core.config import JarvisConfig, load_config
from openjarvis.tools._paths import resolve_allowed_dirs
from openjarvis.tools.file_read import FileReadTool
from openjarvis.tools.file_write import FileWriteTool


def test_explicit_argument_wins(tmp_path: Path) -> None:
    assert resolve_allowed_dirs([str(tmp_path)]) == [str(tmp_path)]


def test_explicit_empty_list_does_not_load_ambient_config(monkeypatch):
    monkeypatch.setattr(
        "openjarvis.core.config.load_config",
        Mock(side_effect=AssertionError("explicit policy must win")),
    )
    assert resolve_allowed_dirs([]) == []


@pytest.mark.parametrize("tool_class", [FileReadTool, FileWriteTool])
@pytest.mark.parametrize("invalid", ["/tmp/allowed", [""], [None], {"/": True}, None])
def test_invalid_directory_config_never_creates_an_unrestricted_tool(
    monkeypatch, tool_class, invalid
):
    cfg = JarvisConfig()
    cfg.security.allowed_dirs = invalid
    monkeypatch.setattr("openjarvis.core.config.load_config", lambda: cfg)
    with pytest.raises(ValueError, match="allowed_dirs"):
        tool_class()


@pytest.mark.parametrize("tool_class", [FileReadTool, FileWriteTool])
def test_unreadable_config_does_not_remove_directory_restrictions(
    monkeypatch, tool_class
):
    monkeypatch.setattr(
        "openjarvis.core.config.load_config",
        Mock(side_effect=PermissionError("configuration unavailable")),
    )
    with pytest.raises(PermissionError):
        tool_class()


def test_scalar_toml_policy_is_rejected_instead_of_allowing_root(tmp_path, monkeypatch):
    config_path = tmp_path / "config.toml"
    config_path.write_text('[security]\nallowed_dirs = "/tmp/allowed"\n')
    monkeypatch.setenv("OPENJARVIS_CONFIG", str(config_path))
    with pytest.raises(ValueError, match="allowed_dirs"):
        FileReadTool()


def test_config_default_is_empty() -> None:
    assert JarvisConfig().security.allowed_dirs == []


def test_config_allowed_dirs_restricts_file_read(tmp_path, monkeypatch) -> None:
    inside = tmp_path / "ok"
    inside.mkdir()
    (inside / "a.txt").write_text("inside")
    outside = tmp_path / "outside.txt"
    outside.write_text("outside")

    cfg = JarvisConfig()
    cfg.security.allowed_dirs = [str(inside)]
    monkeypatch.setattr("openjarvis.core.config.load_config", lambda *a, **k: cfg)

    tool = FileReadTool()
    assert tool.execute(path=str(inside / "a.txt")).success
    assert not tool.execute(path=str(outside)).success


def test_config_allowed_dirs_restricts_file_write(tmp_path, monkeypatch) -> None:
    inside = tmp_path / "ok"
    inside.mkdir()
    cfg = JarvisConfig()
    cfg.security.allowed_dirs = [str(inside)]
    monkeypatch.setattr("openjarvis.core.config.load_config", lambda *a, **k: cfg)

    tool = FileWriteTool()
    assert tool.execute(path=str(inside / "a.txt"), content="x").success
    assert not tool.execute(path=str(tmp_path / "b.txt"), content="x").success


def test_relative_path_resolves_inside_first_allowed_dir(tmp_path: Path) -> None:
    box = tmp_path / "box"
    box.mkdir()
    write = FileWriteTool(allowed_dirs=[str(box)])
    assert write.execute(path="n.txt", content="hi").success
    assert (box / "n.txt").read_text() == "hi"
    read = FileReadTool(allowed_dirs=[str(box)])
    assert read.execute(path="n.txt").content == "hi"


@pytest.mark.parametrize("entry_point", ["cli_sdk", "system", "orchestrator", "mcp"])
def test_active_config_controls_tools_instead_of_ambient_config(
    tmp_path, monkeypatch, entry_point
):
    from openjarvis.core.registry import ToolRegistry

    inside = tmp_path / "allowed"
    inside.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("outside must stay intact")
    config_path = tmp_path / "explicit.toml"
    config_path.write_text(
        f'[security]\nallowed_dirs = ["{inside.as_posix()}"]\n'
        '[tools]\nenabled = "file_read,file_write"\n'
    )
    cfg = load_config(config_path)
    ambient = JarvisConfig()
    monkeypatch.setattr("openjarvis.core.config.load_config", lambda *a, **kw: ambient)
    ToolRegistry.register_value("file_read", FileReadTool)
    ToolRegistry.register_value("file_write", FileWriteTool)

    if entry_point == "cli_sdk":
        from openjarvis.cli.ask import _build_tools

        tools = _build_tools(["file_read", "file_write"], cfg, None, "")
    elif entry_point == "system":
        from openjarvis.system.builder import SystemBuilder

        tools = SystemBuilder(config=cfg)._resolve_tools(cfg, None, "", None)
    elif entry_point == "orchestrator":
        from openjarvis.system.orchestrator import QueryOrchestrator

        system = SimpleNamespace(config=cfg, memory_backend=None, engine=None, model="")
        tools = QueryOrchestrator(system)._build_tools(["file_read", "file_write"])
    else:
        from openjarvis.mcp.server import MCPServer

        tools = MCPServer(allowed_dirs=cfg.security.allowed_dirs).get_tools()

    file_tools = {tool.spec.name: tool for tool in tools}
    read, write = file_tools["file_read"], file_tools["file_write"]
    assert write.execute(path="note.txt", content="allowed").success
    assert read.execute(path="note.txt").content == "allowed"
    assert not read.execute(path=str(outside)).success
    assert not write.execute(path=str(outside), content="blocked").success
    assert outside.read_text() == "outside must stay intact"


@pytest.mark.parametrize("entry_point", ["cli_sdk", "system", "orchestrator"])
def test_invalid_active_policy_cannot_fall_back_to_valid_ambient_config(
    monkeypatch, entry_point
):
    from openjarvis.core.registry import ToolRegistry

    cfg = JarvisConfig()
    cfg.security.allowed_dirs = None
    cfg.tools.enabled = "file_read,file_write"
    ambient = JarvisConfig()
    monkeypatch.setattr("openjarvis.core.config.load_config", lambda: ambient)
    ToolRegistry.register_value("file_read", FileReadTool)
    ToolRegistry.register_value("file_write", FileWriteTool)
    if entry_point == "cli_sdk":
        from openjarvis.cli.ask import _build_tools

        with pytest.raises(ValueError, match="allowed_dirs"):
            _build_tools(["file_read", "file_write"], cfg, None, "")
    elif entry_point == "system":
        from openjarvis.system.builder import SystemBuilder

        with pytest.raises(ValueError, match="allowed_dirs"):
            SystemBuilder(config=cfg)._resolve_tools(cfg, None, "", None)
    else:
        from openjarvis.system.orchestrator import QueryOrchestrator

        system = SimpleNamespace(config=cfg, memory_backend=None, engine=None, model="")
        assert QueryOrchestrator(system)._build_tools(["file_read", "file_write"]) == []


def test_managed_route_constructor_uses_active_policy(tmp_path, monkeypatch):
    from openjarvis.server.agent_manager_routes import _instantiate_managed_tool

    cfg = JarvisConfig()
    cfg.security.allowed_dirs = [str(tmp_path / "allowed")]
    state = SimpleNamespace(config=cfg, memory_backend=object())
    monkeypatch.setattr("openjarvis.core.config.load_config", lambda: JarvisConfig())
    outside = tmp_path / "outside.txt"
    outside.write_text("must stay outside")
    tool = _instantiate_managed_tool(
        FileReadTool, "file_read", engine=None, model="", app_state=state
    )
    assert not tool.execute(path=str(outside)).success
    cfg.security.allowed_dirs = None
    with pytest.raises(ValueError, match="allowed_dirs"):
        _instantiate_managed_tool(
            FileReadTool, "file_read", engine=None, model="", app_state=state
        )


def test_traversal_and_symlinks_cannot_escape_configured_directory(tmp_path):
    inside = tmp_path / "allowed"
    inside.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    target = outside / "note.txt"
    target.write_text("keep")
    try:
        (inside / "link").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("Creating directory symlinks is not permitted on this host")
    read = FileReadTool(allowed_dirs=[str(inside)])
    write = FileWriteTool(allowed_dirs=[str(inside)])
    for path in ("../outside/note.txt", "link/note.txt"):
        assert not read.execute(path=path).success
        for mode in ("write", "append"):
            assert not write.execute(path=path, content="escape", mode=mode).success
    assert not write.execute(
        path="link/new/subdir/note.txt", content="escape", create_dirs=True
    ).success
    assert target.read_text() == "keep"
    assert not (outside / "new").exists()


def test_configured_home_directory_is_expanded(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    (tmp_path / "allowed").mkdir()
    write = FileWriteTool(allowed_dirs=["~/allowed"])
    assert write.execute(path="note.txt", content="home").success
    assert (tmp_path / "allowed" / "note.txt").read_text() == "home"
