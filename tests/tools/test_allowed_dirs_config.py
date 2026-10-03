"""`[security] allowed_dirs` is the default directory allow-list for file tools."""

from __future__ import annotations

from pathlib import Path

from openjarvis.core.config import JarvisConfig
from openjarvis.tools._paths import resolve_allowed_dirs
from openjarvis.tools.file_read import FileReadTool
from openjarvis.tools.file_write import FileWriteTool


def test_explicit_argument_wins(tmp_path: Path) -> None:
    assert resolve_allowed_dirs([str(tmp_path)]) == [str(tmp_path)]


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
