"""Tests for analytics opt-out logic and anonymous identity persistence."""

from __future__ import annotations

import pytest

from openjarvis.analytics.identity import (
    _env_opt_out,
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


# ---------------------------------------------------------------------------
# _env_opt_out — the env-var logic lives in its own helper, so test it
# directly. ``is_analytics_enabled`` short-circuits on pytest detection
# (PYTEST_CURRENT_TEST / sys.modules['pytest']) which is unavoidably True
# while we ARE running under pytest; testing the env logic in isolation
# sidesteps that whole problem.
# ---------------------------------------------------------------------------


class TestEnvOptOut:
    def test_no_env_returns_false(self):
        assert _env_opt_out() is False

    @pytest.mark.parametrize(
        "value", ["1", "true", "True", "TRUE", "yes", "on", "anything"]
    )
    def test_do_not_track_truthy(self, monkeypatch, value):
        monkeypatch.setenv("DO_NOT_TRACK", value)
        assert _env_opt_out() is True

    @pytest.mark.parametrize("value", ["1", "true", "yes", "on"])
    def test_openjarvis_no_analytics_truthy(self, monkeypatch, value):
        monkeypatch.setenv("OPENJARVIS_NO_ANALYTICS", value)
        assert _env_opt_out() is True

    @pytest.mark.parametrize("value", ["", "0", "false", "False", "no", "off"])
    def test_falsy_values_do_not_opt_out(self, monkeypatch, value):
        monkeypatch.setenv("DO_NOT_TRACK", value)
        assert _env_opt_out() is False

    def test_whitespace_quoted_truthy_still_opts_out(self, monkeypatch):
        # ``DO_NOT_TRACK=" 1 "`` (user shell-quoted with spaces) should
        # still opt out — we don't want to silently track because of a
        # shell-quoting accident.
        monkeypatch.setenv("DO_NOT_TRACK", " 1 ")
        assert _env_opt_out() is True


# ---------------------------------------------------------------------------
# is_analytics_enabled — top-level integration. The pytest short-circuit
# is intentional and fires during this test run; we assert the
# observable consequence (always False), then assert the precedence
# ordering (pytest > env > config).
# ---------------------------------------------------------------------------


class TestIsAnalyticsEnabled:
    def test_short_circuits_under_pytest(self, cfg_enabled):
        # We are running under pytest, so the function should return False
        # regardless of config or env state. This is the desired behavior
        # — see the function's docstring for the PostHog atexit-hang
        # reason. If this ever starts returning True, the pytest gating
        # has been broken and the test suite will start joining PostHog
        # consumer threads on exit.
        assert is_analytics_enabled(cfg_enabled) is False

    def test_disabled_config_under_pytest_also_false(self, cfg_disabled):
        assert is_analytics_enabled(cfg_disabled) is False

    def test_env_opt_out_doesnt_enable_disabled_config(
        self, cfg_disabled, monkeypatch
    ):
        """Env vars only ever disable; they never turn analytics ON."""
        monkeypatch.setenv("DO_NOT_TRACK", "1")
        assert is_analytics_enabled(cfg_disabled) is False


# ---------------------------------------------------------------------------
# Anonymous ID persistence — completely separate concern.
# ---------------------------------------------------------------------------


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
