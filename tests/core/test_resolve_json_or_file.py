"""Tests for resolve_json_or_file in openjarvis.core.config."""

import json
from pathlib import Path

import pytest

from openjarvis.core.config import resolve_json_or_file


class TestResolveJsonOrFile:
    """Unit tests for resolve_json_or_file."""

    def test_empty_string(self, tmp_path: Path) -> None:
        assert resolve_json_or_file("", tmp_path) is None

    def test_whitespace_only(self, tmp_path: Path) -> None:
        assert resolve_json_or_file("   ", tmp_path) is None

    def test_inline_json_array(self, tmp_path: Path) -> None:
        assert resolve_json_or_file("[1, 2, 3]", tmp_path) == [1, 2, 3]

    def test_inline_json_object(self, tmp_path: Path) -> None:
        assert resolve_json_or_file('{"key": "val"}', tmp_path) == {"key": "val"}

    def test_inline_json_with_leading_whitespace(self, tmp_path: Path) -> None:
        assert resolve_json_or_file("  [1]", tmp_path) == [1]

    def test_file_path_relative(self, tmp_path: Path) -> None:
        sub = tmp_path / "sub"
        sub.mkdir()
        data_file = sub / "data.json"
        data_file.write_text('[{"a": 1}]', encoding="utf-8")

        result = resolve_json_or_file("sub/data.json", tmp_path)
        assert result == [{"a": 1}]

    def test_file_path_absolute(self, tmp_path: Path) -> None:
        # Use a subdirectory as a separate location from config_dir
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        data_dir = tmp_path / "external"
        data_dir.mkdir()
        data_file = data_dir / "servers.json"
        data_file.write_text('{"url": "http://localhost"}', encoding="utf-8")

        result = resolve_json_or_file(str(data_file), config_dir)
        assert result == {"url": "http://localhost"}

    def test_directory_traversal_blocked(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="outside"):
            resolve_json_or_file("../../etc/passwd", tmp_path)

    def test_directory_traversal_dot_segments(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="outside"):
            resolve_json_or_file("sub/../../etc/passwd", tmp_path)

    def test_file_not_found(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            resolve_json_or_file("nonexistent.json", tmp_path)

    def test_invalid_json_in_file(self, tmp_path: Path) -> None:
        bad_file = tmp_path / "broken.json"
        bad_file.write_text("{broken json", encoding="utf-8")

        with pytest.raises(json.JSONDecodeError):
            resolve_json_or_file("broken.json", tmp_path)

    def test_absolute_path_outside_config_dir_allowed(self, tmp_path: Path) -> None:
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        other_dir = tmp_path / "other"
        other_dir.mkdir()
        data_file = other_dir / "data.json"
        data_file.write_text("[42]", encoding="utf-8")

        # Absolute paths bypass the traversal check
        result = resolve_json_or_file(str(data_file), config_dir)
        assert result == [42]
