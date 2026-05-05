"""Tests for mining/_docker.py — Docker SDK orchestration via mocks."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


def test_ensure_image_already_local():
    from openjarvis.mining._docker import PearlDockerLauncher
    fake = MagicMock()
    fake.images.get.return_value = MagicMock(
        id="sha256:abc", tags=["openjarvis/pearl-miner:main"]
    )
    launcher = PearlDockerLauncher(client=fake)
    out = launcher.ensure_image("openjarvis/pearl-miner:main")
    assert out == "openjarvis/pearl-miner:main"
    fake.images.get.assert_called_once_with("openjarvis/pearl-miner:main")
    fake.images.pull.assert_not_called()


def test_ensure_image_pulls_if_published():
    import docker.errors as derr

    from openjarvis.mining._docker import PearlDockerLauncher
    fake = MagicMock()
    fake.images.get.side_effect = derr.ImageNotFound("nope")
    fake.images.pull.return_value = MagicMock(id="sha256:def")
    launcher = PearlDockerLauncher(client=fake)
    out = launcher.ensure_image("registry.example/pearl-miner:1.0")
    assert out == "registry.example/pearl-miner:1.0"
    fake.images.pull.assert_called_once_with("registry.example/pearl-miner:1.0")


def test_ensure_image_falls_back_to_build_for_default_tag():
    import docker.errors as derr

    from openjarvis.mining._constants import PEARL_IMAGE_TAG
    from openjarvis.mining._docker import PearlDockerLauncher
    fake = MagicMock()
    fake.images.get.side_effect = derr.ImageNotFound("nope")
    fake.images.pull.side_effect = derr.NotFound("registry refused")
    launcher = PearlDockerLauncher(client=fake)
    with patch.object(launcher, "_clone_pearl_repo") as clone, patch.object(
        launcher, "_docker_build"
    ) as build:
        clone.return_value = "/tmp/pearl-cache"
        build.return_value = PEARL_IMAGE_TAG
        out = launcher.ensure_image(PEARL_IMAGE_TAG)
        assert out == PEARL_IMAGE_TAG
        clone.assert_called_once()
        build.assert_called_once()


def test_ensure_image_errors_when_non_default_tag_missing():
    import docker.errors as derr
    import pytest

    from openjarvis.mining._docker import (
        ImageAcquisitionError,
        PearlDockerLauncher,
    )
    fake = MagicMock()
    fake.images.get.side_effect = derr.ImageNotFound("nope")
    fake.images.pull.side_effect = derr.NotFound("registry refused")
    launcher = PearlDockerLauncher(client=fake)
    with pytest.raises(ImageAcquisitionError) as ei:
        launcher.ensure_image("user/custom-image:tag")
    assert "user/custom-image:tag" in str(ei.value)


@pytest.fixture
def _env_password(monkeypatch):
    monkeypatch.setenv("PEARLD_RPC_PASSWORD", "secret123")


def test_launcher_start_calls_run_with_expected_kwargs(_env_password):
    from openjarvis.mining._docker import PearlDockerLauncher
    from openjarvis.mining._stubs import MiningConfig, SoloTarget
    fake = MagicMock()
    fake.containers.run.return_value = MagicMock(id="cid-1", status="running")
    launcher = PearlDockerLauncher(client=fake)
    cfg = MiningConfig(
        provider="vllm-pearl",
        wallet_address="prl1qaaa",
        submit_target=SoloTarget(pearld_rpc_url="http://localhost:44107"),
        extra={
            "docker_image_tag": "openjarvis/pearl-miner:main",
            "model": "pearl-ai/Llama-3.3-70B-Instruct-pearl",
            "vllm_port": 8000,
            "gpu_memory_utilization": 0.9,
            "max_model_len": 8192,
            "pearld_rpc_url": "http://localhost:44107",
            "pearld_rpc_user": "rpcuser",
            "pearld_rpc_password_env": "PEARLD_RPC_PASSWORD",
            "hf_token_env": "HF_TOKEN",
        },
    )
    container = launcher.start(cfg, image="openjarvis/pearl-miner:main")
    assert container.id == "cid-1"
    fake.containers.run.assert_called_once()
    kwargs = fake.containers.run.call_args.kwargs
    assert kwargs["image"] == "openjarvis/pearl-miner:main"
    assert kwargs["command"][0] == "pearl-ai/Llama-3.3-70B-Instruct-pearl"
    assert "--gpu-memory-utilization" in kwargs["command"]
    assert kwargs["restart_policy"]["Name"] == "unless-stopped"
    assert kwargs["environment"]["PEARLD_RPC_PASSWORD"] == "secret123"
    assert kwargs["environment"]["PEARLD_MINING_ADDRESS"] == "prl1qaaa"
    assert kwargs["environment"]["MINER_RPC_TRANSPORT"] == "tcp"
    assert kwargs["device_requests"]


def test_launcher_stop_calls_container_stop_and_remove():
    from openjarvis.mining._docker import PearlDockerLauncher
    fake_client = MagicMock()
    fake_container = MagicMock()
    launcher = PearlDockerLauncher(client=fake_client)
    launcher._container = fake_container
    launcher.stop()
    fake_container.stop.assert_called_once()


def test_launcher_is_running_when_container_running():
    from openjarvis.mining._docker import PearlDockerLauncher
    fake_client = MagicMock()
    fake_container = MagicMock(status="running")
    fake_container.reload.return_value = None
    launcher = PearlDockerLauncher(client=fake_client)
    launcher._container = fake_container
    assert launcher.is_running() is True


def test_launcher_is_running_false_when_container_exited():
    from openjarvis.mining._docker import PearlDockerLauncher
    fake_client = MagicMock()
    fake_container = MagicMock()
    fake_container.reload.return_value = None
    fake_container.status = "exited"
    launcher = PearlDockerLauncher(client=fake_client)
    launcher._container = fake_container
    assert launcher.is_running() is False


def test_launcher_get_logs_returns_decoded_string():
    from openjarvis.mining._docker import PearlDockerLauncher
    fake_client = MagicMock()
    fake_container = MagicMock()
    fake_container.logs.return_value = b"hello\nworld\n"
    launcher = PearlDockerLauncher(client=fake_client)
    launcher._container = fake_container
    assert "hello" in launcher.get_logs(tail=100)


def test_launcher_start_errors_when_password_env_missing():
    from openjarvis.mining._docker import (
        ConfigurationError,
        PearlDockerLauncher,
    )
    from openjarvis.mining._stubs import MiningConfig, SoloTarget
    fake = MagicMock()
    launcher = PearlDockerLauncher(client=fake)
    cfg = MiningConfig(
        provider="vllm-pearl",
        wallet_address="prl1qaaa",
        submit_target=SoloTarget(pearld_rpc_url="http://localhost:44107"),
        extra={
            "docker_image_tag": "openjarvis/pearl-miner:main",
            "model": "pearl-ai/Llama-3.3-70B-Instruct-pearl",
            "vllm_port": 8000,
            "gpu_memory_utilization": 0.9,
            "pearld_rpc_url": "http://localhost:44107",
            "pearld_rpc_user": "rpcuser",
            "pearld_rpc_password_env": "DOES_NOT_EXIST_IN_ENV",
        },
    )
    with pytest.raises(ConfigurationError) as ei:
        launcher.start(cfg, image="openjarvis/pearl-miner:main")
    assert "DOES_NOT_EXIST_IN_ENV" in str(ei.value)
