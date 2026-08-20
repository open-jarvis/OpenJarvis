"""Tests for the ``jarvis pearl`` CLI wrappers."""

from __future__ import annotations

import subprocess

from click.testing import CliRunner

from openjarvis.cli import cli


def test_pearl_help_lists_wrappers() -> None:
    result = CliRunner().invoke(cli, ["pearl", "--help"])

    assert result.exit_code == 0
    assert "node" in result.output
    assert "wallet" in result.output
    assert "ctl" in result.output
    assert "address" in result.output


def test_pearl_doctor_reports_discovered_binaries(monkeypatch) -> None:
    def fake_resolve(name: str, pearl_home: str | None = None) -> str | None:
        return f"/opt/pearl/bin/{name}" if name != "oyster" else None

    monkeypatch.setattr("openjarvis.cli.pearl_cmd._resolve_binary", fake_resolve)

    result = CliRunner().invoke(cli, ["pearl", "doctor"])

    assert result.exit_code == 0
    assert "pearld" in result.output
    assert "/opt/pearl/bin/pearld" in result.output
    assert "oyster" in result.output
    assert "not found" in result.output


def test_pearl_node_passes_args_to_pearld(monkeypatch) -> None:
    calls: list[tuple[str, tuple[str, ...], str | None]] = []

    def fake_run(
        name: str, args: tuple[str, ...], pearl_home: str | None = None
    ) -> int:
        calls.append((name, args, pearl_home))
        return 7

    monkeypatch.setattr("openjarvis.cli.pearl_cmd._run", fake_run)

    result = CliRunner().invoke(
        cli,
        ["pearl", "node", "--pearl-home", "/opt/pearl", "--notls", "--txindex"],
    )

    assert result.exit_code == 7
    assert calls == [("pearld", ("--notls", "--txindex"), "/opt/pearl")]


def test_pearl_ctl_passes_args_to_prlctl(monkeypatch) -> None:
    calls: list[tuple[str, tuple[str, ...], str | None]] = []

    def fake_run(
        name: str, args: tuple[str, ...], pearl_home: str | None = None
    ) -> int:
        calls.append((name, args, pearl_home))
        return 0

    monkeypatch.setattr("openjarvis.cli.pearl_cmd._run", fake_run)

    result = CliRunner().invoke(
        cli,
        ["pearl", "ctl", "--wallet", "--notls", "-s", "localhost:44207", "help"],
    )

    assert result.exit_code == 0
    assert calls == [
        ("prlctl", ("--wallet", "--notls", "-s", "localhost:44207", "help"), None)
    ]


def test_pearl_address_uses_wallet_rpc(monkeypatch) -> None:
    calls: list[tuple[str, tuple[str, ...], str | None]] = []

    def fake_capture(
        name: str, args: tuple[str, ...], pearl_home: str | None = None
    ) -> subprocess.CompletedProcess[str]:
        calls.append((name, args, pearl_home))
        return subprocess.CompletedProcess(
            args=[name, *args],
            returncode=0,
            stdout="prl1pabc\n",
            stderr="",
        )

    monkeypatch.setattr("openjarvis.cli.pearl_cmd._run_capture", fake_capture)

    result = CliRunner().invoke(
        cli,
        [
            "pearl",
            "address",
            "--pearl-home",
            "/opt/pearl",
            "-u",
            "alice",
            "-P",
            "secret",
            "-s",
            "localhost:44209",
        ],
    )

    assert result.exit_code == 0
    assert "prl1pabc" in result.output
    assert calls == [
        (
            "prlctl",
            (
                "--wallet",
                "-u",
                "alice",
                "-P",
                "secret",
                "-s",
                "localhost:44209",
                "--notls",
                "getnewaddress",
            ),
            "/opt/pearl",
        )
    ]
