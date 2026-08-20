"""Tests for openjarvis.mining._pearl_subprocess."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def fake_popen():
    """A MagicMock standing in for a live subprocess.Popen handle."""
    p = MagicMock()
    p.poll.return_value = None  # still running
    p.pid = 12345
    return p


def _make_launcher(tmp_path):
    """Build a launcher with safe defaults that won't conflict with anything."""
    from openjarvis.mining._pearl_subprocess import PearlSubprocessLauncher

    return PearlSubprocessLauncher(
        gateway_host="127.0.0.1",
        gateway_port=18337,
        metrics_port=18339,
        pearld_rpc_url="http://localhost:44107",
        pearld_rpc_user="rpcuser",
        pearld_rpc_password="testpw",
        wallet_address="prl1qtest",
        log_dir=tmp_path,
    )


def test_launcher_accepts_custom_provider_and_miner_module(fake_popen, tmp_path):
    """Providers can select a distinct miner-loop module and log file."""
    from openjarvis.mining._pearl_subprocess import PearlSubprocessLauncher

    with patch("subprocess.Popen", return_value=fake_popen) as mock_popen:
        launcher = PearlSubprocessLauncher(
            gateway_host="127.0.0.1",
            gateway_port=18337,
            metrics_port=18339,
            pearld_rpc_url="http://localhost:44107",
            pearld_rpc_user="rpcuser",
            pearld_rpc_password="testpw",
            wallet_address="prl1qtest",
            log_dir=tmp_path,
            provider_id="apple-mps-pearl",
            miner_module="openjarvis.mining._mps_miner_loop_main",
        )
        launcher.start(m=128, n=128, k=1024, rank=64)

    second_call = mock_popen.call_args_list[1]
    assert "_mps_miner_loop_main" in " ".join(second_call.args[0])


def test_launcher_start_spawns_two_processes(fake_popen, tmp_path):
    """start() spawns gateway and miner-loop subprocesses."""
    with patch("subprocess.Popen", return_value=fake_popen) as mock_popen:
        launcher = _make_launcher(tmp_path)
        launcher.start(m=256, n=128, k=1024, rank=32)
        assert mock_popen.call_count == 2  # gateway + miner-loop


def test_launcher_stop_terminates_both(fake_popen, tmp_path):
    """stop() sends SIGTERM to both subprocesses."""
    with patch("subprocess.Popen", return_value=fake_popen):
        launcher = _make_launcher(tmp_path)
        launcher.start(m=256, n=128, k=1024, rank=32)
        launcher.stop()
        assert fake_popen.terminate.call_count >= 2


def test_launcher_is_running_false_when_one_exited(tmp_path):
    """is_running() returns False if either subprocess has exited."""
    fake_alive = MagicMock()
    fake_alive.poll.return_value = None
    fake_alive.pid = 11111
    fake_dead = MagicMock()
    fake_dead.poll.return_value = 1
    fake_dead.pid = 22222

    with patch("subprocess.Popen", side_effect=[fake_alive, fake_dead]):
        launcher = _make_launcher(tmp_path)
        launcher.start(m=256, n=128, k=1024, rank=32)
        assert launcher.is_running() is False


def test_launcher_pids_returns_both(fake_popen, tmp_path):
    """pids() returns (gateway_pid, miner_loop_pid) after start."""
    fake_a = MagicMock()
    fake_a.poll.return_value = None
    fake_a.pid = 11111
    fake_b = MagicMock()
    fake_b.poll.return_value = None
    fake_b.pid = 22222
    with patch("subprocess.Popen", side_effect=[fake_a, fake_b]):
        launcher = _make_launcher(tmp_path)
        launcher.start(m=256, n=128, k=1024, rank=32)
        assert launcher.pids() == (11111, 22222)


def test_launcher_pids_returns_none_before_start(tmp_path):
    """pids() returns None before start()."""
    launcher = _make_launcher(tmp_path)
    assert launcher.pids() is None


def test_launcher_stop_idempotent(fake_popen, tmp_path):
    """stop() called twice is a no-op the second time."""
    with patch("subprocess.Popen", return_value=fake_popen):
        launcher = _make_launcher(tmp_path)
        launcher.start(m=256, n=128, k=1024, rank=32)
        launcher.stop()
        launcher.stop()  # should not raise


def test_launcher_spawn_order_is_gateway_then_miner_loop(fake_popen, tmp_path):
    """Gateway must be spawned before the miner-loop."""
    with patch("subprocess.Popen", return_value=fake_popen) as mock_popen:
        launcher = _make_launcher(tmp_path)
        launcher.start(m=256, n=128, k=1024, rank=32)
        first_call = mock_popen.call_args_list[0]
        second_call = mock_popen.call_args_list[1]
        assert first_call.args[0][0] == "pearl-gateway"
        assert "_miner_loop_main" in " ".join(second_call.args[0])


def test_launcher_start_twice_raises(fake_popen, tmp_path):
    """Calling start() while already running raises RuntimeError."""
    with patch("subprocess.Popen", return_value=fake_popen):
        launcher = _make_launcher(tmp_path)
        launcher.start(m=256, n=128, k=1024, rank=32)
        with pytest.raises(RuntimeError, match="already started"):
            launcher.start(m=256, n=128, k=1024, rank=32)
