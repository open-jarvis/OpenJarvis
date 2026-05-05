"""CLI smoke tests via Click CliRunner."""

from __future__ import annotations

from unittest.mock import patch

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
