"""CLI smoke tests via Click CliRunner."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from click.testing import CliRunner


def test_mine_doctor_prints_capability_matrix(hopper_hw):
    from openjarvis.cli.mine_cmd import mine

    runner = CliRunner()
    with (
        patch("openjarvis.cli.mine_cmd._detect_hardware", return_value=hopper_hw),
        patch(
            "openjarvis.cli.mine_cmd.check_docker_available",
            return_value=(True, "running 24.0.7"),
        ),
        patch(
            "openjarvis.cli.mine_cmd.check_disk_free",
            return_value=(True, "300 GB free"),
        ),
        patch(
            "openjarvis.cli.mine_cmd.check_pearld_reachable",
            return_value=(True, "block height 442107 (synced)"),
        ),
    ):
        result = runner.invoke(mine, ["doctor"])

    assert result.exit_code == 0, result.output
    out = result.output.lower()
    assert "hardware" in out
    assert "docker" in out
    assert "pearl" in out
    assert "vllm-pearl" in out
    assert "supported" in out


def test_mine_doctor_flags_unsupported_hardware(ada_hw):
    from openjarvis.cli.mine_cmd import mine

    runner = CliRunner()
    with (
        patch("openjarvis.cli.mine_cmd._detect_hardware", return_value=ada_hw),
        patch(
            "openjarvis.cli.mine_cmd.check_docker_available",
            return_value=(True, "ok"),
        ),
        patch(
            "openjarvis.cli.mine_cmd.check_disk_free",
            return_value=(True, "300 GB free"),
        ),
        patch(
            "openjarvis.cli.mine_cmd.check_pearld_reachable",
            return_value=(False, "connection refused"),
        ),
    ):
        result = runner.invoke(mine, ["doctor"])

    assert result.exit_code == 0
    assert "FAIL" in result.output
    assert "UNSUPPORTED" in result.output


def _mining_config():
    from openjarvis.mining._stubs import MiningConfig, SoloTarget

    return MiningConfig(
        provider="vllm-pearl",
        wallet_address="prl1qexampleaddress",
        submit_target=SoloTarget(pearld_rpc_url="http://localhost:44107"),
    )


def test_mine_start_runs_provider_start():
    from openjarvis.cli.mine_cmd import mine

    runner = CliRunner()
    fake_provider_class = MagicMock()
    with (
        patch("openjarvis.cli.mine_cmd.MinerRegistry") as reg,
        patch("openjarvis.cli.mine_cmd.load_config") as load,
        patch("openjarvis.cli.mine_cmd.asyncio.run") as arun,
    ):
        load.return_value = MagicMock(mining=_mining_config())
        reg.get.return_value = fake_provider_class
        result = runner.invoke(mine, ["start"])

    assert result.exit_code == 0, result.output
    arun.assert_called_once()
    fake_provider_class.assert_called_once()


def test_mine_stop_calls_provider_stop():
    from openjarvis.cli.mine_cmd import mine

    runner = CliRunner()
    fake_provider_class = MagicMock()
    with (
        patch("openjarvis.cli.mine_cmd.MinerRegistry") as reg,
        patch("openjarvis.cli.mine_cmd.load_config") as load,
        patch("openjarvis.cli.mine_cmd.asyncio.run") as arun,
    ):
        load.return_value = MagicMock(mining=_mining_config())
        reg.get.return_value = fake_provider_class
        result = runner.invoke(mine, ["stop"])

    assert result.exit_code == 0, result.output
    arun.assert_called_once()
    fake_provider_class.assert_called_once()


def test_mine_start_errors_when_no_mining_config():
    from openjarvis.cli.mine_cmd import mine

    runner = CliRunner()
    with patch("openjarvis.cli.mine_cmd.load_config") as load:
        load.return_value = MagicMock(mining=None)
        result = runner.invoke(mine, ["start"])

    assert result.exit_code != 0
    assert "init" in result.output.lower() or "no [mining]" in result.output.lower()


def test_mine_status_renders_stats():
    from openjarvis.cli.mine_cmd import mine
    from openjarvis.mining._stubs import MiningStats

    runner = CliRunner()
    fake_provider = MagicMock()
    fake_provider.stats.return_value = MiningStats(
        provider_id="vllm-pearl",
        shares_submitted=100,
        shares_accepted=99,
        blocks_found=2,
    )
    fake_provider_class = MagicMock(return_value=fake_provider)
    with (
        patch("openjarvis.cli.mine_cmd.MinerRegistry") as reg,
        patch("openjarvis.cli.mine_cmd.load_config") as load,
    ):
        load.return_value = MagicMock(mining=_mining_config())
        reg.get.return_value = fake_provider_class
        result = runner.invoke(mine, ["status"])

    assert result.exit_code == 0, result.output
    assert "100" in result.output
    assert "99" in result.output


def test_mine_attach_writes_sidecar(tmp_path, monkeypatch):
    from openjarvis.cli.mine_cmd import mine

    runner = CliRunner()
    sidecar = tmp_path / "mining.json"
    monkeypatch.setattr("openjarvis.cli.mine_cmd.SIDECAR_PATH", sidecar)

    result = runner.invoke(
        mine,
        [
            "attach",
            "--vllm-endpoint",
            "http://127.0.0.1:8000/v1",
            "--gateway-url",
            "http://127.0.0.1:8337",
            "--gateway-metrics-url",
            "http://127.0.0.1:8339",
            "--model",
            "pearl-ai/Llama-3.3-70B-Instruct-pearl",
        ],
    )

    assert result.exit_code == 0, result.output
    assert sidecar.exists()


def test_mine_logs_streams_container_output():
    from openjarvis.cli.mine_cmd import mine

    runner = CliRunner()
    fake_container = MagicMock()
    fake_container.logs.return_value = b"log line 1\nlog line 2\n"
    fake_client = MagicMock()
    fake_client.containers.get.return_value = fake_container
    with patch("openjarvis.cli.mine_cmd._docker_from_env", return_value=fake_client):
        result = runner.invoke(mine, ["logs", "--tail", "100"])

    assert result.exit_code == 0, result.output
    assert "log line 1" in result.output
