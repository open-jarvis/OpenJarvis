"""Tests for the file_read tool."""

from __future__ import annotations

from openjarvis.tools.file_read import FileReadTool


class TestFileReadTool:
    def test_spec(self):
        tool = FileReadTool()
        assert tool.spec.name == "file_read"
        assert tool.spec.category == "filesystem"

    def test_no_path(self):
        tool = FileReadTool()
        result = tool.execute(path="")
        assert result.success is False

    def test_file_not_found(self):
        tool = FileReadTool()
        result = tool.execute(path="/nonexistent/file.txt")
        assert result.success is False
        assert "File not found" in result.content

    def test_read_file(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("hello world\nsecond line\n", encoding="utf-8")
        tool = FileReadTool()
        result = tool.execute(path=str(f))
        assert result.success is True
        assert "hello world" in result.content
        assert result.metadata["size_bytes"] > 0

    def test_max_lines(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("line1\nline2\nline3\nline4\n", encoding="utf-8")
        tool = FileReadTool()
        result = tool.execute(path=str(f), max_lines=2)
        assert result.success is True
        assert "line1" in result.content
        assert "line2" in result.content
        assert "line3" not in result.content

    def test_allowed_dirs_blocks(self, tmp_path):
        f = tmp_path / "secret.txt"
        f.write_text("secret data", encoding="utf-8")
        tool = FileReadTool(allowed_dirs=["/some/other/dir"])
        result = tool.execute(path=str(f))
        assert result.success is False
        assert "Access denied" in result.content

    def test_allowed_dirs_permits(self, tmp_path):
        f = tmp_path / "ok.txt"
        f.write_text("ok data", encoding="utf-8")
        tool = FileReadTool(allowed_dirs=[str(tmp_path)])
        result = tool.execute(path=str(f))
        assert result.success is True
        assert "ok data" in result.content

    def test_directory_lists(self, tmp_path):
        (tmp_path / "a.txt").write_text("x", encoding="utf-8")
        sub = tmp_path / "sub"
        sub.mkdir()
        tool = FileReadTool()
        result = tool.execute(path=str(tmp_path))
        assert result.success is True
        assert "a.txt" in result.content
        assert "sub/" in result.content
        assert result.metadata.get("is_directory") is True

    def test_directory_respects_allowed_dirs(self, tmp_path):
        sub = tmp_path / "inner"
        sub.mkdir()
        (sub / "f.txt").write_text("x", encoding="utf-8")
        tool = FileReadTool(allowed_dirs=[str(sub)])
        result = tool.execute(path=str(tmp_path))
        assert result.success is False
        assert "outside allowed" in result.content

    def test_directory_allowed_when_root_matches(self, tmp_path):
        sub = tmp_path / "inner"
        sub.mkdir()
        (sub / "f.txt").write_text("x", encoding="utf-8")
        tool = FileReadTool(allowed_dirs=[str(tmp_path)])
        result = tool.execute(path=str(sub))
        assert result.success is True
        assert "f.txt" in result.content

    def test_blocks_env_file(self, tmp_path):
        f = tmp_path / ".env"
        f.write_text("SECRET=foo", encoding="utf-8")
        tool = FileReadTool()
        result = tool.execute(path=str(f))
        assert result.success is False
        assert "sensitive" in result.content.lower()

    def test_blocks_pem_file(self, tmp_path):
        f = tmp_path / "server.pem"
        f.write_text("-----BEGIN CERTIFICATE-----", encoding="utf-8")
        tool = FileReadTool()
        result = tool.execute(path=str(f))
        assert result.success is False
        assert "sensitive" in result.content.lower()

    def test_blocks_credentials_json(self, tmp_path):
        f = tmp_path / "credentials.json"
        f.write_text('{"token": "abc"}', encoding="utf-8")
        tool = FileReadTool()
        result = tool.execute(path=str(f))
        assert result.success is False
        assert "sensitive" in result.content.lower()

    def test_allows_normal_py_files(self, tmp_path):
        f = tmp_path / "main.py"
        f.write_text("print('hello')", encoding="utf-8")
        tool = FileReadTool()
        result = tool.execute(path=str(f))
        assert result.success is True
