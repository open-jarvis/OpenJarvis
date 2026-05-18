"""Tests for analytics opt-out logic and anonymous identity persistence."""

from __future__ import annotations

import pytest

from openjarvis.analytics.identity import (
    get_or_create_anon_id,
    is_analytics_enabled,
    reset_anon_id,
)
from openjarvis.core.config import AnalyticsConfig


@pytest.fixture
def cfg_enabled() -> AnalyticsConfig:
    return AnalyticsConfig(enabled=True)


@pytest.fixture
def cfg_disabled() -> AnalyticsConfig:
    return AnalyticsConfig(enabled=False)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """Strip opt-out env vars so a host shell can't leak into tests."""
    monkeypatch.delenv("DO_NOT_TRACK", raising=False)
    monkeypatch.delenv("OPENJARVIS_NO_ANALYTICS", raising=False)


class TestIsAnalyticsEnabled:
    def test_config_enabled_no_env(self, cfg_enabled):
        assert is_analytics_enabled(cfg_enabled) is True

    def test_config_disabled_no_env(self, cfg_disabled):
        assert is_analytics_enabled(cfg_disabled) is False

    @pytest.mark.parametrize(
        "value", ["1", "true", "True", "TRUE", "yes", "on", "anything"]
    )
    def test_do_not_track_overrides_enabled_config(
        self, cfg_enabled, monkeypatch, value
    ):
        monkeypatch.setenv("DO_NOT_TRACK", value)
        assert is_analytics_enabled(cfg_enabled) is False

    @pytest.mark.parametrize("value", ["1", "true", "yes", "on"])
    def test_openjarvis_no_analytics_overrides_enabled_config(
        self, cfg_enabled, monkeypatch, value
    ):
        monkeypatch.setenv("OPENJARVIS_NO_ANALYTICS", value)
        assert is_analytics_enabled(cfg_enabled) is False

    @pytest.mark.parametrize("value", ["", "0", "false", "False", "no", "off"])
    def test_falsy_env_does_not_opt_out(self, cfg_enabled, monkeypatch, value):
        monkeypatch.setenv("DO_NOT_TRACK", value)
        assert is_analytics_enabled(cfg_enabled) is True

    def test_env_opt_out_does_not_re_enable_disabled_config(
        self, cfg_disabled, monkeypatch
    ):
        """Env vars only ever disable; they can't turn analytics ON."""
        monkeypatch.setenv("DO_NOT_TRACK", "1")
        assert is_analytics_enabled(cfg_disabled) is False

    def test_whitespace_in_env_var_treated_as_truthy_when_value_present(
        self, cfg_enabled, monkeypatch
    ):
        # `DO_NOT_TRACK=" 1 "` should still opt out — users shouldn't be
        # tracked because they accidentally shell-quoted with spaces.
        monkeypatch.setenv("DO_NOT_TRACK", " 1 ")
        assert is_analytics_enabled(cfg_enabled) is False


class TestAnonId:
    def test_create_persists_and_returns_same_uuid(self, tmp_path):
        p = tmp_path / "anon_id"
        a = get_or_create_anon_id(p)
        b = get_or_create_anon_id(p)
        assert a == b
        assert p.exists()
        assert len(a.strip()) == 36  # standard UUID v4 string length

    def test_reset_generates_new_uuid(self, tmp_path):
        p = tmp_path / "anon_id"
        original = get_or_create_anon_id(p)
        fresh = reset_anon_id(p)
        assert original != fresh
        assert p.read_text(encoding="utf-8").strip() == fresh

    def test_atomic_write_leaves_no_tmp_file(self, tmp_path):
        """The rename-after-write pattern should not leave an .anon_id.tmp behind."""
        p = tmp_path / "anon_id"
        get_or_create_anon_id(p)
        tmp_artifacts = list(tmp_path.glob("anon_id*.tmp"))
        assert tmp_artifacts == []
