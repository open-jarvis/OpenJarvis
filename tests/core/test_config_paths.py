"""Tests for the env-aware OpenJarvis home-directory resolver (issue #462).

Covers the single-root consolidation: ``$OPENJARVIS_HOME`` >
``$XDG_DATA_HOME/openjarvis`` > ``~/.openjarvis``, backward compatibility
(no env => exactly ``~/.openjarvis``), and the source-tree rejection guard.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from openjarvis.core import paths


def _clear_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove every env var that influences home resolution."""
    for var in (
        "OPENJARVIS_HOME",
        "XDG_DATA_HOME",
        "XDG_CONFIG_HOME",
        "XDG_CACHE_HOME",
    ):
        monkeypatch.delenv(var, raising=False)


class TestGetConfigDir:
    """Precedence and backward compatibility of get_config_dir()."""

    def test_default_when_unset_is_legacy_dir(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Backward-compat: with nothing set, the resolved dir is exactly the
        # historical ~/.openjarvis so existing installs are untouched.
        _clear_env(monkeypatch)
        assert paths.get_config_dir() == (Path.home() / ".openjarvis").resolve()

    def test_respects_openjarvis_home(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _clear_env(monkeypatch)
        custom = tmp_path / "oj"
        monkeypatch.setenv("OPENJARVIS_HOME", str(custom))
        assert paths.get_config_dir() == custom.resolve()

    def test_respects_xdg_data_home(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _clear_env(monkeypatch)
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        # Single nested 'openjarvis' dir under XDG_DATA_HOME.
        assert paths.get_config_dir() == (tmp_path / "openjarvis").resolve()

    def test_openjarvis_home_wins_over_xdg(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _clear_env(monkeypatch)
        oj = tmp_path / "oj_wins"
        monkeypatch.setenv("OPENJARVIS_HOME", str(oj))
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg_loses"))
        assert paths.get_config_dir() == oj.resolve()

    def test_expands_user_in_openjarvis_home(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _clear_env(monkeypatch)
        monkeypatch.setenv("OPENJARVIS_HOME", "~/relocated-oj")
        assert paths.get_config_dir() == (Path.home() / "relocated-oj").resolve()

    def test_returns_absolute_path(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _clear_env(monkeypatch)
        monkeypatch.setenv("OPENJARVIS_HOME", str(tmp_path / "rel"))
        assert paths.get_config_dir().is_absolute()


class TestDerivedDirs:
    """config_path / data_dir / cache_dir all hang off the single root."""

    def test_config_path(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _clear_env(monkeypatch)
        monkeypatch.setenv("OPENJARVIS_HOME", str(tmp_path / "oj"))
        assert paths.get_config_path() == (tmp_path / "oj" / "config.toml").resolve()

    def test_data_dir_equals_config_dir(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _clear_env(monkeypatch)
        monkeypatch.setenv("OPENJARVIS_HOME", str(tmp_path / "oj"))
        assert paths.get_data_dir() == paths.get_config_dir()

    def test_cache_dir_is_nested_cache(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _clear_env(monkeypatch)
        monkeypatch.setenv("OPENJARVIS_HOME", str(tmp_path / "oj"))
        assert paths.get_cache_dir() == (tmp_path / "oj" / "cache").resolve()

    def test_cache_dir_under_xdg(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _clear_env(monkeypatch)
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        assert paths.get_cache_dir() == (tmp_path / "openjarvis" / "cache").resolve()


class TestSourceTreeRejection:
    """A home pointing inside the repo must fail loudly (REVIEW.md)."""

    def test_rejects_path_inside_source_tree(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _clear_env(monkeypatch)
        source_root = paths._find_source_root()
        assert source_root is not None  # We must be running inside the repo.
        monkeypatch.setenv("OPENJARVIS_HOME", str(source_root / "junk_dir"))
        with pytest.raises(paths.ConfigurationError, match="inside the source tree"):
            paths.get_config_dir()


class TestLegacyConstantsHonorEnv:
    """The legacy DEFAULT_CONFIG_* names route through the env-aware resolver.

    This is the exact split-brain bug from #462: the constant used to ignore
    OPENJARVIS_HOME entirely. The constant is resolved once at import (the
    install-script model, where the env is set before the process starts), and
    every instance-level default goes through ``get_config_dir()`` so it honors
    the override. ``DEFAULT_CONFIG_DIR`` stays a real attribute so existing
    tests can ``monkeypatch.setattr`` it.
    """

    def test_constant_matches_resolver_at_import(self) -> None:
        from openjarvis.core import config

        # The constant is the import-time resolution of the same function.
        assert config.DEFAULT_CONFIG_DIR == paths.get_config_dir()
        assert config.DEFAULT_CONFIG_PATH == paths.get_config_path()

    def test_constant_is_a_real_settable_attribute(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Install/CLI tests monkeypatch this attribute directly; it must be a
        # real module attribute (not __getattr__-only) for setattr/undo to work.
        from openjarvis.core import config

        monkeypatch.setattr(config, "DEFAULT_CONFIG_DIR", tmp_path / "patched")
        assert config.DEFAULT_CONFIG_DIR == tmp_path / "patched"

    def test_dataclass_defaults_reflect_env(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Config dataclass field defaults must resolve under the override at
        # instantiation time, not freeze ~/.openjarvis at import.
        _clear_env(monkeypatch)
        from openjarvis.core.config import SessionConfig, StorageConfig

        monkeypatch.setenv("OPENJARVIS_HOME", str(tmp_path / "oj"))
        root = (tmp_path / "oj").resolve()
        assert StorageConfig().db_path == str(root / "memory.db")
        assert SessionConfig().db_path == str(root / "sessions.db")

    def test_downstream_consumer_honors_env(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # End-to-end: a non-config subsystem (credentials) resolves under the
        # custom root, proving the override is no longer split-brain.
        _clear_env(monkeypatch)
        from openjarvis.core import credentials

        monkeypatch.setenv("OPENJARVIS_HOME", str(tmp_path / "oj"))
        assert (
            credentials._default_path()
            == (tmp_path / "oj" / "credentials.toml").resolve()
        )
