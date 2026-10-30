"""Tests for the apply_patch tool."""

from __future__ import annotations

import pytest

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

    @pytest.mark.parametrize(
        "alias_name,target_name", [("notes.txt", ".env"), (".env", "notes.txt")]
    )
    @pytest.mark.parametrize("explicit_path", [True, False])
    def test_blocks_symlink_alias_to_sensitive_file(
        self, tmp_path, alias_name, target_name, explicit_path
    ):
        sensitive = tmp_path / target_name
        sensitive.write_text("SECRET=foo\n", encoding="utf-8")
        alias = tmp_path / alias_name
        try:
            alias.symlink_to(sensitive)
        except OSError:
            pytest.skip("filesystem does not permit creating symlinks")
        patch = f"--- {alias}\n+++ {alias}\n@@ -1 +1 @@\n-SECRET=foo\n+SECRET=bar\n"

        result = ApplyPatchTool().execute(
            patch=patch, path=str(alias) if explicit_path else None
        )

        assert result.success is False
        assert "sensitive" in result.content.lower()
        assert sensitive.read_text(encoding="utf-8") == "SECRET=foo\n"
        assert not alias.with_suffix(alias.suffix + ".bak").exists()

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

    def test_create_new_file_from_dev_null_patch(self, tmp_path):
        new_file = tmp_path / "test_new_file.txt"
        patch = (
            "--- /dev/null\n"
            "+++ b/test_new_file.txt\n"
            "@@ -0,0 +1,2 @@\n"
            "+line one\n"
            "+line two\n"
        )
        tool = ApplyPatchTool()
        result = tool.execute(patch=patch, path=str(new_file))
        assert result.success is True
        assert new_file.exists()
        assert new_file.read_text(encoding="utf-8") == "line one\nline two\n"
        assert "backup_path" not in result.metadata

    def test_create_new_file_auto_detect_path_nested_dirs(self, tmp_path):
        nested_file = tmp_path / "sub" / "dir" / "created.txt"
        patch = (
            f"--- /dev/null\n+++ b/{nested_file}\n@@ -0,0 +1,1 @@\n+created content\n"
        )
        tool = ApplyPatchTool()
        result = tool.execute(patch=patch)
        assert result.success is True
        assert nested_file.exists()
        assert nested_file.read_text(encoding="utf-8") == "created content\n"

    def test_patch_empty_file_with_old_start_zero(self, tmp_path):
        empty_file = tmp_path / "empty.txt"
        empty_file.write_text("", encoding="utf-8")
        patch = (
            "--- a/empty.txt\n"
            "+++ b/empty.txt\n"
            "@@ -0,0 +1,2 @@\n"
            "+first line\n"
            "+second line\n"
        )
        tool = ApplyPatchTool()
        result = tool.execute(patch=patch, path=str(empty_file), backup=True)
        assert result.success is True
        assert empty_file.read_text(encoding="utf-8") == "first line\nsecond line\n"
        bak = tmp_path / "empty.txt.bak"
        assert bak.exists()
        assert bak.read_text(encoding="utf-8") == ""

    def test_create_file_crlf_line_endings(self, tmp_path):
        target = tmp_path / "crlf_new.txt"
        patch = (
            "--- /dev/null\r\n"
            "+++ b/crlf_new.txt\r\n"
            "@@ -0,0 +1,2 @@\r\n"
            "+line1\r\n"
            "+line2\r\n"
        )
        tool = ApplyPatchTool()
        result = tool.execute(patch=patch, path=str(target), backup=False)
        assert result.success is True
        with open(target, "rb") as f:
            raw_bytes = f.read()
        assert raw_bytes == b"line1\r\nline2\r\n"

    @pytest.mark.parametrize(
        "header",
        [
            "--- /dev/null\n",
            "--- a/dev/null\n",
            "--- /dev/null\t2026-01-01 00:00:00.000000000 +0000\n",
            "--- dev/null\n",
        ],
    )
    def test_create_new_file_dev_null_variants(self, tmp_path, header):
        f = tmp_path / "variant.txt"
        patch = f"{header}+++ b/variant.txt\n@@ -0,0 +1,1 @@\n+variant content\n"
        tool = ApplyPatchTool()
        result = tool.execute(patch=patch, path=str(f), backup=False)
        assert result.success is True
        assert f.read_text(encoding="utf-8") == "variant content\n"

    def test_create_sensitive_file_blocked(self, tmp_path):
        env_file = tmp_path / ".env"
        patch = "--- /dev/null\n+++ b/.env\n@@ -0,0 +1,1 @@\n+SECRET=123\n"
        tool = ApplyPatchTool()
        result = tool.execute(patch=patch, path=str(env_file))
        assert result.success is False
        assert "sensitive" in result.content.lower()
        assert not env_file.exists()
