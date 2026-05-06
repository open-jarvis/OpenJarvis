"""Tests for the ``jarvis mine`` CLI."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from openjarvis.cli import cli
from openjarvis.mining import Sidecar


def test_mine_help() -> None:
    result = CliRunner().invoke(cli, ["mine", "--help"])

    assert result.exit_code == 0
    assert "Configure and run Pearl mining" in result.output
    assert "init" in result.output
    assert "start" in result.output
    assert "doctor" in result.output


def test_mine_models_lists_validated_and_planned_models() -> None:
    result = CliRunner().invoke(cli, ["mine", "models"])

    assert result.exit_code == 0
    assert "Pearl Mining Models" in result.output
    assert "pearl-ai/Llama-3.3-70B-Instruct-pearl" in result.output
    assert "pearl-ai/Qwen3.5-9B-pearl" in result.output
    assert "validated" in result.output
    assert "planned" in result.output


def test_mine_init_writes_mining_config(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"

    result = CliRunner().invoke(
        cli,
        [
            "mine",
            "init",
            "--provider",
            "cpu-pearl",
            "--wallet-address",
            "prl1qtestingaddr",
            "--pearld-rpc-url",
            "http://127.0.0.1:44107",
            "--pearld-rpc-user",
            "rpcuser",
            "--pearld-rpc-password-env",
            "TEST_PEARLD_PASSWORD",
        ],
        env={"OPENJARVIS_CONFIG": str(config_path)},
    )

    assert result.exit_code == 0
    content = config_path.read_text()
    assert "[mining]" in content
    assert 'provider = "cpu-pearl"' in content
    assert 'wallet_address = "prl1qtestingaddr"' in content
    assert 'pearld_rpc_password_env = "TEST_PEARLD_PASSWORD"' in content


def test_mine_start_uses_configured_provider(tmp_path: Path, monkeypatch) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
[mining]
provider = "cpu-pearl"
wallet_address = "prl1qtest"
submit_target = "solo"

[mining.extra]
pearld_rpc_url = "http://127.0.0.1:44107"
pearld_rpc_user = "rpcuser"
pearld_rpc_password_env = "TEST_PEARLD_PASSWORD"
gateway_host = "127.0.0.1"
gateway_port = 18337
metrics_port = 19109
"""
    )
    sidecar_path = tmp_path / "mining.json"
    monkeypatch.setattr("openjarvis.cli.mine_cmd.SIDECAR_PATH", sidecar_path)

    started_configs = []

    async def fake_start(config):
        started_configs.append(config)

    fake_provider = MagicMock()
    provider_cls = MagicMock(return_value=fake_provider)
    fake_provider.start = fake_start

    with patch("openjarvis.cli.mine_cmd._provider_ids", return_value=("cpu-pearl",)):
        with patch("openjarvis.cli.mine_cmd.MinerRegistry.contains", return_value=True):
            with patch(
                "openjarvis.cli.mine_cmd.MinerRegistry.get",
                return_value=provider_cls,
            ):
                result = CliRunner().invoke(
                    cli,
                    ["mine", "start"],
                    env={
                        "OPENJARVIS_CONFIG": str(config_path),
                        "TEST_PEARLD_PASSWORD": "secret",
                    },
                )

    assert result.exit_code == 0
    assert "Started" in result.output
    provider_cls.assert_called_once_with()
    assert started_configs[0].provider == "cpu-pearl"


def test_mine_status_reports_sidecar_and_metrics(tmp_path: Path, monkeypatch) -> None:
    sidecar_path = tmp_path / "mining.json"
    Sidecar.write(
        sidecar_path,
        {
            "provider": "cpu-pearl",
            "wallet_address": "prl1qtest",
            "gateway_url": "http://127.0.0.1:8337",
            "metrics_url": "http://127.0.0.1:9109/metrics",
            "gateway_pid": 111,
            "miner_loop_pid": 222,
        },
    )
    monkeypatch.setattr("openjarvis.cli.mine_cmd.SIDECAR_PATH", sidecar_path)
    monkeypatch.setattr("openjarvis.cli.mine_cmd._pid_alive", lambda pid: True)

    stats = MagicMock()
    stats.shares_submitted = 3
    stats.shares_accepted = 2
    stats.blocks_found = 1
    monkeypatch.setattr(
        "openjarvis.cli.mine_cmd._stats_from_metrics_url",
        lambda url, provider_id: (stats, None),
    )

    result = CliRunner().invoke(cli, ["mine", "status"])

    assert result.exit_code == 0
    assert "cpu-pearl" in result.output
    assert "Shares submitted" in result.output
    assert "3" in result.output


def test_mine_stop_terminates_pids_and_removes_sidecar(
    tmp_path: Path, monkeypatch
) -> None:
    sidecar_path = tmp_path / "mining.json"
    Sidecar.write(
        sidecar_path,
        {
            "provider": "cpu-pearl",
            "gateway_pid": 111,
            "miner_loop_pid": 222,
        },
    )
    monkeypatch.setattr("openjarvis.cli.mine_cmd.SIDECAR_PATH", sidecar_path)
    terminated: list[int] = []

    def fake_terminate(pid, *, grace_seconds):
        terminated.append(pid)

    monkeypatch.setattr("openjarvis.cli.mine_cmd._terminate_pid", fake_terminate)

    result = CliRunner().invoke(cli, ["mine", "stop"])

    assert result.exit_code == 0
    assert sorted(terminated) == [111, 222]
    assert not sidecar_path.exists()


def test_mine_doctor_without_config(tmp_path: Path, monkeypatch) -> None:
    config_path = tmp_path / "missing.toml"
    monkeypatch.setattr("openjarvis.cli.mine_cmd.SIDECAR_PATH", tmp_path / "none.json")

    with patch("openjarvis.cli.mine_cmd._provider_ids", return_value=()):
        result = CliRunner().invoke(
            cli,
            ["mine", "doctor"],
            env={"OPENJARVIS_CONFIG": str(config_path)},
        )

    assert result.exit_code == 0
    assert "Pearl Mining Doctor" in result.output
    assert "jarvis mine init" in result.output


def test_mine_status_no_session(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("openjarvis.cli.mine_cmd.SIDECAR_PATH", tmp_path / "none.json")

    result = CliRunner().invoke(cli, ["mine", "status"])

    assert result.exit_code == 0
    assert "No active mining session" in result.output
