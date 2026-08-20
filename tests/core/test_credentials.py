"""Tests for credential persistence module."""

import os
from unittest.mock import patch

import pytest

from openjarvis.core.credentials import (
    delete_credential,
    get_credential_status,
    inject_credentials,
    load_credentials,
    save_credential,
)


@pytest.fixture
def cred_path(tmp_path):
    return tmp_path / "credentials.toml"


def test_save_and_load(cred_path):
    save_credential("web_search", "TAVILY_API_KEY", "tvly-123", path=cred_path)
    creds = load_credentials(path=cred_path)
    assert creds["web_search"]["TAVILY_API_KEY"] == "tvly-123"


def test_save_sets_env(cred_path, monkeypatch):
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    save_credential("web_search", "TAVILY_API_KEY", "tvly-abc", path=cred_path)
    assert os.environ["TAVILY_API_KEY"] == "tvly-abc"


def test_save_rejects_unknown_key(cred_path):
    with pytest.raises(ValueError, match="Unknown credential key"):
        save_credential("web_search", "BOGUS_KEY", "val", path=cred_path)


def test_save_rejects_empty_value(cred_path):
    with pytest.raises(ValueError, match="empty"):
        save_credential("web_search", "TAVILY_API_KEY", "  ", path=cred_path)


def test_get_status(cred_path, monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-x")
    status = get_credential_status("web_search")
    assert status["TAVILY_API_KEY"] is True


def test_get_status_missing(monkeypatch):
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    status = get_credential_status("web_search")
    assert status["TAVILY_API_KEY"] is False


def test_file_permissions(cred_path):
    save_credential("web_search", "TAVILY_API_KEY", "tvly-x", path=cred_path)
    mode = oct(cred_path.stat().st_mode & 0o777)
    assert mode == "0o600"


def test_inject_credentials_restores_saved_value(cred_path, monkeypatch):
    save_credential("web_search", "TAVILY_API_KEY", "tvly-persisted", path=cred_path)
    monkeypatch.delenv("TAVILY_API_KEY")

    inject_credentials(path=cred_path)

    assert os.environ["TAVILY_API_KEY"] == "tvly-persisted"


def test_delete_credential_removes_file_value_and_env(cred_path, monkeypatch):
    save_credential("web_search", "TAVILY_API_KEY", "tvly-delete", path=cred_path)

    delete_credential("web_search", "TAVILY_API_KEY", path=cred_path)

    assert load_credentials(path=cred_path) == {}
    assert "TAVILY_API_KEY" not in os.environ


def test_delete_rejects_unknown_key(cred_path):
    with pytest.raises(ValueError, match="Unknown credential key"):
        delete_credential("web_search", "BOGUS_KEY", path=cred_path)


def test_special_characters_round_trip(cred_path):
    nasty = 'p@ss"w\\ord\twith\nnewline'

    save_credential("email", "EMAIL_PASSWORD", nasty, path=cred_path)
    save_credential("email", "EMAIL_USERNAME", "me@example.com", path=cred_path)

    creds = load_credentials(path=cred_path)
    assert creds["email"]["EMAIL_PASSWORD"] == nasty
    assert creds["email"]["EMAIL_USERNAME"] == "me@example.com"


def test_failed_atomic_replace_preserves_existing_store(cred_path):
    save_credential("web_search", "TAVILY_API_KEY", "original", path=cred_path)

    with (
        patch("openjarvis.core.credentials.os.replace", side_effect=OSError("boom")),
        pytest.raises(OSError, match="boom"),
    ):
        save_credential("web_search", "TAVILY_API_KEY", "new", path=cred_path)

    assert load_credentials(path=cred_path)["web_search"]["TAVILY_API_KEY"] == (
        "original"
    )
    assert list(cred_path.parent.glob(f".{cred_path.name}.*")) == []
