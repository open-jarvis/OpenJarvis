"""Tests for the post-command "new version available" hint."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from openjarvis.cli._version_check import _check_disabled, check_for_updates


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for v in ("OPENJARVIS_NO_UPDATE_CHECK", "CI"):
        monkeypatch.delenv(v, raising=False)


class TestCheckDisabled:
    def test_default_not_disabled(self):
        assert _check_disabled() is False

    @pytest.mark.parametrize("value", ["1", "true", "yes", "on", "anything"])
    def test_jarvis_no_update_check_disables(self, monkeypatch, value):
        monkeypatch.setenv("OPENJARVIS_NO_UPDATE_CHECK", value)
        assert _check_disabled() is True

    @pytest.mark.parametrize("value", ["", "0", "false", "no", "off"])
    def test_falsy_does_not_disable(self, monkeypatch, value):
        monkeypatch.setenv("OPENJARVIS_NO_UPDATE_CHECK", value)
        assert _check_disabled() is False

    def test_ci_env_disables_by_default(self, monkeypatch):
        monkeypatch.setenv("CI", "true")
        assert _check_disabled() is True

    def test_ci_false_does_not_disable(self, monkeypatch):
        monkeypatch.setenv("CI", "false")
        assert _check_disabled() is False


class TestCheckForUpdates:
    @patch("openjarvis.cli._version_check._do_check")
    def test_runs_for_ask_command(self, mock_do):
        check_for_updates("ask")
        mock_do.assert_called_once()

    @patch("openjarvis.cli._version_check._do_check")
    def test_runs_for_doctor_command(self, mock_do):
        """Widened list: doctor wasn't checked before."""
        check_for_updates("doctor")
        mock_do.assert_called_once()

    @patch("openjarvis.cli._version_check._do_check")
    def test_skips_unknown_command(self, mock_do):
        check_for_updates("_bootstrap")
        mock_do.assert_not_called()

    @patch("openjarvis.cli._version_check._do_check")
    def test_ci_env_short_circuits_widely(self, mock_do, monkeypatch):
        monkeypatch.setenv("CI", "1")
        check_for_updates("ask")
        mock_do.assert_not_called()

    @patch(
        "openjarvis.cli._version_check._do_check",
        side_effect=Exception("boom"),
    )
    def test_exception_in_do_check_never_propagates(self, mock_do):
        # Best-effort: a broken check must not break the user's command.
        check_for_updates("ask")
        mock_do.assert_called_once()
