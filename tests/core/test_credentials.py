"""Tests for credential persistence module."""

import os

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


@pytest.fixture(autouse=True)
def _isolate_environ():
    """Snapshot and restore os.environ around every test in this module.

    save_credential()/inject_credentials()/delete_credential() mutate
    os.environ directly as a side effect of file persistence -- they are
    production code, not test doubles, so monkeypatch's undo stack has no
    idea those mutations happened. A test that used
    monkeypatch.delenv("TAVILY_API_KEY") to clear the var before calling
    one of these functions would have monkeypatch snapshot whatever value
    had already leaked in from an earlier test and then RESTORE that
    leaked value at teardown -- permanently re-leaking it into every
    later test in the session, including tests/security/
    test_data_boundary_audit.py's cloud-surface detection (#788).
    Force a full restore of the real environment after every test here
    instead of relying on monkeypatch to track these direct mutations.
    """
    original = dict(os.environ)
    yield
    os.environ.clear()
    os.environ.update(original)


def test_save_and_load(cred_path):
    save_credential("web_search", "TAVILY_API_KEY", "tvly-123", path=cred_path)
    creds = load_credentials(path=cred_path)
    assert creds["web_search"]["TAVILY_API_KEY"] == "tvly-123"


def test_zz_previous_test_did_not_leak_env(cred_path):
    """Regression for #788: this must run *after* a test that sets
    TAVILY_API_KEY directly on os.environ (test_save_and_load, just
    above -- pytest runs tests in file order by default). Before the
    _isolate_environ fixture existed, save_credential()'s direct
    os.environ mutation was never cleaned up, and tests/security/
    test_data_boundary_audit.py's cloud-surface detection would see the
    leaked key and misreport a cloud API surface."""
    assert "TAVILY_API_KEY" not in os.environ


def test_save_sets_env(cred_path):
    os.environ.pop("TAVILY_API_KEY", None)
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


def test_get_status_missing():
    os.environ.pop("TAVILY_API_KEY", None)
    status = get_credential_status("web_search")
    assert status["TAVILY_API_KEY"] is False


def test_file_permissions(cred_path):
    save_credential("web_search", "TAVILY_API_KEY", "tvly-x", path=cred_path)
    mode = oct(cred_path.stat().st_mode & 0o777)
    assert mode == "0o600"


def test_inject_credentials_restores_saved_value(cred_path):
    save_credential("web_search", "TAVILY_API_KEY", "tvly-persisted", path=cred_path)
    os.environ.pop("TAVILY_API_KEY", None)

    inject_credentials(path=cred_path)

    assert os.environ["TAVILY_API_KEY"] == "tvly-persisted"


def test_delete_credential_removes_file_value_and_env(cred_path):
    save_credential("web_search", "TAVILY_API_KEY", "tvly-delete", path=cred_path)

    delete_credential("web_search", "TAVILY_API_KEY", path=cred_path)

    assert load_credentials(path=cred_path) == {}
    assert "TAVILY_API_KEY" not in os.environ


def test_delete_rejects_unknown_key(cred_path):
    with pytest.raises(ValueError, match="Unknown credential key"):
        delete_credential("web_search", "BOGUS_KEY", path=cred_path)
