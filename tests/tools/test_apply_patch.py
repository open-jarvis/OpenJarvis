"""Tests for the apply_patch tool."""

from __future__ import annotations

from openjarvis.tools.apply_patch import ApplyPatchTool


class TestApplyPatchTool:
    def test_spec(self):
        tool = ApplyPatchTool()
        assert tool.spec.name == "apply_patch"
        assert tool.spec.category == "filesystem"
        assert "file:write" in tool.spec.required_capabilities

    def test_no_patch_provided(self):
        tool = ApplyPatchTool()
        result = tool.execute(patch="")
        assert result.success is False
        assert "No patch provided" in result.content

    def test_simple_one_hunk_patch(self, tmp_path):
        f = tmp_path / "hello.txt"
        f.write_text("line1\nline2\nline3\n", encoding="utf-8")
        patch = (
            "--- a/hello.txt\n"
            "+++ b/hello.txt\n"
            "@@ -1,3 +1,3 @@\n"
            " line1\n"
            "-line2\n"
            "+line2_modified\n"
            " line3\n"
        )
        tool = ApplyPatchTool()
        result = tool.execute(patch=patch, path=str(f), backup=False)
        assert result.success is True
        assert result.metadata["hunks_applied"] == 1
        content = f.read_text(encoding="utf-8")
        assert "line2_modified" in content
        assert "line2\n" not in content

    def test_multi_hunk_patch(self, tmp_path):
        f = tmp_path / "multi.txt"
        f.write_text(
            "alpha\nbeta\ngamma\ndelta\nepsilon\nzeta\neta\ntheta\n",
            encoding="utf-8",
        )
        patch = (
            "--- a/multi.txt\n"
            "+++ b/multi.txt\n"
            "@@ -1,3 +1,3 @@\n"
            " alpha\n"
            "-beta\n"
            "+BETA\n"
            " gamma\n"
            "@@ -6,3 +6,3 @@\n"
            " zeta\n"
            "-eta\n"
            "+ETA\n"
            " theta\n"
        )
        tool = ApplyPatchTool()
        result = tool.execute(patch=patch, path=str(f), backup=False)
        assert result.success is True
        assert result.metadata["hunks_applied"] == 2
        content = f.read_text(encoding="utf-8")
        assert "BETA" in content
        assert "ETA" in content
        assert "beta" not in content
        lines = content.splitlines()
        assert "eta" not in lines

    def test_context_mismatch_error(self, tmp_path):
        f = tmp_path / "mismatch.txt"
        f.write_text("aaa\nbbb\nccc\n", encoding="utf-8")
        patch = (
            "--- a/mismatch.txt\n"
            "+++ b/mismatch.txt\n"
            "@@ -1,3 +1,3 @@\n"
            " aaa\n"
            "-WRONG_CONTENT\n"
            "+replaced\n"
            " ccc\n"
        )
        tool = ApplyPatchTool()
        result = tool.execute(patch=patch, path=str(f), backup=False)
        assert result.success is False
        assert "mismatch" in result.content.lower()

    def test_backup_creation(self, tmp_path):
        f = tmp_path / "backup_me.txt"
        f.write_text("original\ncontent\n", encoding="utf-8")
        patch = (
            "--- a/backup_me.txt\n"
            "+++ b/backup_me.txt\n"
            "@@ -1,2 +1,2 @@\n"
            " original\n"
            "-content\n"
            "+new_content\n"
        )
        tool = ApplyPatchTool()
        result = tool.execute(patch=patch, path=str(f), backup=True)
        assert result.success is True
        assert "backup_path" in result.metadata
        bak = tmp_path / "backup_me.txt.bak"
        assert bak.exists()
        assert bak.read_text(encoding="utf-8") == "original\ncontent\n"
        assert "new_content" in f.read_text(encoding="utf-8")

    def test_backup_disabled(self, tmp_path):
        f = tmp_path / "no_bak.txt"
        f.write_text("hello\nworld\n", encoding="utf-8")
        patch = (
            "--- a/no_bak.txt\n"
            "+++ b/no_bak.txt\n"
            "@@ -1,2 +1,2 @@\n"
            "-hello\n"
            "+goodbye\n"
            " world\n"
        )
        tool = ApplyPatchTool()
        result = tool.execute(patch=patch, path=str(f), backup=False)
        assert result.success is True
        assert "backup_path" not in result.metadata
        bak = tmp_path / "no_bak.txt.bak"
        assert not bak.exists()

    def test_blocks_sensitive_files(self, tmp_path):
        f = tmp_path / ".env"
        f.write_text("SECRET=foo\n", encoding="utf-8")
        patch = "--- a/.env\n+++ b/.env\n@@ -1 +1 @@\n-SECRET=foo\n+SECRET=bar\n"
        tool = ApplyPatchTool()
        result = tool.execute(patch=patch, path=str(f))
        assert result.success is False
        assert "sensitive" in result.content.lower()

    def test_auto_detect_path_from_patch_header(self, tmp_path):
        f = tmp_path / "auto.txt"
        f.write_text("one\ntwo\nthree\n", encoding="utf-8")
        patch = (
            f"--- a/auto.txt\n+++ b/{f}\n@@ -1,3 +1,3 @@\n one\n-two\n+TWO\n three\n"
        )
        tool = ApplyPatchTool()
        # No explicit path — should auto-detect from +++ header
        result = tool.execute(patch=patch, backup=False)
        assert result.success is True
        assert "TWO" in f.read_text(encoding="utf-8")

    def test_malformed_patch(self):
        tool = ApplyPatchTool()
        result = tool.execute(patch="this is not a patch at all")
        assert result.success is False
        lower = result.content.lower()
        assert "malformed" in lower or "no hunks" in lower

    def test_file_not_found(self):
        tool = ApplyPatchTool()
        patch = (
            "--- a/nonexistent.txt\n+++ b/nonexistent.txt\n@@ -1 +1 @@\n-old\n+new\n"
        )
        result = tool.execute(patch=patch, path="/nonexistent/path/file.txt")
        assert result.success is False
        assert "not found" in result.content.lower()

    def test_addition_only_hunk(self, tmp_path):
        f = tmp_path / "add_only.txt"
        f.write_text("first\nsecond\n", encoding="utf-8")
        patch = (
            "--- a/add_only.txt\n"
            "+++ b/add_only.txt\n"
            "@@ -1,2 +1,3 @@\n"
            " first\n"
            "+inserted\n"
            " second\n"
        )
        tool = ApplyPatchTool()
        result = tool.execute(patch=patch, path=str(f), backup=False)
        assert result.success is True
        content = f.read_text(encoding="utf-8")
        assert content == "first\ninserted\nsecond\n"

    def test_removal_only_hunk(self, tmp_path):
        f = tmp_path / "del_only.txt"
        f.write_text("keep\nremove_me\nkeep_too\n", encoding="utf-8")
        patch = (
            "--- a/del_only.txt\n"
            "+++ b/del_only.txt\n"
            "@@ -1,3 +1,2 @@\n"
            " keep\n"
            "-remove_me\n"
            " keep_too\n"
        )
        tool = ApplyPatchTool()
        result = tool.execute(patch=patch, path=str(f), backup=False)
        assert result.success is True
        content = f.read_text(encoding="utf-8")
        assert content == "keep\nkeep_too\n"
