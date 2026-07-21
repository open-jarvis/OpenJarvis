"""Tests for analytics identity + the DO_NOT_TRACK kill-switch."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from openjarvis.analytics.identity import (
    do_not_track,
    get_or_create_anon_id,
    is_analytics_enabled,
    reset_anon_id,
)


@dataclass
class _Cfg:
    enabled: bool


class TestDoNotTrack:
    @pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", "Yes", " true "])
    def test_truthy_values_enable_dnt(self, monkeypatch, value):
        monkeypatch.setenv("DO_NOT_TRACK", value)
        assert do_not_track() is True

    @pytest.mark.parametrize("value", ["0", "false", "no", "", "off"])
    def test_falsey_values_disable_dnt(self, monkeypatch, value):
        monkeypatch.setenv("DO_NOT_TRACK", value)
        assert do_not_track() is False

    def test_unset_is_false(self, monkeypatch):
        monkeypatch.delenv("DO_NOT_TRACK", raising=False)
        assert do_not_track() is False


class TestIsAnalyticsEnabled:
    def test_config_enabled_no_dnt(self, monkeypatch):
        monkeypatch.delenv("DO_NOT_TRACK", raising=False)
        assert is_analytics_enabled(_Cfg(enabled=True)) is True

    def test_config_disabled(self, monkeypatch):
        monkeypatch.delenv("DO_NOT_TRACK", raising=False)
        assert is_analytics_enabled(_Cfg(enabled=False)) is False

    def test_dnt_overrides_enabled_config(self, monkeypatch):
        # The whole point: DNT wins even when config says analytics is on.
        monkeypatch.setenv("DO_NOT_TRACK", "1")
        assert is_analytics_enabled(_Cfg(enabled=True)) is False

    def test_dnt_zero_does_not_disable(self, monkeypatch):
        monkeypatch.setenv("DO_NOT_TRACK", "0")
        assert is_analytics_enabled(_Cfg(enabled=True)) is True


class TestAnonId:
    def test_create_and_persist(self, tmp_path):
        p = tmp_path / "anon_id"
        first = get_or_create_anon_id(p)
        assert first
        # Idempotent — same value on second call.
        assert get_or_create_anon_id(p) == first

    def test_reset_changes_id(self, tmp_path):
        p = tmp_path / "anon_id"
        first = get_or_create_anon_id(p)
        second = reset_anon_id(p)
        assert second and second != first
