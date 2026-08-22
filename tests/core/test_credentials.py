"""Tests for credential persistence module."""

import os

import pytest

from openjarvis.core.credentials import (
    TOOL_CREDENTIALS,
    delete_credential,
    get_credential_status,
    inject_credentials,
    load_credentials,
    save_credential,
)

_CREDENTIAL_ENV_KEYS = frozenset(
    key for keys in TOOL_CREDENTIALS.values() for key in keys
)
_ENV_BASELINE = {
    key: value for key, value in os.environ.items() if key in _CREDENTIAL_ENV_KEYS
}


@pytest.fixture
def cred_path(tmp_path):
    return tmp_path / "credentials.toml"


def _restore_credential_environ(snapshot):
    """Restore credential variables without disturbing pytest/process internals."""
    for key in _CREDENTIAL_ENV_KEYS:
        if key in snapshot:
            os.environ[key] = snapshot[key]
        else:
            os.environ.pop(key, None)


@pytest.fixture(autouse=True)
def _isolate_environ():
    """Reset os.environ to the collection baseline around every test.

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
    Resetting both before and after each test makes isolation independent
    of test order while preserving legitimate ambient credentials supplied
    by the developer or CI process.
    """
    _restore_credential_environ(_ENV_BASELINE)
    yield
    _restore_credential_environ(_ENV_BASELINE)


def test_save_and_load(cred_path):
    save_credential("web_search", "TAVILY_API_KEY", "tvly-123", path=cred_path)
    creds = load_credentials(path=cred_path)
    assert creds["web_search"]["TAVILY_API_KEY"] == "tvly-123"


def test_credential_special_characters_round_trip(cred_path):
    value = 'quote" backslash\\ internal\nnewline and unicode: café 🔐'

    save_credential("email", "EMAIL_PASSWORD", value, path=cred_path)

    assert load_credentials(path=cred_path)["email"]["EMAIL_PASSWORD"] == value
    assert cred_path.read_text(encoding="utf-8")


def test_malformed_file_is_backed_up_and_store_recovers(cred_path):
    malformed = '[email]\nEMAIL_PASSWORD = "unterminated\n'
    cred_path.write_text(malformed, encoding="utf-8")

    assert load_credentials(path=cred_path) == {}
    assert not cred_path.exists()
    backups = list(cred_path.parent.glob("credentials.toml.corrupt-*"))
    assert len(backups) == 1
    assert backups[0].read_text(encoding="utf-8") == malformed

    save_credential("web_search", "TAVILY_API_KEY", "recovered", path=cred_path)
    assert load_credentials(path=cred_path) == {
        "web_search": {"TAVILY_API_KEY": "recovered"}
    }


def test_atomic_write_failure_preserves_existing_credentials(cred_path, monkeypatch):
    save_credential("web_search", "TAVILY_API_KEY", "original", path=cred_path)
    original = cred_path.read_bytes()

    def fail_replace(source, destination):
        raise OSError("replace blocked")

    monkeypatch.setattr("openjarvis.security.file_utils.os.replace", fail_replace)
    with pytest.raises(OSError, match="replace blocked"):
        save_credential("web_search", "TAVILY_API_KEY", "new", path=cred_path)

    assert cred_path.read_bytes() == original


def test_restore_environ_preserves_legitimate_ambient_key(cred_path):
    """Regression for #788 must not erase a real key from the parent process."""
    baseline = {"TAVILY_API_KEY": "tvly-legitimate-ambient"}
    _restore_credential_environ(baseline)

    save_credential("web_search", "TAVILY_API_KEY", "tvly-test", path=cred_path)
    assert os.environ["TAVILY_API_KEY"] == "tvly-test"

    _restore_credential_environ(baseline)
    assert os.environ["TAVILY_API_KEY"] == "tvly-legitimate-ambient"


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
