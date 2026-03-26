"""Tests for the file_write tool."""

from __future__ import annotations

from openjarvis.tools.file_write import FileWriteTool


class TestFileWriteTool:
    def test_spec(self):
        tool = FileWriteTool()
        assert tool.spec.name == "file_write"
        assert tool.spec.category == "filesystem"
        assert "file:write" in tool.spec.required_capabilities

    def test_no_path(self):
        tool = FileWriteTool()
        result = tool.execute(path="", content="hello")
        assert result.success is False
        assert "No path" in result.content

    def test_no_content(self):
        tool = FileWriteTool()
        result = tool.execute(path="/tmp/test.txt")
        assert result.success is False
        assert "No content" in result.content

    def test_write_file(self, tmp_path):
        f = tmp_path / "test.txt"
        tool = FileWriteTool()
        result = tool.execute(path=str(f), content="hello world\n")
        assert result.success is True
        assert f.read_text(encoding="utf-8") == "hello world\n"
        assert result.metadata["size_bytes"] > 0
        assert result.metadata["path"] == str(f.resolve())

    def test_append_mode(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("line1\n", encoding="utf-8")
        tool = FileWriteTool()
        result = tool.execute(path=str(f), content="line2\n", mode="append")
        assert result.success is True
        assert f.read_text(encoding="utf-8") == "line1\nline2\n"

    def test_create_dirs(self, tmp_path):
        f = tmp_path / "sub" / "deep" / "test.txt"
        tool = FileWriteTool()
        result = tool.execute(
            path=str(f),
            content="nested",
            create_dirs=True,
        )
        assert result.success is True
        assert f.read_text(encoding="utf-8") == "nested"

    def test_create_dirs_false_missing_parent(self, tmp_path):
        f = tmp_path / "nonexistent" / "test.txt"
        tool = FileWriteTool()
        result = tool.execute(path=str(f), content="data")
        assert result.success is False
        assert "Parent directory does not exist" in result.content

    def test_blocks_env_file(self, tmp_path):
        f = tmp_path / ".env"
        tool = FileWriteTool()
        result = tool.execute(path=str(f), content="SECRET=foo")
        assert result.success is False
        assert "sensitive" in result.content.lower()

    def test_blocks_pem_file(self, tmp_path):
        f = tmp_path / "server.pem"
        tool = FileWriteTool()
        result = tool.execute(
            path=str(f),
            content="-----BEGIN CERTIFICATE-----",
        )
        assert result.success is False
        assert "sensitive" in result.content.lower()

    def test_blocks_credentials_json(self, tmp_path):
        f = tmp_path / "credentials.json"
        tool = FileWriteTool()
        result = tool.execute(path=str(f), content='{"token": "abc"}')
        assert result.success is False
        assert "sensitive" in result.content.lower()

    def test_allowed_dirs_blocks(self, tmp_path):
        f = tmp_path / "test.txt"
        tool = FileWriteTool(allowed_dirs=["/some/other/dir"])
        result = tool.execute(path=str(f), content="data")
        assert result.success is False
        assert "Access denied" in result.content

    def test_allowed_dirs_permits(self, tmp_path):
        f = tmp_path / "ok.txt"
        tool = FileWriteTool(allowed_dirs=[str(tmp_path)])
        result = tool.execute(path=str(f), content="ok data")
        assert result.success is True
        assert f.read_text(encoding="utf-8") == "ok data"

    def test_file_size_limit(self, tmp_path):
        f = tmp_path / "big.txt"
        # 10 MB + 1 byte exceeds the limit
        big_content = "x" * (10_485_761)
        tool = FileWriteTool()
        result = tool.execute(path=str(f), content=big_content)
        assert result.success is False
        assert "too large" in result.content.lower()

    def test_write_creates_new_file(self, tmp_path):
        f = tmp_path / "new_file.txt"
        assert not f.exists()
        tool = FileWriteTool()
        result = tool.execute(path=str(f), content="brand new")
        assert result.success is True
        assert f.exists()
        assert f.read_text(encoding="utf-8") == "brand new"

    def test_overwrite_existing_file(self, tmp_path):
        f = tmp_path / "existing.txt"
        f.write_text("old content", encoding="utf-8")
        tool = FileWriteTool()
        result = tool.execute(path=str(f), content="new content")
        assert result.success is True
        assert f.read_text(encoding="utf-8") == "new content"

    def test_invalid_mode(self, tmp_path):
        f = tmp_path / "test.txt"
        tool = FileWriteTool()
        result = tool.execute(
            path=str(f),
            content="data",
            mode="invalid",
        )
        assert result.success is False
        assert "Invalid mode" in result.content
