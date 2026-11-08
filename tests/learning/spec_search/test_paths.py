"""Tests for friday_ai.learning.spec_search.storage.paths module."""

from __future__ import annotations

from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# resolve_spec_search_root
# ---------------------------------------------------------------------------


class TestResolveSpecSearchRoot:
    """Tests for resolve_spec_search_root()."""

    def test_default_is_under_home(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from friday_ai.learning.spec_search.storage import paths

        monkeypatch.delenv("FRIDAY_AI_HOME", raising=False)
        result = paths.resolve_spec_search_root()
        assert result == Path.home() / ".friday_ai" / "learning"

    def test_respects_friday_ai_home_env_var(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from friday_ai.learning.spec_search.storage import paths

        custom = tmp_path / "custom_oj"
        monkeypatch.setenv("FRIDAY_AI_HOME", str(custom))
        result = paths.resolve_spec_search_root()
        assert result == custom / "learning"

    def test_returns_absolute_path(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from friday_ai.learning.spec_search.storage import paths

        monkeypatch.setenv("FRIDAY_AI_HOME", str(tmp_path / "rel"))
        result = paths.resolve_spec_search_root()
        assert result.is_absolute()

    def test_rejects_path_inside_source_tree(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from friday_ai.learning.spec_search.storage import paths

        # Find the FridayAI source root by walking up from the paths module.
        source_root = paths._find_source_root()
        assert source_root is not None  # We must be running inside the repo.

        # Force FRIDAY_AI_HOME to point inside the source tree.
        monkeypatch.setenv("FRIDAY_AI_HOME", str(source_root / "junk_dir"))

        with pytest.raises(paths.ConfigurationError, match="inside the source tree"):
            paths.resolve_spec_search_root()

    def test_find_source_root_returns_repo_root(self) -> None:
        from friday_ai.learning.spec_search.storage import paths

        result = paths._find_source_root()
        assert result is not None
        assert (result / "pyproject.toml").exists()


# ---------------------------------------------------------------------------
# ensure_spec_search_dirs
# ---------------------------------------------------------------------------


class TestEnsureSpecSearchDirs:
    """Tests for ensure_spec_search_dirs()."""

    def test_creates_subdirs(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from friday_ai.learning.spec_search.storage import paths

        monkeypatch.setenv("FRIDAY_AI_HOME", str(tmp_path / "oj"))
        root = paths.ensure_spec_search_dirs()

        assert root.exists()
        assert (root / "sessions").exists()
        assert (root / "benchmarks").exists()
        assert (root / "benchmarks" / "reference_outputs").exists()
        assert (root / "pending_review").exists()

    def test_idempotent(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from friday_ai.learning.spec_search.storage import paths

        monkeypatch.setenv("FRIDAY_AI_HOME", str(tmp_path / "oj"))
        first = paths.ensure_spec_search_dirs()
        second = paths.ensure_spec_search_dirs()

        assert first == second
        assert first.exists()
