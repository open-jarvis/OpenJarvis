"""Tests for file sensitivity policy."""

from __future__ import annotations

from pathlib import Path

import pytest

from openjarvis.security.file_policy import filter_sensitive_paths, is_sensitive_file


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

    @pytest.mark.parametrize(
        "sensitive_name", [".env", "credentials.json", "server.pem"]
    )
    def test_sensitive_symlink_alias(self, tmp_path: Path, sensitive_name: str) -> None:
        sensitive = tmp_path / sensitive_name
        sensitive.write_text("SENSITIVE-SENTINEL", encoding="utf-8")
        alias = tmp_path / "notes.txt"
        try:
            alias.symlink_to(sensitive)
        except OSError:
            pytest.skip("filesystem does not permit creating symlinks")

        assert is_sensitive_file(alias) is True

    def test_sensitive_symlink_alias_to_missing_target(self, tmp_path: Path) -> None:
        alias = tmp_path / "notes.txt"
        try:
            alias.symlink_to(tmp_path / ".env")
        except OSError:
            pytest.skip("filesystem does not permit creating symlinks")

        assert is_sensitive_file(alias) is True


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
