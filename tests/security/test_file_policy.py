"""Tests for file sensitivity policy."""

from __future__ import annotations

from pathlib import Path

import pytest

from openjarvis.security.file_policy import (
    _is_sensitive_file_py,
    filter_sensitive_paths,
    is_sensitive_file,
)


def _symlink_or_mock_resolution(
    link: Path,
    target: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    try:
        link.symlink_to(target)
    except (NotImplementedError, OSError):
        link.write_bytes(target.read_bytes())
        original_resolve = Path.resolve

        def resolve_alias(self: Path, strict: bool = False) -> Path:
            if self == link:
                return target
            return original_resolve(self, strict=strict)

        monkeypatch.setattr(Path, "resolve", resolve_alias)


class TestIsSensitiveFile:
    def test_sensitive_env(self) -> None:
        assert is_sensitive_file(".env") is True

    def test_sensitive_env_local(self) -> None:
        assert is_sensitive_file(".env.local") is True

    def test_sensitive_pem(self) -> None:
        assert is_sensitive_file("server.pem") is True

    def test_sensitive_key(self) -> None:
        assert is_sensitive_file("private.key") is True

    def test_sensitive_id_rsa(self) -> None:
        assert is_sensitive_file("id_rsa") is True

    def test_sensitive_credentials(self) -> None:
        assert is_sensitive_file("credentials.json") is True

    def test_sensitive_htpasswd(self) -> None:
        assert is_sensitive_file(".htpasswd") is True

    def test_sensitive_pgpass(self) -> None:
        assert is_sensitive_file(".pgpass") is True

    def test_sensitive_netrc(self) -> None:
        assert is_sensitive_file(".netrc") is True

    def test_sensitive_p12(self) -> None:
        assert is_sensitive_file("cert.p12") is True

    def test_sensitive_pfx(self) -> None:
        assert is_sensitive_file("cert.pfx") is True

    def test_sensitive_jks(self) -> None:
        assert is_sensitive_file("keystore.jks") is True

    def test_sensitive_id_ed25519(self) -> None:
        assert is_sensitive_file("id_ed25519") is True

    def test_sensitive_secret(self) -> None:
        assert is_sensitive_file(".secret") is True

    def test_sensitive_env_in_path(self) -> None:
        assert is_sensitive_file(Path("/some/dir/.env")) is True

    def test_not_sensitive_py(self) -> None:
        assert is_sensitive_file("main.py") is False

    def test_not_sensitive_txt(self) -> None:
        assert is_sensitive_file("readme.txt") is False

    def test_not_sensitive_toml(self) -> None:
        assert is_sensitive_file("pyproject.toml") is False

    def test_not_sensitive_json(self) -> None:
        assert is_sensitive_file("package.json") is False

    def test_path_object(self) -> None:
        assert is_sensitive_file(Path("server.pem")) is True
        assert is_sensitive_file(Path("main.py")) is False

    def test_sensitive_target_is_blocked_through_safe_named_alias(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        target = tmp_path / ".env"
        target.write_text("SECRET=value", encoding="utf-8")
        alias = tmp_path / "notes.txt"
        _symlink_or_mock_resolution(alias, target, monkeypatch)

        assert is_sensitive_file(alias) is True

    def test_safe_target_remains_allowed_through_alias(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        target = tmp_path / "notes.txt"
        target.write_text("safe", encoding="utf-8")
        alias = tmp_path / "alias.txt"
        _symlink_or_mock_resolution(alias, target, monkeypatch)

        assert is_sensitive_file(alias) is False

    def test_resolution_failure_is_denied(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        def fail_resolution(self: Path, strict: bool = False) -> Path:
            raise RuntimeError("symlink loop")

        monkeypatch.setattr(Path, "resolve", fail_resolution)

        assert is_sensitive_file(tmp_path / "ordinary.txt") is True

    @pytest.mark.parametrize(
        "name",
        [".ENV", "Credentials.JSON", "PRIVATE.KEY", "ID_RSA"],
    )
    def test_python_matcher_is_case_insensitive(
        self,
        name: str,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr("fnmatch.os.path.normcase", lambda value: value)
        assert _is_sensitive_file_py(name) is True


class TestFilterSensitivePaths:
    def test_filter_sensitive_paths(self) -> None:
        paths = [
            "main.py",
            ".env",
            "server.pem",
            "readme.txt",
            "credentials.json",
            "app.js",
        ]
        filtered = filter_sensitive_paths(paths)
        names = [p.name for p in filtered]
        assert "main.py" in names
        assert "readme.txt" in names
        assert "app.js" in names
        assert ".env" not in names
        assert "server.pem" not in names
        assert "credentials.json" not in names

    def test_filter_all_sensitive(self) -> None:
        paths = [".env", "server.pem", "credentials.json"]
        filtered = filter_sensitive_paths(paths)
        assert filtered == []

    def test_filter_none_sensitive(self) -> None:
        paths = ["main.py", "app.js", "readme.txt"]
        filtered = filter_sensitive_paths(paths)
        assert len(filtered) == 3

    def test_filter_empty(self) -> None:
        assert filter_sensitive_paths([]) == []
