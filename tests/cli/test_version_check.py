"""Tests for the post-command "new version available" hint."""

from __future__ import annotations

import io
import json
import time
from unittest.mock import patch

import pytest

from openjarvis.cli import _version_check
from openjarvis.cli._version_check import (
    _check_disabled,
    _config_disabled,
    _fetch_latest_stable,
    _get_latest_version,
    check_for_updates,
)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch, tmp_path):
    for v in ("OPENJARVIS_NO_UPDATE_CHECK", "CI", "OPENJARVIS_CONFIG"):
        monkeypatch.delenv(v, raising=False)
    # Point config + cache at empty tmp paths so tests don't see the
    # developer's real ~/.openjarvis state.
    monkeypatch.setenv("OPENJARVIS_CONFIG", str(tmp_path / "no-config.toml"))
    monkeypatch.setattr(_version_check, "_CACHE_PATH", tmp_path / "version-check.json")


def _pypi_response(
    versions: dict[str, list] | None = None, info_version: str = ""
) -> io.BytesIO:
    """Build a minimal PyPI JSON payload."""
    payload = {
        "info": {"version": info_version},
        "releases": versions if versions is not None else {},
    }
    return io.BytesIO(json.dumps(payload).encode())


class _FakeResponse:
    """Context-manager-able stand-in for urllib's response."""

    def __init__(self, body: bytes) -> None:
        self._body = body

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *exc) -> None:
        pass

    def read(self) -> bytes:
        return self._body


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


class TestConfigDisabled:
    def test_missing_file_not_disabled(self):
        assert _config_disabled() is False

    def test_auto_update_false_disables(self, monkeypatch, tmp_path):
        cfg = tmp_path / "config.toml"
        cfg.write_text("[updates]\nauto_update = false\n")
        monkeypatch.setenv("OPENJARVIS_CONFIG", str(cfg))
        assert _config_disabled() is True

    def test_auto_update_true_does_not_disable(self, monkeypatch, tmp_path):
        cfg = tmp_path / "config.toml"
        cfg.write_text("[updates]\nauto_update = true\n")
        monkeypatch.setenv("OPENJARVIS_CONFIG", str(cfg))
        assert _config_disabled() is False

    def test_updates_section_absent_does_not_disable(self, monkeypatch, tmp_path):
        cfg = tmp_path / "config.toml"
        cfg.write_text("[other]\nkey = 1\n")
        monkeypatch.setenv("OPENJARVIS_CONFIG", str(cfg))
        assert _config_disabled() is False

    def test_malformed_toml_treated_as_optout(self, monkeypatch, tmp_path):
        """A typo in the user's config must not silently re-enable updates.

        Conservative: if the user touched the file at all, assume they meant
        to opt out and would rather see no nudge than the wrong behavior.
        """
        cfg = tmp_path / "config.toml"
        cfg.write_text("[updates\nauto_update = false\n")  # missing ]
        monkeypatch.setenv("OPENJARVIS_CONFIG", str(cfg))
        assert _config_disabled() is True

    def test_openjarvis_config_env_override(self, monkeypatch, tmp_path):
        """OPENJARVIS_CONFIG should redirect the lookup, matching core.config."""
        cfg = tmp_path / "alt.toml"
        cfg.write_text("[updates]\nauto_update = false\n")
        monkeypatch.setenv("OPENJARVIS_CONFIG", str(cfg))
        assert _check_disabled() is True


class TestFetchLatestStable:
    def test_picks_highest_non_dev_release(self):
        body = _pypi_response(
            versions={
                "1.0.0": [{}],
                "1.0.1": [{}],
                "1.0.2.dev500": [{}],
                "1.0.2.dev499": [{}],
            },
            info_version="1.0.2.dev500",  # PyPI's "latest upload" may be a dev
        )
        with patch(
            "urllib.request.urlopen", return_value=_FakeResponse(body.getvalue())
        ):
            assert _fetch_latest_stable() == "1.0.1"

    def test_returns_info_version_when_no_stable(self):
        body = _pypi_response(
            versions={"1.0.0.dev1": [{}]},
            info_version="1.0.0.dev1",
        )
        with patch(
            "urllib.request.urlopen", return_value=_FakeResponse(body.getvalue())
        ):
            # No stable release yet — fall back to info.version so we still
            # report *something* rather than silently returning None.
            assert _fetch_latest_stable() == "1.0.0.dev1"

    def test_skips_invalid_version_strings(self):
        body = _pypi_response(
            versions={
                "1.0.0": [{}],
                "garbage-version": [{}],
                "1.1.0": [{}],
            },
            info_version="1.1.0",
        )
        with patch(
            "urllib.request.urlopen", return_value=_FakeResponse(body.getvalue())
        ):
            assert _fetch_latest_stable() == "1.1.0"

    def test_network_error_returns_none(self):
        with patch("urllib.request.urlopen", side_effect=OSError("offline")):
            assert _fetch_latest_stable() is None

    def test_filters_prereleases(self):
        body = _pypi_response(
            versions={"1.0.0": [{}], "1.1.0rc1": [{}], "1.1.0b2": [{}]},
            info_version="1.1.0rc1",
        )
        with patch(
            "urllib.request.urlopen", return_value=_FakeResponse(body.getvalue())
        ):
            assert _fetch_latest_stable() == "1.0.0"


class TestGetLatestVersion:
    def test_fresh_cache_short_circuits_network(self, tmp_path):
        cache = _version_check._CACHE_PATH
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(
            json.dumps({"last_check": time.time(), "latest_version": "9.9.9"})
        )
        with patch("urllib.request.urlopen") as mock_open:
            assert _get_latest_version("1.0.0") == "9.9.9"
            mock_open.assert_not_called()

    def test_stale_cache_refetches(self, tmp_path):
        cache = _version_check._CACHE_PATH
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(
            json.dumps({"last_check": time.time() - 999_999, "latest_version": "0.0.1"})
        )
        body = _pypi_response(versions={"1.2.3": [{}]}, info_version="1.2.3")
        with patch(
            "urllib.request.urlopen", return_value=_FakeResponse(body.getvalue())
        ):
            assert _get_latest_version("1.0.0") == "1.2.3"

    def test_empty_version_is_not_cached(self, tmp_path):
        """An empty PyPI ``info.version`` must not poison the cache for 24h."""
        cache = _version_check._CACHE_PATH
        body = _pypi_response(versions={}, info_version="")
        with patch(
            "urllib.request.urlopen", return_value=_FakeResponse(body.getvalue())
        ):
            assert _get_latest_version("1.0.0") is None
        assert not cache.exists(), "empty version must not be written to cache"

    def test_cached_empty_string_returns_none(self, tmp_path):
        """A previously-cached empty string from older builds must not crash."""
        cache = _version_check._CACHE_PATH
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps({"last_check": time.time(), "latest_version": ""}))
        with patch("urllib.request.urlopen") as mock_open:
            assert _get_latest_version("1.0.0") is None
            mock_open.assert_not_called()


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
