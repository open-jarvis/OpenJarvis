"""Tests for mining/_docker.py — Docker SDK orchestration via mocks."""

from __future__ import annotations

from unittest.mock import MagicMock, patch


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
