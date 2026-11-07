"""Tests for mount_security module."""

from __future__ import annotations

import json

import pytest

from friday_ai.sandbox.mount_security import (
    DEFAULT_BLOCKED_PATTERNS,
    AllowedRoot,
    MountAllowlist,
    load_mount_allowlist,
    validate_mount,
    validate_mounts,
)


class TestDefaultBlockedPatterns:
    def test_contains_ssh(self):
        assert ".ssh" in DEFAULT_BLOCKED_PATTERNS

    def test_contains_env(self):
        assert ".env" in DEFAULT_BLOCKED_PATTERNS

    def test_contains_pem(self):
        assert "*.pem" in DEFAULT_BLOCKED_PATTERNS

    def test_contains_key(self):
        assert "*.key" in DEFAULT_BLOCKED_PATTERNS

    def test_contains_gnupg(self):
        assert ".gnupg" in DEFAULT_BLOCKED_PATTERNS

    def test_contains_aws(self):
        assert ".aws" in DEFAULT_BLOCKED_PATTERNS

    def test_contains_credentials(self):
        assert "credentials" in DEFAULT_BLOCKED_PATTERNS


class TestValidateMount:
    def test_allows_valid_path(self, tmp_path):
        allowlist = MountAllowlist(
            roots=[AllowedRoot(path=str(tmp_path))],
        )
        target = tmp_path / "data"
        target.mkdir()
        assert validate_mount(str(target), allowlist) is True

    def test_blocks_ssh_dir(self, tmp_path):
        allowlist = MountAllowlist(
            roots=[AllowedRoot(path=str(tmp_path))],
        )
        target = tmp_path / ".ssh"
        target.mkdir()
        assert validate_mount(str(target), allowlist) is False

    def test_blocks_env_file(self, tmp_path):
        allowlist = MountAllowlist(
            roots=[AllowedRoot(path=str(tmp_path))],
        )
        target = tmp_path / ".env"
        target.touch()
        assert validate_mount(str(target), allowlist) is False

    def test_blocks_pem_file(self, tmp_path):
        allowlist = MountAllowlist(
            roots=[AllowedRoot(path=str(tmp_path))],
        )
        target = tmp_path / "server.pem"
        target.touch()
        assert validate_mount(str(target), allowlist) is False

    def test_blocks_key_file(self, tmp_path):
        allowlist = MountAllowlist(
            roots=[AllowedRoot(path=str(tmp_path))],
        )
        target = tmp_path / "private.key"
        target.touch()
        assert validate_mount(str(target), allowlist) is False

    def test_rejects_outside_root(self, tmp_path):
        allowlist = MountAllowlist(
            roots=[AllowedRoot(path=str(tmp_path / "allowed"))],
        )
        target = tmp_path / "not_allowed" / "data"
        target.mkdir(parents=True)
        assert validate_mount(str(target), allowlist) is False

    def test_no_roots_allows_non_blocked(self, tmp_path):
        allowlist = MountAllowlist(roots=[])
        target = tmp_path / "safe_dir"
        target.mkdir()
        assert validate_mount(str(target), allowlist) is True

    def test_traversal_prevention(self, tmp_path):
        """Paths with .. are resolved before checking."""
        allowed = tmp_path / "allowed"
        allowed.mkdir()
        # This resolves to tmp_path (outside allowed)
        traversal = str(allowed / ".." / "secret")
        allowlist = MountAllowlist(
            roots=[AllowedRoot(path=str(allowed))],
            blocked_patterns=["secret"],
        )
        assert validate_mount(traversal, allowlist) is False


class TestValidateMounts:
    def test_returns_valid_mounts(self, tmp_path):
        d1 = tmp_path / "data1"
        d2 = tmp_path / "data2"
        d1.mkdir()
        d2.mkdir()
        allowlist = MountAllowlist(
            roots=[AllowedRoot(path=str(tmp_path))],
        )
        result = validate_mounts([str(d1), str(d2)], allowlist)
        assert len(result) == 2

    def test_raises_for_blocked(self, tmp_path):
        target = tmp_path / ".ssh"
        target.mkdir()
        allowlist = MountAllowlist(
            roots=[AllowedRoot(path=str(tmp_path))],
        )
        with pytest.raises(ValueError, match="blocked"):
            validate_mounts([str(target)], allowlist)

    def test_raises_for_outside_root(self, tmp_path):
        target = tmp_path / "outside"
        target.mkdir()
        allowlist = MountAllowlist(
            roots=[AllowedRoot(path=str(tmp_path / "inside"))],
        )
        with pytest.raises(ValueError, match="not under"):
            validate_mounts([str(target)], allowlist)

    def test_empty_list(self):
        allowlist = MountAllowlist()
        assert validate_mounts([], allowlist) == []


class TestLoadMountAllowlist:
    def test_loads_from_json(self, tmp_path):
        config = {
            "roots": [
                {"path": "/home/user/projects", "read_only": False},
                {"path": "/data"},
            ],
            "blocked_patterns": [".ssh", "*.pem"],
        }
        f = tmp_path / "allowlist.json"
        f.write_text(json.dumps(config))

        al = load_mount_allowlist(str(f))
        assert len(al.roots) == 2
        assert al.roots[0].path == "/home/user/projects"
        assert al.roots[0].read_only is False
        assert al.roots[1].read_only is True
        assert al.blocked_patterns == [".ssh", "*.pem"]

    def test_default_blocked_patterns(self, tmp_path):
        config = {"roots": []}
        f = tmp_path / "allowlist.json"
        f.write_text(json.dumps(config))

        al = load_mount_allowlist(str(f))
        assert al.blocked_patterns == DEFAULT_BLOCKED_PATTERNS
